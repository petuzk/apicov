import inspect
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from functools import reduce
from operator import add
from types import NoneType
from typing import Any, Never, NoReturn

from typing_inspect import get_args, is_union_type

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

    args_cov: Collection["TypeCoverage | None"] | None = None
    """Coverage corresponding to arguments of a parametrized type annotation, or None if not parametrized.

    If TypeCoverage is produced by a parametrized type annotation, this is a Collection of
    the same length as annotation's `get_args()`. Each object is either a `TypeCoverage`
    if the corresponding argument is coverable, or None otherwise.
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


class TypeAnnotation:
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

    def get_args(self) -> Collection["TypeAnnotation | str"] | None:
        """If `self` is a parametrized type annotation, return its arguments. Otherwise return None.

        Each argument may be a TypeAnnotation (such as arguments of generic types), or a string
        representation of something that is not a type (such as arguments of typing.Annotated).
        """
        return None

    def match(self, value: object) -> TypeMatch | None:
        """Check if the given value matches this type annotation."""
        raise NotImplementedError

    def match_unwind(self, exception: BaseException) -> TypeMatch | None:
        """Check if an unwind event with the given exception matches this type annotation.

        This is only relevant for special return annotations, where
        an unwind (an exception) should contribute to its coverage (e.g. Never).
        """
        return None  # by default, unwinds do not match any type annotation

    def analyze_coverage(self, matches: set[TypeMatch], is_return: bool) -> TypeCoverage:
        """Analyze the coverage of this type annotation based on the matches it produced.

        TypeCoverage must be parametrized (i.e. have its `args_cov` set) if the type annotation is.
        """
        # by default, assume one possible type coverable by any match (i.e. 0/1 or 1/1)
        return TypeCoverage(1 if matches else 0, 1)

    def __str__(self) -> str:
        s = self.get_origin()
        if (args := self.get_args()) is not None:
            s += f"[{', '.join(map(str, args))}]"
        return s

    def __repr__(self) -> str:
        has_params = inspect.signature(type(self)).parameters
        if has_params:
            return f"<{type(self).__name__} for {self}>"
        return f"<{type(self).__name__}>"


class NoAnnotation(TypeAnnotation):
    """Special class to handle an absence of a type annotation in a generic way."""

    def get_origin(self) -> Never:
        raise TypeError("NoAnnotation has no origin")

    def __str__(self) -> str:
        return "<no annotation>"

    @dataclass(frozen=True, slots=True)
    class Match(TypeMatch):
        label: str

        def __str__(self) -> str:
            return self.label

    def match(self, value: object) -> TypeMatch | None:
        return self.Match(classify(value))  # matches everything


class SelfAnnotation(TypeAnnotation):
    """Represents the `Self` type annotation bound to a class."""

    def __init__(self, bound_class: type) -> None:
        self.bound_class = bound_class

    def get_origin(self) -> str:
        return "Self"

    def __str__(self) -> str:
        return f"Self:{self.bound_class.__qualname__}"

    class Match(TypeMatch):
        def __str__(self) -> str:
            return "Self"

    _MATCH = Match()  # singleton match object since it has no data

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
    try:
        isinstance(None, annotation)  # check if it's a simple type annotation
        return InstanceAnnotation(annotation)
    except TypeError:
        return UnknownAnnotation(repr(annotation))


class NoneAnnotation(TypeAnnotation):
    """Represents the `None` type annotation."""

    def get_origin(self) -> str:
        return "None"

    class Match(TypeMatch):
        def __str__(self) -> str:
            return "None"

    _MATCH = Match()  # singleton match object since it has no data

    def match(self, value: object) -> TypeMatch | None:
        return self._MATCH if value is None else None


class AnyAnnotation(TypeAnnotation):
    """Represents the `Any` type annotation. Matches all runtime values."""

    def get_origin(self) -> str:
        return "Any"

    class Match(TypeMatch):
        def __str__(self) -> str:
            return "Any"

    _MATCH = Match()  # singleton match object since it has no data

    def match(self, value: object) -> TypeMatch | None:
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

    def get_origin(self) -> str:
        return "Never"

    class Match(TypeMatch):
        def __str__(self) -> str:
            return "Never"

    _MATCH = Match()  # singleton match object since it has no data

    def match(self, value: object) -> TypeMatch | None:
        return None

    def match_unwind(self, exception: BaseException) -> TypeMatch | None:
        return self._MATCH

    def analyze_coverage(self, matches: set[TypeMatch], is_return: bool) -> TypeCoverage:
        # when used as a return value, coverage is 100% if there was an unwind
        if is_return:
            return TypeCoverage(1 if matches else 0, 1)
        # when used as a parameter, it will not match anything,
        # so coverage is 100% regardless of any other parameters
        return TypeCoverage(0, 0)


class InstanceAnnotation(TypeAnnotation):
    """Represents a simple type annotation like `int` or `str`."""

    def __init__(self, typ: type):
        self.typ = typ

    def get_origin(self) -> str:
        return self.typ.__qualname__

    @dataclass(frozen=True, slots=True)
    class Match(TypeMatch):
        typ: type

        def __str__(self) -> str:
            return self.typ.__qualname__

    def match(self, value: object) -> TypeMatch | None:
        if isinstance(value, self.typ):
            return self.Match(self.typ)
        return None


class UnionAnnotation(TypeAnnotation):
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

    @dataclass(frozen=True, slots=True)
    class Match(TypeMatch):
        option_index: int
        match: TypeMatch

        def __str__(self) -> str:
            return str(self.match)

    def match(self, value: object) -> TypeMatch | None:
        for i, option in enumerate(self.options):
            match = option.match(value)
            if match is not None:
                return self.Match(i, match)
        return None

    def analyze_coverage(self, matches: set[TypeMatch], is_return: bool) -> TypeCoverage:
        option_matches: dict[int, set[TypeMatch]] = {i: set() for i in range(len(self.options))}
        for match in matches:
            option_matches[match.option_index].add(match.match)
        options_cov = [option.analyze_coverage(option_matches[i], is_return) for i, option in enumerate(self.options)]
        coverage_sum = reduce(add, options_cov)
        return TypeCoverage(coverage_sum.hits, coverage_sum.total, options_cov)


class UnknownAnnotation(TypeAnnotation):
    """Fallback annotation for unsupported annotations."""

    def __init__(self, label: str):
        self.label = label

    def get_origin(self) -> str:
        return self.label

    def match(self, value: object) -> TypeMatch | None:
        return None  # we don't know how to check this type, so match nothing to avoid false positives
