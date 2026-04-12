from argparse import Namespace
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from apicov.settings.machinery import SettingsSourceList, cli_dest, get_settings_sources

DUMMY_CONFIG_PATH = Path("/tmp/dummy.toml")


@dataclass
class DummySettings:
    x: int = field(default=0)
    p: Path = field(default=Path())


def settings_sources(
    settings_type: type, config: dict[str, Any] | None, cli: dict[str, Any] | None
) -> SettingsSourceList:
    return get_settings_sources(
        settings_type,
        (DUMMY_CONFIG_PATH, config) if config else None,
        Namespace(**{cli_dest(settings_type, name): value for name, value in (cli or {}).items()}),
    )


@pytest.mark.parametrize(
    "config, cli, expected",
    [
        pytest.param(None, None, 0, id="default"),
        pytest.param({"x": 42}, None, 42, id="config"),
        pytest.param(None, {"x": 123}, 123, id="cli"),
        pytest.param({"x": 42}, {"x": 123}, 123, id="cli-override"),
    ],
)
def test_precedence(config, cli, expected):
    assert settings_sources(DummySettings, config, cli).first_value("x") == expected


@pytest.mark.parametrize(
    "config, cli, expected",
    [
        pytest.param(None, None, Path.cwd(), id="default"),
        pytest.param({"p": "cfg"}, None, DUMMY_CONFIG_PATH.parent / "cfg", id="config"),
        pytest.param(None, {"p": "cli"}, Path.cwd() / "cli", id="cli"),
        pytest.param({"p": "cfg"}, {"p": "cli"}, Path.cwd() / "cli", id="cli-override"),
    ],
)
def test_path_resolution(config, cli, expected):
    assert settings_sources(DummySettings, config, cli).path("p") == expected


@pytest.mark.parametrize(
    "config, cli, where",
    [
        pytest.param({"x": "42"}, None, DUMMY_CONFIG_PATH, id="config"),
        pytest.param(None, {"x": "123"}, "cli", id="cli"),
        # even though the valid CLI value should be effective, still report the invalid one from config
        pytest.param({"x": "42"}, {"x": 123}, DUMMY_CONFIG_PATH, id="cli-override"),
    ],
)
def test_validation(config, cli, where):
    with pytest.raises(ValueError, match=f"invalid value of 'x' setting in {where}"):
        settings_sources(DummySettings, config, cli)


def test_requires_default():
    @dataclass
    class NoDefault:
        x: int

    with pytest.raises(ValueError, match="field x has no default value"):
        settings_sources(NoDefault, None, None)
