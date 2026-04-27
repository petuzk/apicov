"""Generic machinery for application settings. Not aware of apicov settings structure.

The machinery allows to construct a Settings dataclass from multiple sources in the following
precedence:
  - CLI
  - configuration file
  - default values

It supports different base path (for relative path handling) for each source, since it's
typically a CWD for CLI, and root directory for a config file. It also helps to build
argparse CLI.

Validation strategy: all values from all sources are validated, regardless of whether
they are effective. This helps to prevent hidden configuration issues.
"""

from argparse import Namespace
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import MISSING, Field, dataclass, fields
from pathlib import Path
from typing import Any, Literal, Self, get_origin


@dataclass(frozen=True)
class Setting:
    """Represents configuration for a single setting."""

    description: str | None = None
    cli: bool = True  # whether can be configured via CLI
    config: bool = True  # whether can be configured via config file
    metavar: str | None = None
    nargs: Literal["+"] | None = None

    _METADATA_KEY = "apicov_setting"

    def into_meta(self) -> dict[str, Self]:
        return {self._METADATA_KEY: self}

    @classmethod
    def from_meta(cls, meta: Mapping[str, Any]) -> Self:
        value = meta.get(cls._METADATA_KEY, cls())
        assert isinstance(value, cls), f"unexpected {value=}"
        return value


def iter_settings(settings_type: type) -> Iterator[tuple[str, type, Setting]]:
    return ((field.name, _get_field_type(field), Setting.from_meta(field.metadata)) for field in fields(settings_type))


def iter_cli_config(settings_type: type) -> Iterator[tuple[str, dict[str, Any]]]:
    for name, _, setting in iter_settings(settings_type):
        if setting.cli:
            kwargs = {
                "dest": cli_dest(settings_type, name),  # make dest predictable regardless of option name
                "default": MISSING,  # reuse sentinel from dataclasses to indicate that value was not passed
                "help": setting.description,
                "metavar": setting.metavar,
                "nargs": setting.nargs,
            }
            yield name, kwargs


@dataclass(frozen=True)
class RawConfigFile:
    """Represents a raw configuration file found in the project, without any processing or validation."""

    path: Path
    raw_config: dict[str, Any]


def get_settings_sources(settings_type: type, config: RawConfigFile | None, cli: Namespace) -> "SettingsSourceList":
    """Build SettingsSourceList for `settings_type` from given config (if any) and parsed CLI namespace.

    `config` must be a tuple of config file path and a dictionary parsed from it, or None if
    no configuration file was found. The directory containing the config file will be used
    as base path for resolving relative paths in config and in defaults. If config file
    does not exist, paths in defaults are resolved relative to CWD. Paths from CLI are
    always resolved relative to CWD.
    """
    settings = [_source_from_cli(settings_type, cli)]  # cli has highest precedence
    if config is not None:
        config_source = _source_from_config(settings_type, config.path, config.raw_config)
        defaults_path_base = config_source.path_base
        settings.append(config_source)
    else:
        defaults_path_base = Path.cwd()
    settings.append(_defaults(settings_type, defaults_path_base))
    return SettingsSourceList(settings)


@dataclass
class SettingsSource:
    """Validated settings values from a single source. Contains a subset of settings."""

    path_base: Path
    values: dict[str, Any]


@dataclass
class SettingsSourceList:
    """Semantically similar to ChainMap of SettingsSource objects."""

    sources: Sequence[SettingsSource]

    def first(self, key: str) -> tuple[SettingsSource, Any]:
        for source in self.sources:
            try:
                return source, source.values[key]
            except KeyError:
                pass
        raise KeyError(f"{key!r} not found in any settings source")

    def first_value(self, key: str) -> Any:
        return self.first(key)[1]

    def path(self, key: str) -> Path:
        source, value = self.first(key)
        return Path(source.path_base, value)

    def list_of_paths(self, key: str) -> list[Path]:
        source, value = self.first(key)
        return [Path(source.path_base, v) for v in value]


def cli_dest(settings_type: type, name: str) -> str:
    return f"_{settings_type.__qualname__}_{name}"


def _defaults(settings_type: type, root: Path) -> SettingsSource:
    return SettingsSource(
        path_base=root,
        values={field.name: _get_field_default(field) for field in fields(settings_type)},
    )


def _get_field_default(field: Field[Any]) -> Any:
    # default_factory is not yet needed, so assume all fields have `default` defined
    if field.default is MISSING:
        raise ValueError(f"field {field.name} has no default value")
    return field.default


def _get_field_type(field: Field[Any]) -> type:
    origin = get_origin(field.type) or field.type
    if not isinstance(origin, type):
        raise ValueError(f"field {field.name} has unsupported type (stringized annotation?)")
    return origin


def _source_from_cli(settings_type: type, namespace: Namespace) -> SettingsSource:
    return SettingsSource(
        path_base=Path.cwd(),
        values={
            name: _validate_value("cli", name, setting, typ, value)
            for name, typ, setting in iter_settings(settings_type)
            if setting.cli and (value := getattr(namespace, cli_dest(settings_type, name), MISSING)) is not MISSING
        },
    )


def _source_from_config(settings_type: type, config_file: Path, config: dict[str, Any]) -> SettingsSource:
    return SettingsSource(
        path_base=config_file.parent,
        values={
            name: _validate_value(str(config_file), name, setting, typ, config[name])
            for name, typ, setting in iter_settings(settings_type)
            if setting.config and name in config
        },
    )


def _validate_value(source: str, name: str, setting: Setting, typ: type, value: Any) -> Any:
    if typ is Path:
        try:
            value = Path(value)
        except (ValueError, TypeError):
            raise ValueError(f"{_loc(source, name)}: expected a valid path")
    elif not isinstance(value, typ):
        raise ValueError(f"{_loc(source, name)}: expected {typ.__name__}")

    if setting.nargs == "+" and (not isinstance(value, Sequence) or not value):
        raise ValueError(f"{_loc(source, name)}: expected non-empty sequence")

    return value


def _loc(source: str, name: str) -> str:
    return f"invalid value of {name!r} setting in {source}"
