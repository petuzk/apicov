import inspect
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from functools import reduce
from operator import mul
from reprlib import Repr
from types import FrameType
from typing import Any, Self, get_overloads

from apicov.classify import classify
from apicov.sysmon import AnyCallable
from apicov.type_annotation import NoAnnotation, SelfAnnotation, TypeAnnotation, TypeCoverage, TypeMatch, get_annotation
from apicov.util import transpose_into_sets

_repr = Repr(maxlong=20, maxstring=50, maxother=50).repr


@dataclass(frozen=True)
class Overload:
    """Represents a single overload of a function, i.e. a specific combination of parameter and return types."""

    original_func: AnyCallable
    signature: inspect.Signature = field(compare=False)
    param_annotations: tuple[TypeAnnotation, ...] = field(compare=False)  # type annotations for each parameter
    return_annotation: TypeAnnotation = field(compare=False)  # type annotation for the return value

    @classmethod
    def from_callable(cls, func: AnyCallable, encapsulating_class: type | None = None) -> Self:
        try:
            signature = inspect.signature(func, eval_str=True)
        except Exception:
            # perhaps the exception comes from evaluating stringized annotations, try again without evaluating them
            signature = inspect.signature(func)
        return cls(
            func,
            signature,
            tuple(
                cls._get_param_annotation(i, param, encapsulating_class)
                for i, param in enumerate(signature.parameters.values())
            ),
            cls._get_return_annotation(signature, encapsulating_class),
        )

    @staticmethod
    def _get_param_annotation(index: int, param: inspect.Parameter, encapsulating_class: type | None) -> TypeAnnotation:
        annotation = param.annotation
        if (annotation is Self or (index == 0 and param.name == "self")) and encapsulating_class is not None:
            return SelfAnnotation(encapsulating_class)
        if annotation is inspect.Parameter.empty:
            return NoAnnotation()
        return get_annotation(annotation)

    @staticmethod
    def _get_return_annotation(signature: inspect.Signature, encapsulating_class: type | None) -> TypeAnnotation:
        annotation = signature.return_annotation
        if annotation is Self and encapsulating_class is not None:
            return SelfAnnotation(encapsulating_class)
        if annotation is inspect.Signature.empty:
            return NoAnnotation()
        return get_annotation(annotation)

    def match(self, frame: FrameType) -> tuple[TypeMatch, ...] | None:
        """Inspect the given frame, and match values against this overload's parameter annotations.

        The frame is expected to be at the start of a call to the function corresponding to this overload,
        so its local variables should correspond to the parameters of this overload.
        If all parameters match, return a tuple of their TypeMatches. If any parameter doesn't match, return None.
        """
        matches = []
        for param, annotation in zip(self.signature.parameters.values(), self.param_annotations):
            match = annotation.match(frame.f_locals[param.name])
            if match is None:
                return None  # if any parameter doesn't match, this overload doesn't match
            matches.append(match)
        return tuple(matches)

    def analyze_coverage(self, matches: Iterable[tuple[tuple[TypeMatch, ...], TypeMatch]]) -> "OverloadCoverage":
        """Analyze total coverage of this overload based on the matches it produced in runtime."""
        # prepare tuples of TypeAnnotations, corresponding sets of TypeMatches,
        # and flags indicating which of them are return annotations
        annotations = (*self.param_annotations, self.return_annotation)
        are_returns = (*([False] * len(self.param_annotations)), True)

        flattened = ((*params, return_match) for params, return_match in matches)
        match_sets = transpose_into_sets(flattened, n=len(annotations))  # group matches by annotation
        coverages = tuple(
            annotation.analyze_coverage(matches, is_ret)
            for annotation, matches, is_ret in zip(annotations, match_sets, are_returns)
        )
        return OverloadCoverage(coverages[:-1], coverages[-1])


@dataclass(frozen=True)
class OverloadCoverage:
    """Represents the detailed coverage of a single overload."""

    param_coverages: tuple[TypeCoverage, ...]  # coverage of each parameter annotation
    return_coverage: TypeCoverage  # coverage of the return annotation

    def total(self) -> TypeCoverage:
        """Calculate total coverage of this overload based on the coverage of its parameters and return type."""
        return reduce(mul, self.param_coverages, self.return_coverage)


