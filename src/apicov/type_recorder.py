"""Type recorders.

Type recorder is a helper object that maps to a type annotation
and tracks whether values of that type were seen at runtime.
It also provides a method to format the result back to a type hint
string, using colors to indicate whether the type was seen or not.
"""

from abc import ABC
from typing_inspect import get_args, is_union_type


class TypeRecorder(ABC):
    """Abstract base class for type recorders."""

    def record_seen(self, value: object) -> None:
        """Record a value seen for this type annotation."""

    def format(self) -> str:
        """Represent this type annotation depending on wheter it was seen."""


def get_recorder(typ: type) -> TypeRecorder:
    """Get a type recorder for the given type annotation."""
    if typ is None or typ is type(None):
        return NoneTypeRecorder()
    if is_union_type(typ):
        return UnionTypeRecorder(*get_args(typ))
    return SimpleTypeRecorder(typ)


class SimpleTypeRecorder(TypeRecorder):
    """Record simple types recognized by `isinstance` check."""

    def __init__(self, typ: type):
        self.typ = typ
        self.is_seen = False

    def record_seen(self, value: object) -> None:
        self.is_seen = self.is_seen or isinstance(value, self.typ)

    def format(self) -> str:
        color = "green" if self.is_seen else "red"
        return f"[{color} bold]{self.typ.__name__}[/]"


class NoneTypeRecorder(TypeRecorder):
    """Record None (and NoneType)."""

    def __init__(self):
        self.is_seen = False

    def record_seen(self, value: object) -> None:
        self.is_seen = self.is_seen or value is None

    def format(self) -> str:
        color = "green" if self.is_seen else "red"
        return f"[{color} bold]None[/]"


class UnionTypeRecorder(TypeRecorder):
    """Record Unions by tracking multiple possible types."""

    def __init__(self, *types: type):
        self.types = list(map(get_recorder, types))

    def record_seen(self, value: object) -> None:
        for typ in self.types:
            typ.record_seen(value)

    def format(self) -> str:
        return " | ".join(typ.format() for typ in self.types)
