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
Marketplace public principals are ordinary ``identity`` and
``storefront_identity`` configuration. The matching service credential is
read only from ``ARKHAI_IDENTITY_CREDENTIAL`` at composition and is never
loaded into Dynaconf.
"""

from __future__ import annotations

import os
from pathlib import Path

from dynaconf import Dynaconf
from market_config import DynaconfBootstrapOptions, load_dynaconf

BARE_METAL_RECLAIM_POLICIES = frozenset({
    "remove_lease_key",
    "lock_user",
    "delete_user",
})
DEFAULT_BARE_METAL_RECLAIM_POLICY = "remove_lease_key"

# The service owns environment lookup and optional-include policy; the shared kit
# owns deterministic profile/include resolution and Dynaconf construction.
_SRC_DIR = Path(__file__).parent
_BOOTSTRAP_OPTIONS = DynaconfBootstrapOptions(
    default_config_directory=_SRC_DIR / "config",
    settings_files=(_SRC_DIR / "settings.toml",),
    envvar_prefix="PROVISIONING",
    nested_separator_keyword="envvar_separator",
    dotenv_files=(".env", ".env.local"),
    filter_missing_includes=True,
)
_bootstrap = load_dynaconf(
    _BOOTSTRAP_OPTIONS,
    config_directory=os.environ.get("CONFIG_DIRECTORY"),
    active_profiles=os.environ.get("ACTIVE_PROFILES", ""),
)
_CONFIG_DIR = _bootstrap.config_directory
_active_profiles = list(_bootstrap.active_profiles)
_includes = [str(path) for path in _bootstrap.includes]
_dynaconf = _bootstrap.settings


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
    def resolved_bare_metal_playbook_path(self) -> Path:
        return Path(str(self._source.bare_metal_playbook_path)).resolve()

    @property
    def bare_metal_reclaim_policy(self) -> str:
        policy = str(
            getattr(
                self._source,
                "bare_metal_reclaim_policy",
                DEFAULT_BARE_METAL_RECLAIM_POLICY,
            )
            or DEFAULT_BARE_METAL_RECLAIM_POLICY
        ).strip()
        if policy not in BARE_METAL_RECLAIM_POLICIES:
            allowed = ", ".join(sorted(BARE_METAL_RECLAIM_POLICIES))
            raise ValueError(
                "Invalid bare_metal_reclaim_policy "
                f"{policy!r}; expected one of: {allowed}"
            )
        return policy

    @property
    def resolved_inventory_path(self) -> Path:
        return Path(str(self._source.inventory_path)).resolve()

    @property
    def resolved_pool_definitions_path(self) -> Path | None:
        raw = str(getattr(self._source, "pool_definitions_path", "") or "").strip()
        return Path(raw).resolve() if raw else None

    @property
    def resolved_relay_definitions_path(self) -> Path | None:
        raw = str(getattr(self._source, "relay_definitions_path", "") or "").strip()
        return Path(raw).resolve() if raw else None

    @property
    def management_vars_path(self) -> Path:
        return Path(str(self._source.management_vars_path)).resolve()


settings = Settings(_dynaconf)