@dataclass(frozen=True)
class UnmatchedValue:
    """Information about runtime value that did not match its type annotation."""

    type_label: str

    def __str__(self) -> str:
        return self.type_label

    @classmethod
    def from_value(cls, value: Any) -> Self:
        return cls(classify(value))


@dataclass(frozen=True)
class UnmatchedException:
    """Information about an exception raised from a traced function that did not match the return type annotation."""

    exc_repr: str

    def __str__(self) -> str:
        return self.exc_repr

    @classmethod
    def from_exception(cls, exception: BaseException) -> Self:
        return cls(_repr(exception))


@dataclass(frozen=True, eq=False)
class FuncTracer:
    """Tracer for a single function, matching its calls against its overloads and recording the matches."""

    type MatchedArgs = tuple[TypeMatch, ...]
    type UnmatchedArgs = tuple[tuple[str, UnmatchedValue], ...]  # represents a mapping immutably
    type UnmatchedResult = UnmatchedValue | UnmatchedException

    original_func: AnyCallable
    matched_calls: Mapping[
        # For each overload, store all calls that matched its parameters as a tuple
        # (matches for parameters, return match or UnmatchedResult)
        # Note that non-matching result (return/unwind) is still stored in matched_calls.
        # Use dict with None values for ordered set semantics, and potential storage for per-call metadata.
        Overload, dict[tuple[MatchedArgs, TypeMatch | UnmatchedResult], None]
    ]
    # Store calls that did not match any overload as (tuple({parameter name: argument}.items()), UnmatchedResult)
    unmatched_calls: dict[tuple[UnmatchedArgs, UnmatchedResult], None]

    @classmethod
    def from_callable(cls, func: AnyCallable, encapsulating_class: type | None = None) -> Self:
        overloads = [Overload.from_callable(f, encapsulating_class) for f in get_overloads(func) or [func]]
        return cls(
            func,
            {overload: {} for overload in overloads},
            {},
        )

    type _StartKey = tuple[Overload, MatchedArgs] | tuple[None, UnmatchedArgs]

    def on_start(self, frame: FrameType) -> _StartKey:
        """Select an overload matching this call, and return a key with parameter matches.

        If no overload matches, return a key with a string representation of the arguments.
        """
        for overload in self.matched_calls.keys():
            matches = overload.match(frame)
            if matches is not None:
                return overload, matches
        # if no overload matches, return parameter names and argument types
        return None, tuple((k, UnmatchedValue.from_value(v)) for k, v in frame.f_locals.items())

    def on_return(self, key: _StartKey, retval: object) -> None:
        """Record a call started with `key` which returned the given return value."""
        if key[0] is not None:
            overload, matches = key
            result = overload.return_annotation.match(retval) or UnmatchedValue.from_value(retval)
            self.matched_calls[overload][(matches, result)] = None
        else:
            _, unmatched_args = key
            self.unmatched_calls[(unmatched_args, UnmatchedValue.from_value(retval))] = None

    def on_unwind(self, key: _StartKey, exception: BaseException) -> None:
        """Record a call started with `key` which raised the given exception."""
        if key[0] is not None:
            overload, matches = key
            result = overload.return_annotation.match_unwind(exception) or UnmatchedException.from_exception(exception)
            self.matched_calls[overload][(matches, result)] = None
        else:
            _, unmatched_args = key
            self.unmatched_calls[(unmatched_args, UnmatchedException.from_exception(exception))] = None

    def analyze_coverage(self) -> dict[Overload, OverloadCoverage]:
        """Analyze coverage of each overload based on recorded runtime values."""
        return {
            # ignore calls that did not match the return type as they are non compliant with API
            overload: overload.analyze_coverage(
                (matches, return_match) for (matches, return_match) in calls if isinstance(return_match, TypeMatch)
            )
            for overload, calls in self.matched_calls.items()
        }
