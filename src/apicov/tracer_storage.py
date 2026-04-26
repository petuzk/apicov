from collections.abc import Iterable
from datetime import datetime

from apicov.frozen import (
    CoverageTrace,
    CoverageTraceMetadata,
    FuncCoverage,
    MatchedCall,
    OverloadCalls,
    SerializedTypeMatch,
    Signature,
    Type,
    UnmatchedCall,
)
from apicov.func_tracer import FuncTracer, Overload, OverloadCoverage
from apicov.sysmon import AnyCallable
from apicov.type_annotation import TypeMatch


class TracerStorage:
    """Creates and stores per-function tracers, and freezes coverage data into persistent state."""

    def __init__(self) -> None:
        self.timestamp = datetime.now()
        self.tracers: dict[str, dict[AnyCallable, FuncTracer]] = {}

    def get_tracer(self, func: AnyCallable, encapsulating_class: type | None) -> FuncTracer | None:
        """Get a tracer for the given function, creating one if it doesn't exist."""
        tracers = self.tracers.setdefault(func.__code__.co_filename, {})
        if func in tracers:
            return tracers[func]
        tracer = tracers[func] = FuncTracer.from_callable(func, encapsulating_class)
        return tracer

    def freeze(self) -> CoverageTrace:
        """Freeze the collected tracers into a persistent and serializable `CoverageTrace`."""
        return CoverageTrace(
            metadata=CoverageTraceMetadata(
                start_timestamp=self.timestamp,
            ),
            files={
                filename: {
                    tr.qualname: FuncCoverage(
                        lineno=tr.lineno,
                        matched_calls=[
                            OverloadCalls(
                                lineno=overload.lineno,
                                signature=Signature(
                                    params_annotations={
                                        param: Type.from_type_annotation(anno)
                                        for param, anno in zip(
                                            overload.signature.parameters, overload.param_annotations
                                        )
                                    },
                                    return_annotation=Type.from_type_annotation(overload.return_annotation),
                                ),
                                coverage=coverage,
                                calls=calls,
                            )
                            for overload, coverage, calls in _iter_cov_and_calls(tr)
                        ],
                        unmatched_calls=[
                            UnmatchedCall(
                                params=dict(param_matches),
                                result=result,
                            )
                            for (param_matches, result) in tr.unmatched_calls.keys()
                        ],
                    )
                    for tr in sorted(tracers.values(), key=lambda tr: tr.lineno)  # sort by line number
                }
                for filename, tracers in sorted(self.tracers.items())  # sort by filename
            },
        )


def _iter_cov_and_calls(tracer: FuncTracer) -> Iterable[tuple[Overload, OverloadCoverage, list[MatchedCall]]]:
    """Iterate over overloads of this function, yielding their coverage and matched calls."""
    per_overload_cov = tracer.analyze_coverage()
    assert per_overload_cov.keys() == tracer.matched_calls.keys()
    for overload, calls in tracer.matched_calls.items():
        coverage = per_overload_cov[overload]
        yield (
            overload,
            coverage,
            [
                MatchedCall(params=list(map(_serialize_match, params)), result=_serialize_match(result))
                for params, result in calls.keys()
            ],
        )


def _serialize_match[T](obj: TypeMatch | T) -> SerializedTypeMatch | T:
    """Convert a match result into a serializable form."""
    if isinstance(obj, TypeMatch):
        return SerializedTypeMatch(match=str(obj))
    return obj
