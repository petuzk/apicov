import argparse
import runpy
import sys
import traceback
from contextlib import contextmanager
from functools import lru_cache

from rich import print

from apicov.func_tracer import FuncTracer
from apicov.sysmon import Tracer


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


@lru_cache
def should_trace(filename: str) -> bool:
    if filename.startswith("<") and filename.endswith(">"):
        return False  # this is not a file on disk but some magic thing, skip it
    if filename.startswith(sys.base_prefix):
        return False  # skip standard library
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="API Coverage tool")
    parser.add_argument("script", nargs="?", default=None, help="Path to the script to execute")
    parser.add_argument("-m", dest="module", help="Run given module as a script")
    args = parser.parse_args()

    if args.script and args.module:
        parser.error("cannot specify both a script and a module to run")
    elif not args.script and not args.module:
        parser.print_help()
        return 1

    tracer = Tracer(should_trace, FuncTracer.from_callable)
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

    header = f"Captured {len(tracer.traced_funcs)} called functions in {args.script or args.module}:"
    print("=" * len(header))
    print(header)
    for fullname, func_info in tracer.traced_funcs.items():
        formatted_name = f"[bold]{fullname.module}[/].[blue bold]{fullname.qualname}[/]"
        for overload, calls in func_info.matched_calls.items():
            print(f"{formatted_name}[bold]{overload.signature}[/]:")
            if not calls:
                print("  [italic]no calls[/]")
            for matches, outcome, result in calls:
                params_str = ", ".join(str(m) for m in matches)
                if outcome == "return":
                    print(f"  ({params_str}) -> {result or '[red italic]unmatched[/]'}")
                else:
                    print(f"  ({params_str}) raised {result}")
        if func_info.unmatched_calls:
            print(f"{formatted_name} [italic]unmatched[/]:")
            for args_str, outcome, result in func_info.unmatched_calls:
                if outcome == "return":
                    print(f"  ({args_str}) -> {result}")
                else:
                    print(f"  ({args_str}) raised {result}")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
