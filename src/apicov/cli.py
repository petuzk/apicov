import argparse
import runpy
import sys
import traceback
from contextlib import contextmanager
from functools import partial

from rich import print

from apicov.file_selection import file_selection_predicate
from apicov.func_tracer import FuncTracer, UnmatchedException, UnmatchedValue
from apicov.html import generate_html_report
from apicov.settings import ApicovSettings, find_config_file, get_settings_sources, iter_cli_config
from apicov.sysmon import AnyCallable, Tracer
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


def create_and_store_tracer(
    storage: list[FuncTracer], func: AnyCallable, encapsulating_class: type | None
) -> FuncTracer:
    tracer = FuncTracer.from_callable(func, encapsulating_class)
    storage.append(tracer)
    return tracer


def main() -> int:
    parser = argparse.ArgumentParser(description="API Coverage tool")
    parser.add_argument("script", nargs="?", default=None, help="Path to the script to execute")
    parser.add_argument("-m", dest="module", help="Run given module as a script")
    parser.add_argument("--html", action="store_true", help="Generate HTML report")

    settings_grp = parser.add_argument_group("general settings")
    for name, kwargs in iter_cli_config():
        settings_grp.add_argument(f"--{name.replace('_', '-')}", **kwargs)

    args = parser.parse_args()
    settings = ApicovSettings.from_sources(get_settings_sources(find_config_file(), args))

    if args.script and args.module:
        parser.error("cannot specify both a script and a module to run")
    elif not args.script and not args.module:
        parser.print_help()
        return 1

    func_tracers: list[FuncTracer] = []  # store FuncTracers created by the tracer, to analyze them after execution
    tracer = Tracer(file_selection_predicate(settings), partial(create_and_store_tracer, func_tracers))
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

    if args.html:
        with open("report.html", "w") as file:
            for chunk in generate_html_report(func_tracers):
                file.write(chunk)
        print("✓ Coverage report generated: report.html")
        return 0

    header = f"Captured {len(func_tracers)} called functions in {args.script or args.module}:"
    print("=" * len(header))
    print(header)
    for func_info in func_tracers:
        func = func_info.original_func
        formatted_name = f"[bold]{func.__module__}[/].[blue bold]{func.__qualname__}[/]"
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


if __name__ == "__main__":
    sys.exit(main())
