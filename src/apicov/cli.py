import argparse
import runpy
import sys
import traceback
from contextlib import contextmanager
from typing import Self

from rich import print

from apicov.sysmon import Tracer
from apicov.type_recorder import TypeRecorder


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
    parser.add_argument("script", help="Path to the script to execute")
    args = parser.parse_args()

    tracer = Tracer(args.script)
    exit_code = 0
    try:
        with instrument_runpy(tracer):
            runpy.run_path(args.script, run_name="__main__")
    except Exception:
        # print traceback, but continue execution to also print the report
        traceback.print_exc()
        exit_code = 1

    header = f"Captured {len(tracer.traced_funcs)} called functions in {tracer.filename}:"
    print("=" * len(header))
    print(header)
    for qualname, func_info in tracer.traced_funcs.items():
        # replace real annotations with recorder formatters to inject colored output
        new_sig = func_info.signature.replace(
            parameters=[
                param.replace(annotation=_RecorderFormatter.from_recorder(recorder) or param.annotation)
                for param, recorder in zip(func_info.signature.parameters.values(), func_info.param_rec)
            ],
            return_annotation=(
                _RecorderFormatter.from_recorder(func_info.return_rec) or func_info.signature.return_annotation
            ),
        )
        print(f" * {qualname}{new_sig}")

    return exit_code


class _RecorderFormatter:
    def __init__(self, recorder: TypeRecorder):
        self.recorder = recorder

    def __repr__(self):
        return self.recorder.format()

    @classmethod
    def from_recorder(cls, recorder: TypeRecorder | None) -> Self | None:
        return cls(recorder) if recorder is not None else None


if __name__ == "__main__":
    sys.exit(main())
