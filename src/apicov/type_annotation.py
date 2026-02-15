from dataclasses import dataclass
from typing import Any

from typing_inspect import get_args, is_union_type


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


class TypeAnnotation:
    """Represents a type annotation in a function signature.

    Allows matching it against runtime values, and analyzing coverage
    from matches produced by this annotation.
    """

    def match(self, value: object) -> TypeMatch | None:
        """Check if the given value matches this type annotation."""
        raise NotImplementedError


class NoAnnotation(TypeAnnotation):
    """Special class to handle an absence of a type annotation in a generic way."""

    class Match(TypeMatch):
        def __str__(self) -> str:
            return "?"

    _MATCH = Match()  # singleton match object since it has no data

    def match(self, value: object) -> TypeMatch | None:
        return self._MATCH  # matches everything


def get_annotation(annotation: Any) -> TypeAnnotation:
    """Parse a type annotation and return a TypeAnnotation object representing it."""
    if annotation is None or annotation is type(None):
        return NoneAnnotation()
    if is_union_type(annotation):
        return UnionAnnotation(*map(get_annotation, get_args(annotation)))
    try:
        isinstance(None, annotation)  # check if it's a simple type annotation
        return InstanceAnnotation(annotation)
    except TypeError:
        return UnknownAnnotation(str(annotation))


class NoneAnnotation(TypeAnnotation):
    """Represents the `None` type annotation."""

    class Match(TypeMatch):
        def __str__(self) -> str:
            return "None"

    _MATCH = Match()  # singleton match object since it has no data

    def match(self, value: object) -> TypeMatch | None:
        return self._MATCH if value is None else None


class InstanceAnnotation(TypeAnnotation):
    """Represents a simple type annotation like `int` or `str`."""

    def __init__(self, typ: type):
        self.typ = typ

    @dataclass(frozen=True, slots=True)
    class Match(TypeMatch):
        typ: type

        def __str__(self) -> str:
            return self.typ.__name__

    def match(self, value: object) -> TypeMatch | None:
        if isinstance(value, self.typ):
            return self.Match(self.typ)
        return None


class UnionAnnotation(TypeAnnotation):
    """Represents a union type annotation like `int | str`."""

    def __init__(self, *options: TypeAnnotation):
        self.options = options

    @dataclass(frozen=True, slots=True)
    class Match(TypeMatch):
        option: TypeAnnotation
        match: TypeMatch

        def __str__(self) -> str:
            return str(self.match)

    def match(self, value: object) -> TypeMatch | None:
        for option in self.options:
            match = option.match(value)
            if match is not None:
                return self.Match(option, match)
        return None


class UnknownAnnotation(TypeAnnotation):
    """Fallback annotation for unsupported annotations."""

    def __init__(self, label: str):
        self.label = label

    class Match(TypeMatch):
        def __str__(self) -> str:
            return "<unknown>"

    _MATCH = Match()  # singleton match object since it has no data

    def match(self, value: object) -> TypeMatch | None:
        return self._MATCH  # we don't know how to check this type, so match everything
