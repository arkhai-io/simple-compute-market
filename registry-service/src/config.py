import os
from typing import Literal
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from web3 import Web3


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Load local overrides, then the shared-env written by contracts-deploy at runtime
        env_file=[".env.local", ".env", "/app/shared-env/.env"],
        env_file_encoding="utf-8",
        case_sensitive=False,
    )
    
    database_url: str = "sqlite:///./indexer.db"
    
    # Blockchain Configuration - Base Sepolia
    chain_id: int = Field(default=1337, env="CHAIN_ID")
    rpc_url: str = "https://sepolia.base.org"
    
    # ERC-8004 Contract Addresses (Base Sepolia)
    identity_registry_address: str = "0x8004AA63c570c570eBF15376c0dB199918BFe9Fb"
    reputation_registry_address: str = "0x8004bd8daB57f14Ed299135749a5CB5c42d341BF"
    validation_registry_address: str = "0x8004C269D0A5647E51E121FeB226200ECE932d55"
    
    @field_validator(
        "identity_registry_address",
        "reputation_registry_address",
        "validation_registry_address",
        mode="before"
    )
    @classmethod
    def convert_to_checksum_address(cls, v: str) -> str:
        """Convert Ethereum address to checksum format (EIP-55)"""
        if v and isinstance(v, str) and v.startswith("0x") and len(v) == 42:
            try:
                return Web3.to_checksum_address(v)
            except (ValueError, AttributeError):
                # If web3 is not available or address is invalid, return as-is
                return v
        return v
    
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
    
    # Health Check Configuration
    enable_health_checks: bool = False  # Opt-in: Registry-initiated health checks (disabled by default)
    health_check_interval: int = 60
    endpoint_check_timeout: int = 10
    heartbeat_ttl_secs: int = 60
    
    # API key authentication (opt-in; off by default for back-compat).
    # When ``require_api_key=True`` every non-admin / non-health route
    # rejects requests without ``Authorization: Bearer <key>`` matching
    # an active row in the api_keys table. Operators mint and revoke
    # keys via ``POST /admin/api-keys`` etc., gated by the
    # ``admin_api_key`` env var (separate from the api_keys table).
    require_api_key: bool = Field(
        default=False, validation_alias="REGISTRY_REQUIRE_API_KEY",
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

