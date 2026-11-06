import os
from collections.abc import Mapping
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# The dotenv files every registry reads first. A later file overrides an earlier
# one on a key both state, and the process environment overrides every file, so
# `.env.local` is the lowest-priority file, not an override.
DEFAULT_ENV_FILES: tuple[str, ...] = (".env.local", ".env", "/app/shared-env/.env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=DEFAULT_ENV_FILES,
        env_file_encoding="utf-8",
        case_sensitive=False,
        # Tolerate unknown env vars (e.g. stale cross-service entries in
        # shared-env/.env) so the registry boots cleanly.
        extra="ignore",
    )

    database_url: str = "sqlite:///./indexer.db"

    # Server Configuration
    port: int = 8080
    host: str = "0.0.0.0"
    # root_path: set to the gateway path prefix for this service (e.g. "/registry").
    # Used by FastAPI to generate correct OpenAPI schema URLs when behind a
    # reverse proxy that strips the prefix. A deployment states it as ROOT_PATH
    # in a profile env file; the registry chart renders it from config.rootPath.
    root_path: str = ""

    registry_authority_id: str | None = Field(
        default=None,
        validation_alias="REGISTRY_AUTHORITY_ID",
    )
    registry_authority_scheme: str | None = Field(
        default=None,
        validation_alias="REGISTRY_AUTHORITY_SCHEME",
    )
    registry_authority_identifier: str | None = Field(
        default=None,
        validation_alias="REGISTRY_AUTHORITY_IDENTIFIER",
    )
    registry_authority_credential_file: str | None = Field(
        default=None,
        validation_alias="REGISTRY_AUTHORITY_CREDENTIAL_FILE",
    )
    registry_descriptor_base_url: str | None = Field(
        default=None,
        validation_alias="REGISTRY_DESCRIPTOR_BASE_URL",
    )
    registry_descriptor_display_name: str | None = Field(
        default=None,
        validation_alias="REGISTRY_DESCRIPTOR_DISPLAY_NAME",
    )
    registry_descriptor_operator_identity: str | None = Field(
        default=None,
        validation_alias="REGISTRY_DESCRIPTOR_OPERATOR_IDENTITY",
    )
    registry_descriptor_access_acquisition_pointer: str | None = Field(
        default=None,
        validation_alias="REGISTRY_DESCRIPTOR_ACCESS_ACQUISITION_POINTER",
    )

    registry_descriptor_recommended_dispute_authorities: list[dict] = Field(
        default_factory=list,
        validation_alias="REGISTRY_DESCRIPTOR_RECOMMENDED_DISPUTE_AUTHORITIES",
    )

    # The filter specification this registry serves; unset, the packaged
    # filter-spec.yaml.
    registry_filter_spec_path: str | None = Field(
        default=None,
        validation_alias="REGISTRY_FILTER_SPEC_PATH",
    )

    # Optional ZeroTier configuration (used by deployment/Makefile, not by app logic)
    zerotier_network: str | None = Field(default=None, env="ZEROTIER_NETWORK")

    # API key authentication, gated independently for read and write
    # access (both opt-in; off by default). Read routes (discovery,
    # lookups, system diagnostics) require any active key when
    # ``require_read_api_key`` is set; write routes (publish / update /
    # delete listings, heartbeat) require a *write*-scoped key when
    # ``require_write_api_key`` is set. The two toggles compose:
    #   both off  → fully public registry
    #   write on  → open discovery, gated publishing (vetted sellers)
    #   both on   → private registry (buyers hold read keys, sellers write)
    # Keys carry a scope; a write key implies read. Operators mint and
    # revoke keys via ``POST /admin/api-keys`` etc., gated by the
    # ``admin_api_key`` env var (separate from the api_keys table).
    require_read_api_key: bool = Field(
        default=False,
        validation_alias="REGISTRY_REQUIRE_READ_API_KEY",
    )
    require_write_api_key: bool = Field(
        default=False,
        validation_alias="REGISTRY_REQUIRE_WRITE_API_KEY",
    )
    admin_api_key: str | None = Field(
        default=None,
        validation_alias="REGISTRY_ADMIN_API_KEY",
    )
    # Optional bootstrap secret. When set AND the api_keys table is
    # empty at startup, the registry seeds a single row with this raw
    # value (hashed). Lets a private registry come up with one
    # operator-known key without an admin orchestration step. After
    # the first run, the env var can stay set or be removed — the
    # row persists across restarts.
    bootstrap_api_key: str | None = Field(
        default=None,
        validation_alias="REGISTRY_BOOTSTRAP_API_KEY",
    )

    # Logging
    log_level: str = "info"

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql://")

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite://")


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


def load_settings(environment: Mapping[str, str] | None = None) -> Settings:
    """Build the registry's settings from its dotenv files and selected profiles.

    The profile files follow the default dotenv files in one list, so a profile
    overrides every default file, a later profile an earlier one, and the
    process environment every file; a listed file that does not exist is
    skipped, as a missing default file is. ``environment`` supplies only the
    resolver variables, the process environment by default.
    """
    source = os.environ if environment is None else environment
    return Settings(_env_file=(*DEFAULT_ENV_FILES, *profile_env_files(source)))


settings = load_settings()
