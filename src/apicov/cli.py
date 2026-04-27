import argparse
import itertools
import runpy
import sys
import traceback
from contextlib import contextmanager
from pathlib import Path

from rich import print

from apicov.datadir import ApicovDataDir
from apicov.file_selection import file_selection_predicate
from apicov.frozen import CoverageTrace, FileFormat, dump, load
from apicov.func_tracer import UnmatchedException, UnmatchedValue
from apicov.html import generate_html_report
from apicov.settings import ApicovSettings, find_config_file, get_settings_sources, iter_cli_config
from apicov.sysmon import Tracer
from apicov.tracer_storage import TracerStorage
from apicov.type_annotation import TypeMatch


@contextmanager
def instrument_runpy(tracer):
    """Context manager hack to patch `runpy` to enable tracer.

    `runpy` is ideal for the use case because it provides a simple way to run a script
    in an isolated namespace, but it doesn't provide any hooks for instrumentation.
    """

    def instrumented_exec(*args, **kwargs):
        with tracer:
            return exec(*args, **kwargs)

    runpy.exec = instrumented_exec
    try:
        yield
    finally:
        del runpy.exec


def main() -> int:
    parser = argparse.ArgumentParser(description="API Coverage tool")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    run_parser = subparsers.add_parser("run", help="Run a script or module with API coverage tracing")
    run_parser.add_argument(
        "script", nargs="?", default=None, help="Path to the script to execute (mutually exclusive with '-m')"
    )
    run_parser.add_argument("-m", dest="module", help="Run given module as a script (mutually exclusive with 'script')")
    run_parser.add_argument("--html", action="store_true", help="Generate HTML report")
    run_parser.add_argument("--debug-json", action="store_true", help="Dump raw coverage data in JSON format")

    settings_grp = run_parser.add_argument_group("general settings")
    for name, kwargs in iter_cli_config():
        settings_grp.add_argument(f"--{name.replace('_', '-')}", **kwargs)

    html_parser = subparsers.add_parser("html", help="Generate HTML report from coverage file")

    args = parser.parse_args()
    config_file = find_config_file()
    settings = ApicovSettings.from_sources(get_settings_sources(config_file, args))
    apicov_dir = ApicovDataDir.at(config_file.path.parent if config_file else None)

    if args.command == "run":
        return run_command(run_parser, args, settings, apicov_dir)
    if args.command == "html":
        return html_command(html_parser, args, settings, apicov_dir)

    parser.error("no command specified")


def run_command(
    parser: argparse.ArgumentParser, args: argparse.Namespace, settings: ApicovSettings, apicov_dir: ApicovDataDir
) -> int:
    """Execute a script or module with tracer instrumentation and optionally generate HTML report."""
    if args.script and args.module:
        parser.error("cannot specify both a script and a module to run")
    elif not args.script and not args.module:
        parser.error("must specify a script or a module to run")

    storage = TracerStorage()
    tracer = Tracer(file_selection_predicate(settings), storage.get_tracer)
    exit_code = 0
    try:
        with instrument_runpy(tracer):
            if args.script:
                runpy.run_path(args.script, run_name="__main__")
            else:
                runpy.run_module(args.module, run_name="__main__")
    except Exception:
        # print traceback, but continue execution to also print the report
        traceback.print_exc()
        exit_code = 1

    coverage_data = storage.freeze()

    with open(apicov_dir.ensure() / "coverage", "wb") as file:
        dump(coverage_data, file, FileFormat.DEBUG if args.debug_json else FileFormat.DEFAULT)

    if args.html:
        generate_and_open_report(coverage_data, apicov_dir)
        return exit_code

    header = f"Captured calls in {args.script or args.module}:"
    print("=" * len(header))
    print(header)
    for func_info in itertools.chain.from_iterable(d.values() for d in storage.tracers.values()):
        formatted_name = f"[bold]{func_info.module}[/].[blue bold]{func_info.qualname}[/]"
        for overload, coverage in func_info.analyze_coverage().items():
            print(f"{formatted_name}[bold]{overload.signature}[/]: {coverage.total().ratio * 100:.0f}%")
            calls = func_info.matched_calls[overload]
            if not calls:
                print("  [italic]no calls[/]")
            for param_matches, result in calls:
                args_str = ", ".join(str(m) for m in param_matches)
                if isinstance(result, TypeMatch):
                    print(f"  ({args_str}) -> {result}")
                elif isinstance(result, UnmatchedValue):
                    print(f"  ({args_str}) -> [red bold]{result}[/]")
                elif isinstance(result, UnmatchedException):
                    print(f"  ({args_str}) [red italic]raised {result.exc_repr}[/]")
        if func_info.unmatched_calls:
            print(f"{formatted_name} [italic]unmatched[/]:")
            for unmatched_args, result in func_info.unmatched_calls:
                args_str = ", ".join(f"{name}: {arg}" for name, arg in unmatched_args)
                if isinstance(result, UnmatchedValue):
                    print(f"  ({args_str}) -> {result}")
                elif isinstance(result, UnmatchedException):
                    print(f"  ({args_str}) raised {result.exc_repr}")

    return exit_code


def html_command(
    parser: argparse.ArgumentParser, args: argparse.Namespace, settings: ApicovSettings, apicov_dir: ApicovDataDir
) -> int:
    """Generate HTML report from a previously saved coverage file."""
    coverage_file = apicov_dir / "coverage"
    try:
        with open(coverage_file, "rb") as file:
            frozen_data = load(file)
    except FileNotFoundError:
        parser.error(
            f"coverage file not found at {maybe_relative(coverage_file)}.\n"
            "Run a script with `run` command to generate coverage data."
        )

    generate_and_open_report(frozen_data, apicov_dir)
    return 0


def generate_and_open_report(coverage_data: CoverageTrace, apicov_dir: ApicovDataDir) -> None:
    """Generate an HTML report from coverage data into the specified directory."""
    report = apicov_dir.ensure() / "report.html"
    with open(report, "w") as file:
        for chunk in generate_html_report(coverage_data):
            file.write(chunk)
    print(f"✓ Coverage report generated: {maybe_relative(report)}")

    # Open the report in the web browser if running in an interactive terminal
    if sys.stdin.isatty() and sys.stdout.isatty():
        import webbrowser

        webbrowser.open(report.as_uri())


def maybe_relative(path: Path) -> Path:
    """Convert path to a relative one if it's inside the current working directory, for nicer display."""
    try:
        return path.relative_to(Path.cwd())
    except ValueError:
        return path


if __name__ == "__main__":
    sys.exit(main())
