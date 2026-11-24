"""The service's layered settings, as dynaconf resolves them, before any secret is read.

Resolution order (highest priority wins):
  1. APICREDITS_* environment variables
  2. config-<profile>.yml files (in CONFIG_DIRECTORY, one per ACTIVE_PROFILES entry)
  3. config.yml  (in CONFIG_DIRECTORY)
  4. settings.toml  (committed defaults / schema documentation)

Profile selection works exactly like the VM provisioning service: set
CONFIG_DIRECTORY to the directory containing config YAML files and
ACTIVE_PROFILES to a comma-separated list of profile names. All
includes are optional — a fresh checkout with neither set loads only
settings.toml.

Loading reads no file a setting names, so the migration command, which needs
only the database location and the log level, can load it without the
application's secrets mounted; ``apicredits_service.config`` resolves those
for the application.
"""

from __future__ import annotations

import os
from pathlib import Path

from dynaconf import Dynaconf

_SRC_DIR = Path(__file__).parent


def load_settings_source() -> Dynaconf:
    """The settings the environment and configuration files give, read now."""
    config_dir = Path(os.environ.get("CONFIG_DIRECTORY", str(_SRC_DIR / "config")))
    profiles = [
        p.strip() for p in os.environ.get("ACTIVE_PROFILES", "").split(",") if p.strip()
    ]
    # Only include files that exist on disk — every include is optional.
    includes = [
        str(candidate)
        for candidate in [config_dir / "config.yml"]
        + [config_dir / f"config-{p}.yml" for p in profiles]
        if candidate.exists()
    ]
    return Dynaconf(
        settings_file=[str(_SRC_DIR / "settings.toml")],
        includes=includes,
        envvar_prefix="APICREDITS",
        load_dotenv=True,
        dotenv_files=[".env", ".env.local"],
        envvar_separator="__",
        environments=False,   # profiles are used instead of dynaconf environments
        merge_enabled=True,
    )
