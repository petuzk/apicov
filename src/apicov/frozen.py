"""Frozen (de)serializable representation of API coverage data.

This format contains enough information to build the coverage report,
but can no longer be used to update coverage with new calls.
"""

from datetime import datetime
from enum import Enum, auto
from importlib.metadata import version
from lzma import compress, decompress
from typing import IO, Literal, Self, overload

from pydantic import BaseModel, Field

from apicov.func_tracer import OverloadCoverage, UnmatchedException, UnmatchedValue
from apicov.type_annotation import NoAnnotation, ParametrizedTypeAnnotation, TypeAnnotation


class CoverageTrace(BaseModel):
    """A snapshot of collected API coverage data."""

    metadata: "CoverageTraceMetadata"
    files: dict[str, dict[str, "FuncCoverage"]] = Field(
        description="Two-level mapping where keys are filename and then function qualname.",
    )


class CoverageTraceMetadata(BaseModel):
    """Metadata describing the collected data and the session in which it was collected."""

    start_timestamp: datetime
    apicov_version: str = version("apicov")
    format_version: int = 0


class FuncCoverage(BaseModel):
    """Coverage data for a single function."""

    lineno: int = Field(description="Line number of the function definition.")
    matched_calls: list["OverloadCalls"]
    unmatched_calls: list["UnmatchedCall"]


class OverloadCalls(BaseModel):
    """Coverage data for calls matching a single function overload."""

    lineno: int = Field(
        description="Line number of the overload definition (matches function definition if there are no overloads).",
    )
    signature: "Signature"
    coverage: OverloadCoverage
    calls: list["MatchedCall"]


class Signature(BaseModel):
    """Function signature."""

    params_annotations: dict[str, "Type | None"]
    return_annotation: "Type | None"


class Type(BaseModel):
    """A type annotation or a type argument."""

    cls: str | None = Field(
        default=None,
        description=(
            "Name of the TypeAnnotation class that represents this type, "
            "or None if this is not a type (e.g. a string literal in Annotated args)."
        ),
    )
    origin: str = Field(
        description="Base type that this annotation represents (same as `TypeAnnotation.get_origin()`)."
    )
    args: list[Self] | None = None

    @classmethod
    @overload
    def from_type_annotation(cls, anno: TypeAnnotation, allow_no_annotation: Literal[False]) -> Self: ...

    @classmethod
    @overload
    def from_type_annotation(cls, anno: TypeAnnotation, allow_no_annotation: Literal[True] = True) -> Self | None: ...

    @classmethod
    def from_type_annotation(cls, anno: TypeAnnotation, allow_no_annotation: bool = True) -> Self | None:
        if isinstance(anno, NoAnnotation):
            if allow_no_annotation:
                return None
            raise ValueError("annotation is NoAnnotation, but allow_no_annotation is False")
        if isinstance(anno, ParametrizedTypeAnnotation):
            args = [
                Type(origin=arg) if isinstance(arg, str) else Type.from_type_annotation(arg, allow_no_annotation=False)
                for arg in anno.get_args()
            ]
        else:
            args = None
        return cls(cls=anno.__class__.__name__, origin=anno.get_origin(), args=args)


class MatchedCall(BaseModel):
    """A call that matched overload parameters' types, but not necessarily its return type."""

    params: list["SerializedTypeMatch"]
    result: "SerializedTypeMatch | UnmatchedValue | UnmatchedException"


class UnmatchedCall(BaseModel):
    """A call that did not match any overload."""

    params: dict[str, UnmatchedValue]
    result: UnmatchedValue | UnmatchedException


class SerializedTypeMatch(BaseModel):
    """Corresponds to string representation of a `TypeMatch` instance."""

    match: str


class FileFormat(Enum):
    """Format of coverage data in a file."""

    DEFAULT = auto()
    """Default format: JSON-serialized data compressed with XZ. Not human-readable, but compact on disk."""

    DEBUG = auto()
    """Debug format: uncompressed JSON with indentation. Human-readable, but takes more disk space."""


def dump(coverage_data: CoverageTrace, file: IO[bytes], fmt: FileFormat = FileFormat.DEFAULT) -> None:
    """Serialize coverage data into a file."""
    indent = 4 if fmt == FileFormat.DEBUG else None
    serialized = coverage_data.model_dump_json(indent=indent).encode("utf-8")
    if fmt == FileFormat.DEFAULT:
        serialized = compress(serialized)
    file.write(serialized)


def load(file: IO[bytes]) -> CoverageTrace:
    """Deserialize coverage data from a file. Format is auto-detected based on file content."""
    pos = file.tell()
    magic = file.read(1)
    file.seek(pos)
    if magic == b"\xfd":  # XZ
        data = decompress(file.read())
    elif magic == b"{":  # JSON
        data = file.read()
    else:
        raise ValueError(f"unrecognized file format: {magic.hex()}")
    return CoverageTrace.model_validate_json(data)
