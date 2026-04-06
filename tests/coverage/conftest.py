from functools import partial
from pathlib import Path

import pytest

from apicov.func_tracer import FuncTracer, Overload
from apicov.sysmon import AnyCallable, Tracer


@pytest.fixture
def apicov(request):
    """Fixture that provides API coverage tracing for functions defined in test files."""
    return ApicovFixture(request.path)


class ApicovFixture:
    """Tracer for functions defined in test files."""

    def __init__(self, test_path: Path):
        self.func_tracers: dict[AnyCallable, FuncTracer] = {}
        self.tracer = Tracer(test_path.samefile, partial(_create_and_store_tracer, self.func_tracers))

    def __enter__(self) -> None:
        self.tracer.__enter__()

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.tracer.__exit__(exc_type, exc_value, traceback)

    def analyze(self, func: AnyCallable, overload: AnyCallable = None):
        """Analyze coverage for a function or a specific overload of it."""
        try:
            tracer = self.func_tracers[func]
        except KeyError:
            raise ValueError(f"function {func} was not traced") from None
        cov = tracer.analyze_coverage()
        if overload is None:
            assert len(cov) == 1, f"multiple overloads found for {func}, specify overload to analyze"
            return next(iter(cov.values()))
        return cov[Overload.from_callable(overload)]


def _create_and_store_tracer(
    storage: dict[AnyCallable, FuncTracer], func: AnyCallable, encapsulating_class: type | None
) -> FuncTracer:
    tracer = FuncTracer.from_callable(func, encapsulating_class)
    storage[func] = tracer
    return tracer
