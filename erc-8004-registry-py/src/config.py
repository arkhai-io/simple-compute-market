import os
from pydantic_settings import BaseSettings
from typing import Literal


class Settings(BaseSettings):
    # Database
    database_url: str = "sqlite:///./registry.db"
    
    # Blockchain Configuration - Base Sepolia
    chain_id: int = 84532
    rpc_url: str = "https://sepolia.base.org"
    
    # ERC-8004 Contract Addresses (Base Sepolia)
    identity_registry_address: str = "0x8004AA63c570c570eBF15376c0dB199918BFe9Fb"
    reputation_registry_address: str = "0x8004bd8daB57f14Ed299135749a5CB5c42d341BF"
    validation_registry_address: str = "0x8004C269D0A5647E51E121FeB226200ECE932d55"
    
    # Server Configuration
    port: int = 8080
    host: str = "0.0.0.0"
    
    # Health Check Configuration
    enable_health_checks: bool = False  # Opt-in: Registry-initiated health checks (disabled by default)
    health_check_interval: int = 60
    endpoint_check_timeout: int = 10
    heartbeat_ttl_secs: int = 60
    
    # Logging
    log_level: str = "info"
    
    class Config:
        env_file = ".env"
        case_sensitive = False

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql://")
    
    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite://")


settings = Settings()

