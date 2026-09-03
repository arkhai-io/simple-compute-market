"""
Centralised dynaconf configuration loader.

Resolution order (highest priority wins):
  1. CLI args injected via conftest into environment variables before this module loads
  2. ARKHAI_* environment variables. Dynaconf loads missing values from the project
     .env into this same environment layer; already-exported values are not overwritten
  3. config-<profile>.yml files (in CONFIG_DIRECTORY, one per ACTIVE_PROFILES entry)
  4. config.yml  (in CONFIG_DIRECTORY)
  5. .secrets.toml
  6. settings.toml  (project defaults / schema documentation)

Merge behaviour:
  Values are unioned using deep-merge behavior.
  This is good for combining values with secrets but inconvenient if you wish
  to delete previous configuration values
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import List

from dynaconf import Validator
from market_config import (
    DynaconfBootstrapOptions,
    DynaconfBootstrapResult,
    load_dynaconf,
)

# E2E owns environment lookup, secrets, and pass-through include policy; the
# shared kit owns deterministic profile/include resolution and construction.
_PROJECT_ROOT = Path(__file__).parent.parent
_BOOTSTRAP_OPTIONS = DynaconfBootstrapOptions(
    default_config_directory=_PROJECT_ROOT / "config",
    settings_files=(
        _PROJECT_ROOT / "settings.toml",
        _PROJECT_ROOT / ".secrets.toml",
    ),
    envvar_prefix="ARKHAI",
    nested_separator_keyword="nested_sep",
    dotenv_path=_PROJECT_ROOT / ".env",
)


def _load_bootstrap(environ: Mapping[str, str]) -> DynaconfBootstrapResult:
    """Build settings from resolver variables owned by this composition root."""

    return load_dynaconf(
        _BOOTSTRAP_OPTIONS,
        config_directory=environ.get("CONFIG_DIRECTORY"),
        active_profiles=environ.get("ACTIVE_PROFILES", ""),
    )


_bootstrap = _load_bootstrap(os.environ)
_CONFIG_DIR = _bootstrap.config_directory
_active_profiles: List[str] = list(_bootstrap.active_profiles)
_includes: List[str] = [str(path) for path in _bootstrap.includes]
settings = _bootstrap.settings


def validate_all() -> None:
    """Run all validators and raise on the first failure."""
    settings.validators.validate_all()


def active_profiles() -> List[str]:
    return list(_active_profiles)


def config_directory() -> Path:
    return _CONFIG_DIR