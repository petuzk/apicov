import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import FrameType
from typing import Any, Literal, Self, get_overloads

from apicov.type_annotation import NoAnnotation, SelfAnnotation, TypeAnnotation, TypeMatch, get_annotation


@dataclass(frozen=True)
class Overload:
    """Represents a single overload of a function, i.e. a specific combination of parameter and return types."""

    signature: inspect.Signature
    param_annotations: tuple[TypeAnnotation, ...]  # type annotations for each parameter
    return_annotation: TypeAnnotation  # type annotation for the return value

    @classmethod
    def from_callable(cls, func: Callable[..., Any], encapsulating_class: type | None) -> Self:
        signature = inspect.signature(func)
        return cls(
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


@dataclass(frozen=True, eq=False)
class FuncTracer:
    """Tracer for a single function, matching its calls against its overloads and recording the matches."""

    matched_calls: Mapping[
        Overload,
        dict[
            # for each overload, store all calls that matched it
            tuple[tuple[TypeMatch, ...], Literal["return"], TypeMatch | None]
            | tuple[tuple[TypeMatch, ...], Literal["unwind"], str],  # store exception repr so that it's immutable
            None,
        ],
    ]
    unmatched_calls: dict[
        # store reprs of everything as a way to make it immutable
        tuple[str, Literal["return", "unwind"], str],
        None,
    ]

    @classmethod
    def from_callable(cls, func: Callable[..., Any], encapsulating_class: type | None) -> Self:
        overloads = [Overload.from_callable(f, encapsulating_class) for f in get_overloads(func) or [func]]
        return cls(
            {overload: {} for overload in overloads},
            {},
        )

    type StartKey = tuple[Overload, tuple[TypeMatch, ...]] | tuple[None, str]

    def on_start(self, frame: FrameType) -> StartKey:
        for overload in self.matched_calls.keys():
            matches = overload.match(frame)
            if matches is not None:
                return overload, matches
        # if no overload matches, return the actual argument values for reporting
        return None, ", ".join(f"{k}={v!r}" for k, v in frame.f_locals.items())

    def on_return(self, key: StartKey, retval: object) -> None:
        # the implementation is way too explicit, but this allows mypy to check it exhaustively
        exit_type: Literal["return"] = "return"
        if key[0] is not None:
            overload, matches = key
            return_match = overload.return_annotation.match(retval)
            matched_key = (matches, exit_type, return_match)
            self.matched_calls[overload][matched_key] = None
        else:
            _, args_str = key
            unmatched_key = (args_str, exit_type, repr(retval))
            self.unmatched_calls[unmatched_key] = None

    def on_unwind(self, key: StartKey, exception: BaseException) -> None:
        # the implementation is way too explicit, but this allows mypy to check it exhaustively
        exit_type: Literal["unwind"] = "unwind"
        if key[0] is not None:
            overload, matches = key
            matched_key = (matches, exit_type, repr(exception))
            self.matched_calls[overload][matched_key] = None
        else:
            _, args_str = key
            unmatched_key = (args_str, exit_type, repr(exception))
            self.unmatched_calls[unmatched_key] = None
