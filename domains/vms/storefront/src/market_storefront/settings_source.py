"""The VM storefront's layered settings, as Dynaconf merges them, read when asked.

The packaged ``settings.toml`` first, then each storefront configuration file
present (``market_config.config_loader.storefront_config_files``), then the
``STOREFRONT_`` environment. Loading validates nothing and opens no file a
setting names, so the migration command, which needs only the database path
and the log level, reads them here without the storefront's chains, identity,
or base URL being resolved; ``market_storefront.utils.config`` resolves those
for the application.
"""

from __future__ import annotations

from pathlib import Path

from dynaconf import Dynaconf
from market_config.config_loader import storefront_config_files

DEFAULTS_FILE = Path(__file__).resolve().parent / "settings.toml"


def settings_source() -> Dynaconf:
    """The layered settings, read from disk now."""
    overlays = [str(p) for p in storefront_config_files() if Path(p).exists()]
    return Dynaconf(
        settings_file=[str(DEFAULTS_FILE)],
        includes=overlays,
        envvar_prefix="STOREFRONT",
        envvar_separator="__",
        load_dotenv=False,
        environments=False,
        merge_enabled=True,
    )
