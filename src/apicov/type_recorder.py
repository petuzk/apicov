"""Type recorders.

Type recorder is a helper object that maps to a type annotation
and tracks whether values of that type were seen at runtime.
It also provides a method to format the result back to a type hint
string, using colors to indicate whether the type was seen or not.
"""

from abc import ABC, abstractmethod

from rich.markup import escape
from typing_inspect import get_args, is_union_type


class TypeRecorder(ABC):
    """Abstract base class for type recorders."""

    @abstractmethod
    def record_seen(self, value: object) -> None:
        """Record a value seen for this type annotation."""

    @abstractmethod
    def format(self) -> str:
        """Represent this type annotation depending on wheter it was seen."""


def get_recorder(typ: type) -> TypeRecorder:
    """Get a type recorder for the given type annotation."""
    if typ is None or typ is type(None):
        return NoneTypeRecorder()
    if is_union_type(typ):
        return UnionTypeRecorder(*get_args(typ))
    return SimpleTypeRecorder(typ)


class ColorFlagRecorder(TypeRecorder):
    """Format `label` in red or green depending on `is_seen` flag."""

    def __init__(self, label: str, is_seen: bool):
        self.label = label
        self.is_seen = is_seen

    def format(self) -> str:
        color = "green" if self.is_seen else "red"
        return f"[{color} bold]{escape(self.label)}[/]"


class SimpleTypeRecorder(ColorFlagRecorder):
    """Record simple types recognized by `isinstance` check."""

    def __init__(self, typ: type):
        super().__init__(label=typ.__name__, is_seen=False)
        self.typ = typ

    def record_seen(self, value: object) -> None:
        self.is_seen = self.is_seen or isinstance(value, self.typ)


class NoneTypeRecorder(ColorFlagRecorder):
    """Record None (and NoneType)."""

    def __init__(self):
        super().__init__(label="None", is_seen=False)

    def record_seen(self, value: object) -> None:
        self.is_seen = self.is_seen or value is None


class UnionTypeRecorder(TypeRecorder):
    """Record Unions by tracking multiple possible types."""

    def __init__(self, *types: type):
        self.types = list(map(get_recorder, types))

    def record_seen(self, value: object) -> None:
        for typ in self.types:
            typ.record_seen(value)

    def format(self) -> str:
        return " | ".join(typ.format() for typ in self.types)
