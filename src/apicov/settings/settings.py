import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ApicovSettings:
    """Settings for apicov.

    This defines all settings configurable in a config file or via CLI.
    """


_CONFIG_FILES_PREFIXES = {
    ".apicov.toml": (),
    "apicov.toml": (),
    "pyproject.toml": ("tool", "apicov"),
}


def find_config_file(root: Path | None = None) -> tuple[Path, dict[str, Any]] | None:
    """Find and parse a configuration file in specified `root` directory, or any directory from CWD and up."""
    if root is None:
        cwd = Path.cwd()
        candidate_dirs = [cwd, *cwd.parents]
    else:
        candidate_dirs = [root]

    for config_dir in candidate_dirs:
        for filename, prefix in _CONFIG_FILES_PREFIXES.items():
            path = config_dir / filename
            if not path.is_file():
                continue
            with open(path, "rb") as file:
                config = tomllib.load(file)
            for key in prefix:
                config = config.get(key, {})
            if not isinstance(config, dict):
                raise ValueError(f"config in {path} is not a dict")
            return path, config

    return None
