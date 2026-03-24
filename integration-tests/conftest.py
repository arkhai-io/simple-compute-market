"""
conftest.py (project root)
--------------------------
Root-level pytest plugin.  Registers custom CLI options that let you pass
config overrides directly through pytest

    pytest --profile staging --config-dir /mnt/config -m contracts

These options set the corresponding environment variables *before* the
arkhai_e2e_tests.settings module is imported, so dynaconf picks them up
through its normal resolution chain.
"""

from __future__ import annotations

import os

def pytest_addoption(parser) -> None:
    group = parser.getgroup("arkhai", "Arkhai E2E config overrides")

    group.addoption(
        "--profile",
        metavar="NAME",
        default=None,
        help="Active profile(s), comma-separated (sets ACTIVE_PROFILES). "
             "Example: --profile staging",
    )
    group.addoption(
        "--config-dir",
        metavar="PATH",
        default=None,
        help="Path to config directory (sets CONFIG_DIRECTORY). "
             "Example: --config-dir /mnt/e2e-config",
    )

def pytest_configure(config) -> None:
    """
    Inject CLI option values as env vars early in the pytest lifecycle,
    before any test module (or conftest) imports arkhai_e2e_tests.settings.
    """
    _setenv("ACTIVE_PROFILES",             config.getoption("--profile",       default=None))
    _setenv("CONFIG_DIRECTORY",            config.getoption("--config-dir",    default=None))

def _setenv(key: str, value: str | None) -> None:
    if value is not None:
        os.environ[key] = value

def _opt_str(config, name: str) -> str | None:
    val = config.getoption(name, default=None)
    return str(val) if val is not None else None
