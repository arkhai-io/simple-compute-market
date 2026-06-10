import os
from typing import Literal
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Load local overrides, then the committed shared-env/.env (cross-service addresses)
        env_file=[".env.local", ".env", "/app/shared-env/.env"],
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
    # reverse proxy that strips the prefix. Set via ROOT_PATH env var in the
    # Helm values overlay in the ops repo.
    root_path: str = ""

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
        default=False, validation_alias="REGISTRY_REQUIRE_READ_API_KEY",
    )
    require_write_api_key: bool = Field(
        default=False, validation_alias="REGISTRY_REQUIRE_WRITE_API_KEY",
    )
    admin_api_key: str | None = Field(
        default=None, validation_alias="REGISTRY_ADMIN_API_KEY",
    )
    # Optional bootstrap secret. When set AND the api_keys table is
    # empty at startup, the registry seeds a single row with this raw
    # value (hashed). Lets a private registry come up with one
    # operator-known key without an admin orchestration step. After
    # the first run, the env var can stay set or be removed — the
    # row persists across restarts.
    bootstrap_api_key: str | None = Field(
        default=None, validation_alias="REGISTRY_BOOTSTRAP_API_KEY",
    )

    # Logging
    log_level: str = "info"

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql://")
    
    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite://")


settings = Settings()

