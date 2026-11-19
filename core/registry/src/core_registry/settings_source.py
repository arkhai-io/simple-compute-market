"""Where the registry's settings come from, and the two its migration reads.

The registry reads its settings from dotenv files: the default files every
registry reads first, then the profile files the resolver variables select.
:mod:`core_registry.config` builds the application's settings over these files;
the migration command and the Alembic environment read only the database's
location and the log level from the same files, through
:func:`load_database_settings`, so a migration runs with no credential file
mounted and is unaffected by any other setting a profile states
(openspec/specs/deployment-state/spec.md#requirement-service-owned-migration-history).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# The dotenv files every registry reads first. A later file overrides an earlier
# one on a key both state, and the process environment overrides every file, so
# `.env.local` is the lowest-priority file, not an override.
DEFAULT_ENV_FILES: tuple[str, ...] = (".env.local", ".env", "/app/shared-env/.env")

DEFAULT_DATABASE_URL = "sqlite:///./indexer.db"


def profile_env_files(environment: Mapping[str, str]) -> tuple[Path, ...]:
    """The profile env files the resolver variables select, in layering order.

    ``ACTIVE_PROFILES`` is a comma-separated list of profile names, each loaded
    as ``config-<profile>.env`` from ``CONFIG_DIRECTORY`` (the working directory
    when unset), a later profile overriding an earlier one. Neither variable is a
    setting: they choose which files configure the registry.
    """
    directory = Path(environment.get("CONFIG_DIRECTORY") or ".")
    profiles = (
        profile.strip()
        for profile in environment.get("ACTIVE_PROFILES", "").split(",")
        if profile.strip()
    )
    return tuple(directory / f"config-{profile}.env" for profile in profiles)


def settings_env_files(
    environment: Mapping[str, str] | None = None,
) -> tuple[str | Path, ...]:
    """Every file the registry's settings layer, lowest priority first.

    The profile files follow the default dotenv files in one list, so a profile
    overrides every default file and a later profile an earlier one; a listed
    file that does not exist is skipped. ``environment`` supplies only the
    resolver variables, the process environment by default.
    """
    source = os.environ if environment is None else environment
    return (*DEFAULT_ENV_FILES, *profile_env_files(source))


class DatabaseSettings(BaseSettings):
    """The database's location and the log level, and nothing else.

    Every other key the files or the environment state is ignored unread, so a
    malformed operational setting cannot stop a migration.
    """

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    database_url: str = DEFAULT_DATABASE_URL
    log_level: str = "info"


def load_database_settings(
    environment: Mapping[str, str] | None = None,
) -> DatabaseSettings:
    """Read the database's location and the log level from the registry's files."""

    return DatabaseSettings(_env_file=settings_env_files(environment))
