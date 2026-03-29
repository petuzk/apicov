import inspect
import sys
from collections.abc import Collection, Iterable
from collections.abc import Set as ImmutableSet
from dataclasses import dataclass
from enum import Enum
from functools import reduce
from operator import add
from types import NoneType
from typing import TYPE_CHECKING, Any, Generic, Literal, Never, NoReturn, TypeAlias, TypeVar

from typing_inspect import get_args, get_origin, is_union_type

from apicov.classify import classify


class TypeMatch:
    """A successful match of a runtime value against a type annotation.

    This object represents the type of a runtime value to the extent of detail
    that the type annotation requires. It should contain enough data relevant to
    analyzing the coverage of TypeAnnotation that produced the match.

    For example, given a type annotation `list[int | str]`, and a runtime value `[42]`,
    a TypeMatch would indicate that the value is a `list[int]`.
    Contrarily, if the type annotation was e.g. `Any`, the TypeMatch doesn't need to contain
    any information, since the annotation doesn't require any specific type.
    """

    __slots__ = ()


@dataclass(frozen=True, slots=True)
class TypeCoverage:
    """Represents the coverage of a type annotation, function signature or other measurable unit.

    Type coverage is most meaningful with unions, and denotes which of its members were seen at runtime.
    For example, given a type annotation `int | str`, an `int` runtime value covers 1/2 types (50%).
    This approach can also be applied to a function signature, by treating it as a union of all
    possible permutations of parameter and return types. For example, given a function with signature
    `(int | str) -> str | None`, there are 4 possible permutations to be covered:
    `(int) -> str`, `(int) -> None`, `(str) -> str` and `(str) -> None`.
    """

    hits: int
    """Indicates how many permutations of types were actually seen at runtime."""

    total: int
    """Indicates how many permutations of types exist for this annotation.

    For example, for `int | str` total is 2, and for `(int | str) -> str | None` total is 4.
    The value of zero implies that there are no possible permutations, so it is considered 100% coverage.
    """

    @property
    def ratio(self) -> float:
        """Calculate the coverage ratio as hits divided by total, or 1.0 if total is zero."""
        return self.hits / self.total if self.total > 0 else 1.0

    def __mul__(self, other: "TypeCoverage") -> "TypeCoverage":
        """Element-wise multiplication of coverage.

        Useful for combining parameter/return value coverages into signature coverage.
        """
        if not isinstance(other, TypeCoverage):
            return NotImplemented
        return TypeCoverage(self.hits * other.hits, self.total * other.total)

    def __add__(self, other: "TypeCoverage") -> "TypeCoverage":
        """Element-wise addition of coverage.

        Useful for combining coverage from multiple signatures.
        """
        if not isinstance(other, TypeCoverage):
            return NotImplemented
        return TypeCoverage(self.hits + other.hits, self.total + other.total)


@dataclass(frozen=True, slots=True)
class ParametrizedTypeCoverage(TypeCoverage):
    args_cov: Collection[TypeCoverage | None]
    """Coverage corresponding to arguments of a ParametrizedTypeAnnotation.

    This Collection must be of the same length as annotation's `get_args()`. Each object
    is either a `TypeCoverage` if the corresponding argument is coverable, or None otherwise.
    """


# Genericness of TypeAnnotation is an implementation detail to define type returned by match
# and accepted by analyze_coverage for the type checker. For the caller, a TypeAnnotation
# always returns some unspecified TypeMatch object.
if TYPE_CHECKING or sys.version_info >= (3, 13):  # default is a 3.13 feature
    TM = TypeVar("TM", bound=TypeMatch, covariant=True, default=TypeMatch)
else:
    TM = TypeVar("TM", bound=TypeMatch, covariant=True)


