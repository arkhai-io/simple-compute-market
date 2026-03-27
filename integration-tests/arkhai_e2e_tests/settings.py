"""
arkhai_e2e_tests/settings.py
----------------------------
Centralised dynaconf configuration loader.

Resolution order (highest priority wins):
  1. CLI args injected via conftest into env vars before this module loads
  2. ARKHAI_* environment variables
  3. config-<profile>.yml files (in CONFIG_DIRECTORY, one per ACTIVE_PROFILES entry)
  4. config.yml  (in CONFIG_DIRECTORY)
  5. .env / .env.<ENV_FOR_DYNACONF> files
  6. .secrets.toml
  7. settings.toml  (project defaults / schema documentation)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List

from dynaconf import Dynaconf, Validator

# ---------------------------------------------------------------------------
# Resolve config directory and active profiles
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).parent.parent
_CONFIG_DIR = Path(os.environ.get("CONFIG_DIRECTORY", _PROJECT_ROOT / "config"))

_raw_profiles: str = os.environ.get("ACTIVE_PROFILES", "")
_active_profiles: List[str] = [p.strip() for p in _raw_profiles.split(",") if p.strip()]

# Build the ordered list of YAML includes that dynaconf will merge in order.
# config.yml is always loaded first; profile files layer on top.
_includes: List[str] = [str(_CONFIG_DIR / "config.yml")]
for _profile in _active_profiles:
    _profile_path = _CONFIG_DIR / f"config-{_profile}.yml"
    _includes.append(str(_profile_path))

# ---------------------------------------------------------------------------
# Dynaconf instance
# ---------------------------------------------------------------------------
settings = Dynaconf(
    # Base TOML defaults live next to this file's package root
    settings_file=[
        str(_PROJECT_ROOT / "settings.toml"),
        str(_PROJECT_ROOT / ".secrets.toml"),
    ],
    # Additional YAML layers (config dir + profiles)
    includes=_includes,
    # .env file support
    load_dotenv=True,
    dotenv_path=str(_PROJECT_ROOT / ".env"),
    # All ARKHAI_* env vars override everything
    envvar_prefix="ARKHAI",
    environments=False,  # we use profiles, not dynaconf environments
    # Allow nested keys via __ separator in env vars (ARKHAI_RPC__URL)
    nested_sep="__",
)

def validate_all() -> None:
    """Run all validators and raise on the first failure."""
    settings.validators.validate_all()

def active_profiles() -> List[str]:
    return list(_active_profiles)

def config_directory() -> Path:
    return _CONFIG_DIR