import os
import sys
from functools import lru_cache, partial

from apicov.settings import ApicovSettings
from apicov.sysmon import ShouldTraceFn


def file_selection_predicate(settings: ApicovSettings, cached: bool = True) -> ShouldTraceFn:
    """Make a predicate for selecting which files to trace."""
    includes = tuple(map(str, settings.include))
    excludes = tuple(map(str, settings.exclude))
    predicate = partial(_should_trace, includes, excludes)
    # lru_cache improves performance since the predicate is called on each python function call
    return lru_cache(predicate) if cached else predicate


def _should_trace(includes: tuple[str, ...], excludes: tuple[str, ...], filename: str) -> bool:
    if filename.startswith("<") and filename.endswith(">"):
        return False  # this is not a file on disk but some magic thing, skip it
    if filename.startswith((sys.base_prefix, sys.prefix)):
        return False  # skip libraries (standard and venv)
    # os.path has lower overhead than pathlib, and also resolves ".." parts
    normalized = os.path.abspath(filename)
    print(normalized, includes)
    return normalized.startswith(includes) and not normalized.startswith(excludes)