class TypeAnnotation(Generic[TM]):  # noqa: UP046 (explicit TypeVar must be used with Generic)
    """Represents a type annotation in a function signature.

    Allows matching it against runtime values, and analyzing coverage
    from matches produced by this annotation.
    """

    def get_origin(self) -> str:
        """Get name of the base type this annotation represents.

        This should correspond to type annotation minus its arguments.
        For example, for `int` this should be `int`, and for `list[str]` this should be `list`.
        """
        raise NotImplementedError

    def match(self, value: object) -> TM | None:
        """Check if the given value matches this type annotation."""
        raise NotImplementedError

    def match_unwind(self, exception: BaseException) -> TM | None:
        """Check if an unwind event with the given exception matches this type annotation.

        This is only relevant for special return annotations, where
        an unwind (an exception) should contribute to its coverage (e.g. Never).
        """
        return None  # by default, unwinds do not match any type annotation

    def analyze_coverage(self, matches: ImmutableSet[TM], is_return: bool) -> TypeCoverage:
        """Analyze the coverage of this type annotation based on the matches it produced."""
        # by default, assume one possible type coverable by any match (i.e. 0/1 or 1/1)
        return TypeCoverage(1 if matches else 0, 1)

    def __str__(self) -> str:
        return self.get_origin()

    def __repr__(self) -> str:
        has_params = inspect.signature(type(self)).parameters
        if has_params:
            return f"<{type(self).__name__} for {self}>"
        return f"<{type(self).__name__}>"


class ParametrizedTypeAnnotation(TypeAnnotation[TM]):
    def get_args(self) -> Collection[TypeAnnotation | str]:
        """Get arguments of a parametrized type annotation.

        Each argument may be a TypeAnnotation (such as arguments of generic types), or a string
        representation of something that is not a type (such as arguments of typing.Annotated).
        """
        raise NotImplementedError

    def analyze_coverage(self, matches: ImmutableSet[TM], is_return: bool) -> ParametrizedTypeCoverage:
        """Analyze the coverage of this type annotation based on the matches it produced."""
        raise NotImplementedError

    def __str__(self) -> str:
        return self.get_origin() + f"[{', '.join(map(str, self.get_args()))}]"


@dataclass(frozen=True, slots=True)
class _SimpleTypeMatch(TypeMatch):
    """A type match that only stores a label representing the type of a runtime value."""

    type_label: str

    def __str__(self) -> str:
        return self.type_label


class NoAnnotation(TypeAnnotation):
    """Special class to handle an absence of a type annotation in a generic way."""

    def get_origin(self) -> Never:
        raise TypeError("NoAnnotation has no origin")

    def __str__(self) -> str:
        return "<no annotation>"

    def match(self, value: object) -> TypeMatch:
        return _SimpleTypeMatch(classify(value))  # matches everything


class SelfAnnotation(TypeAnnotation):
    """Represents the `Self` type annotation bound to a class."""

    def __init__(self, bound_class: type) -> None:
        self.bound_class = bound_class

    @staticmethod
    def get_origin() -> str:
        return "Self"

    def __str__(self) -> str:
        return f"Self:{self.bound_class.__qualname__}"

    _MATCH = _SimpleTypeMatch(get_origin())

    def match(self, value: object) -> TypeMatch | None:
        return self._MATCH if isinstance(value, self.bound_class) else None


def get_annotation(annotation: Any) -> TypeAnnotation:
    """Parse a type annotation and return a TypeAnnotation object representing it."""
    if annotation is None or annotation is NoneType:
        return NoneAnnotation()
    if annotation is Any:
        return AnyAnnotation()
    if annotation is Never or annotation is NoReturn:
        return NeverAnnotation()
    if is_union_type(annotation):
        return UnionAnnotation(map(get_annotation, get_args(annotation)))
    if (origin := get_origin(annotation)) is not None:
        # annotation is a parametrized type
        if origin is Literal:
            return LiteralAnnotation(get_args(annotation))
        return UnknownAnnotation(repr(annotation))
    try:
        isinstance(None, annotation)  # check if it's a simple type annotation
        return InstanceAnnotation(annotation)
    except TypeError:
        return UnknownAnnotation(repr(annotation))


class NoneAnnotation(TypeAnnotation):
    """Represents the `None` type annotation."""

    @staticmethod
    def get_origin() -> str:
        return "None"

    _MATCH = _SimpleTypeMatch(get_origin())

    def match(self, value: object) -> TypeMatch | None:
        return self._MATCH if value is None else None


class AnyAnnotation(TypeAnnotation):
    """Represents the `Any` type annotation. Matches all runtime values."""

    @staticmethod
    def get_origin() -> str:
        return "Any"

    _MATCH = _SimpleTypeMatch(get_origin())

    def match(self, value: object) -> TypeMatch:
        return self._MATCH  # matches everything


