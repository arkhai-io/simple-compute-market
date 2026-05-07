"""
Centralised dynaconf configuration loader.

Resolution order (highest priority wins):
  1. PROVISIONING_* environment variables
  2. config-<profile>.yml files (in CONFIG_DIRECTORY, one per ACTIVE_PROFILES entry)
  3. config.yml  (in CONFIG_DIRECTORY)
  4. settings.toml  (committed defaults / schema documentation)

Profile selection:
  Set CONFIG_DIRECTORY to the directory containing config YAML files.
  Set ACTIVE_PROFILES to a comma-separated list of profile names, e.g.:
    ACTIVE_PROFILES=local          → loads config/config-local.yml
    ACTIVE_PROFILES=production     → loads config/config-production.yml

  In Kubernetes the ConfigMap mounts config-production.yml into CONFIG_DIRECTORY
  and the Deployment sets ACTIVE_PROFILES=production.
  Locally, copy config/config-local.yml.example to config/config-local.yml
  and set ACTIVE_PROFILES=local (or add it to .env).

All includes are optional — missing files are silently skipped.  This means
a fresh checkout with no config-local.yml and no ACTIVE_PROFILES set will
load only settings.toml, which provides safe defaults for local development.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List

from dynaconf import Dynaconf

# ---------------------------------------------------------------------------
# Resolve config directory and active profiles
# ---------------------------------------------------------------------------
_SRC_DIR = Path(__file__).parent
_CONFIG_DIR = Path(os.environ.get("CONFIG_DIRECTORY", str(_SRC_DIR / "config")))

_raw_profiles: str = os.environ.get("ACTIVE_PROFILES", "")
_active_profiles: List[str] = [p.strip() for p in _raw_profiles.split(",") if p.strip()]

# Only include files that exist on disk — missing files are silently skipped
# rather than raising. This makes every include optional, so a fresh checkout
# with no profile files works out of the box.
_includes: List[str] = []
for _candidate in [_CONFIG_DIR / "config.yml"] + [
    _CONFIG_DIR / f"config-{p}.yml" for p in _active_profiles
]:
    if _candidate.exists():
        _includes.append(str(_candidate))

# ---------------------------------------------------------------------------
# Dynaconf instance
# ---------------------------------------------------------------------------
_dynaconf = Dynaconf(
    settings_file=[str(_SRC_DIR / "settings.toml")],
    includes=_includes,
    envvar_prefix="PROVISIONING",
    load_dotenv=True,
    dotenv_files=[".env", ".env.local"],
    envvar_separator="__",
    environments=False,   # profiles are used instead of dynaconf environments
    merge_enabled=True,
)


class Settings:
    """Thin wrapper around dynaconf that adds typed path properties.

    Simple scalar values are delegated to dynaconf via ``__getattr__``.
    Path properties that require ``Path`` coercion live here as
    ``@property`` accessors.

    All filesystem paths must be supplied explicitly — there is no runtime
    path discovery. Set them via ACTIVE_PROFILES config files or
    PROVISIONING_* env vars.
    """

    def __init__(self, source: Dynaconf) -> None:
        self._source = source

    def __getattr__(self, name: str):  # type: ignore[override]
        return getattr(self._source, name)

    @property
    def is_sqlite(self) -> bool:
        return str(self._source.database_url).startswith("sqlite")

    @property
    def resolved_playbook_path(self) -> Path:
        return Path(str(self._source.playbook_path)).resolve()

    @property
    def resolved_inventory_path(self) -> Path:
        return Path(str(self._source.inventory_path)).resolve()

    @property
    def management_vars_path(self) -> Path:
        return Path(str(self._source.management_vars_path)).resolve()


settings = Settings(_dynaconf)