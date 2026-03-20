import os
from typing import Literal
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from web3 import Web3


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Check both .env.local and .env files
        env_file=[".env.local", ".env"],
        case_sensitive=False,
    )
    
    database_url: str = "sqlite:///./indexer.db"
    
    # Blockchain Configuration - local Anvil by default; deployed canaries must override RPC_URL
    chain_id: int = Field(default=1337, env="CHAIN_ID")
    rpc_url: str = "http://localhost:8545"
    
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

    # Optional ZeroTier configuration (used by deployment/Makefile, not by app logic)
    zerotier_network: str | None = Field(default=None, env="ZEROTIER_NETWORK")

    # Event sync configuration
    event_sync_initial_lookback_blocks: int = 1000
    event_sync_chunk_size: int = 500
    
    # Health Check Configuration
    enable_health_checks: bool = False  # Opt-in: Registry-initiated health checks (disabled by default)
    health_check_interval: int = 60
    endpoint_check_timeout: int = 10
    heartbeat_ttl_secs: int = 60
    
    # Logging
    log_level: str = "info"

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql://")
    
    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite://")


settings = Settings()