class NeverAnnotation(TypeAnnotation):
    """Represents the `Never` type annotation.

    This annotation never matches any runtime values:
      - when used as a parameter annotation, it makes any function call non-compliant
        with regards to declared interface (which also impacts overload resolution)
      - when used as a return annotation, it makes any return a violation of declared interface

    However, unwinding due to an exception is considered a match for Never,
    since the function does not return in this case.
    """

    @staticmethod
    def get_origin() -> str:
        return "Never"

    _MATCH = _SimpleTypeMatch(get_origin())

    def match(self, value: object) -> None:
        return None

    def match_unwind(self, exception: BaseException) -> TypeMatch:
        return self._MATCH

    def analyze_coverage(self, matches: ImmutableSet[TypeMatch], is_return: bool) -> TypeCoverage:
        # when used as a return value, coverage is 100% if there was an unwind
        if is_return:
            return TypeCoverage(1 if matches else 0, 1)
        # when used as a parameter, it will not match anything,
        # so coverage is 100% regardless of any other parameters
        return TypeCoverage(0, 0)


@dataclass(frozen=True, slots=True)
class _InstanceMatch(TypeMatch):
    typ: type

    def __str__(self) -> str:
        return self.typ.__qualname__


class InstanceAnnotation(TypeAnnotation):
    """Represents a simple type annotation like `int` or `str`."""

    def __init__(self, typ: type):
        self.typ = typ

    def get_origin(self) -> str:
        return self.typ.__qualname__

    def match(self, value: object) -> TypeMatch | None:
        return _InstanceMatch(self.typ) if isinstance(value, self.typ) else None


@dataclass(frozen=True, slots=True)
class _UnionMatch(TypeMatch):
    option_index: int
    match: TypeMatch

    def __str__(self) -> str:
        return str(self.match)


class UnionAnnotation(ParametrizedTypeAnnotation[_UnionMatch]):
    """Represents a union type annotation like `int | str`."""

    def __init__(self, options: Iterable[TypeAnnotation]):
        self.options = tuple(options)
        if not self.options:
            raise ValueError("empty union")

    def get_origin(self) -> str:
        return "Union"

    def get_args(self) -> tuple[TypeAnnotation, ...]:
        return self.options

    def __str__(self) -> str:
        return " | ".join(map(str, self.options))

    def match(self, value: object) -> _UnionMatch | None:
        for i, option in enumerate(self.options):
            match = option.match(value)
            if match is not None:
                return _UnionMatch(i, match)
        return None

    def analyze_coverage(self, matches: ImmutableSet[_UnionMatch], is_return: bool) -> ParametrizedTypeCoverage:
        option_matches: dict[int, set[TypeMatch]] = {i: set() for i in range(len(self.options))}
        for match in matches:
            option_matches[match.option_index].add(match.match)
        options_cov = [option.analyze_coverage(option_matches[i], is_return) for i, option in enumerate(self.options)]
        coverage_sum = reduce(add, options_cov)
        return ParametrizedTypeCoverage(coverage_sum.hits, coverage_sum.total, options_cov)


# not a type statement to make it usable for isinstance check
LiteralOption: TypeAlias = int | str | bytes | bool | Enum | None  # noqa: UP040 (see above)


@dataclass(frozen=True, slots=True)
class _LiteralMatch(TypeMatch):
    option: LiteralOption

    def __str__(self) -> str:
        return f"Literal[{self.option!r}]"


class LiteralAnnotation(ParametrizedTypeAnnotation[_LiteralMatch]):
    """Represents a typing.Literal annotation.

    Specification: https://typing.python.org/en/latest/spec/literal.html
    """

    def __init__(self, options: Iterable[LiteralOption]):
        self.options = dict.fromkeys(options)  # ordered set semantics

    def get_origin(self) -> str:
        return "Literal"

    def get_args(self) -> list[str]:
        return [repr(opt) for opt in self.options]

    def match(self, value: object) -> _LiteralMatch | None:
        if isinstance(value, LiteralOption) and value in self.options:
            return _LiteralMatch(value)
        return None

    def analyze_coverage(self, matches: ImmutableSet[_LiteralMatch], is_return: bool) -> ParametrizedTypeCoverage:
        covered_options = {match.option for match in matches}
        return ParametrizedTypeCoverage(
            hits=len(covered_options),
            total=len(self.options),
            args_cov=[TypeCoverage(int(opt in covered_options), 1) for opt in self.options],
        )


class UnknownAnnotation(TypeAnnotation):
    """Fallback annotation for unsupported annotations."""

    def __init__(self, label: str):
        self.label = label

    def get_origin(self) -> str:
        return self.label

    def match(self, value: object) -> None:
        return None  # we don't know how to check this type, so match nothing to avoid false positives
