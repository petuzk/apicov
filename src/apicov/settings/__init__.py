from functools import partial

from .machinery import Setting, SettingsSourceList
from .machinery import get_settings_sources as _get_settings_sources
from .machinery import iter_cli_config as _iter_cli_config
from .machinery import iter_settings as _iter_settings
from .settings import ApicovSettings, find_config_file

get_settings_sources = partial(_get_settings_sources, ApicovSettings)
iter_cli_config = partial(_iter_cli_config, ApicovSettings)
iter_settings = partial(_iter_settings, ApicovSettings)

__all__ = [
    "ApicovSettings",
    "Setting",
    "SettingsSourceList",
    "find_config_file",
    "get_settings_sources",
    "iter_cli_config",
    "iter_settings",
]
