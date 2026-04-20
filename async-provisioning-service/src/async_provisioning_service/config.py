import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_project_root() -> Path:
    override = os.getenv("PROVISIONING_REPO_ROOT")
    if override:
        return Path(override).expanduser().resolve()

    current = Path(__file__).resolve()
    for parent in [current] + list(current.parents):
        if (parent / "compute-provisioning-iac").exists():
            return parent
        if (parent / ".git").exists():
            return parent
    return current.parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=[".env", ".env.local"], extra="ignore")

    host: str = "0.0.0.0"
    port: int = 8081
    worker_health_port: int = 8082  # Health endpoint for the worker process
    log_level: str = "info"

    database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/provisioning"
    redis_url: str = "redis://localhost:6379/0"
    redis_queue_name: str = "provisioning_jobs"

    ansible_timeout_seconds: int = 1800
    default_vm_host: str = "ww1"

    playbook_path: str | None = None
    inventory_path: str | None = None

    # Worker concurrency settings
    max_concurrent_jobs: int = 5  # Max jobs running simultaneously per worker

    # Retry configuration
    default_max_retries: int = 3  # Default retry attempts for failed jobs
    retry_backoff_initial_seconds: int = 60  # Initial retry delay (1 minute)
    retry_backoff_multiplier: float = 2.0  # Exponential backoff multiplier
    retry_backoff_max_seconds: int = 3600  # Max retry delay (1 hour)

    # Errors that should NOT be retried (circuit breaker)
    non_retryable_errors: list[str] = [
        "Invalid SSH key",
        "VM target not found",
        "Permission denied",
        "Authentication failed",
        "Host unreachable",
        "Operation timed out",  # SSH connection timeout
        "Connection refused",    # SSH connection refused
        "UNREACHABLE",          # Ansible unreachable status
        "Failed to get \"resize\" lock",  # Disk image already in use
        "Is another process using the image",  # Disk image lock conflict
        "Cannot determine IP address for VM",  # VM already undefined/cleaned up
        "failed to get domain",  # libvirt domain not found
        "Domain not found",  # virsh domain doesn't exist
    ]

    # FRP tunneling defaults (applied when request doesn't specify FRP params)
    frp_server_addr: str | None = None
    frp_domain: str | None = None
    frp_dashboard_password: str | None = None

    # Authentication settings
    enable_auth: bool = False  # Set to True to enable agent authentication
    registry_url: str | None = None  # URL of agent registry API for verification
    registry_cache_ttl_seconds: int = 300  # TTL for registry lookup cache (5 min)
    registry_cache_max_size: int = 256  # Max entries in registry cache

    # Rate limiting
    enable_rate_limiting: bool = False
    rate_limit_requests_per_minute: int = 30

    @property
    def repo_root(self) -> Path:
        return _find_project_root()

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def resolved_playbook_path(self) -> Path:
        if self.playbook_path:
            return Path(self.playbook_path).expanduser().resolve()
        return (
            self.repo_root
            / "compute-provisioning-iac/ansible/playbooks/single-tenant/vm-operations.yaml"
        ).resolve()

    @property
    def resolved_inventory_path(self) -> Path:
        if self.inventory_path:
            return Path(self.inventory_path).expanduser().resolve()
        return (self.repo_root / "compute-provisioning-iac/ansible/inventory/hosts").resolve()

    @property
    def management_vars_path(self) -> Path:
        return (
            self.repo_root
            / "compute-provisioning-iac/ansible/inventory/management-vars.yaml"
        ).resolve()


settings = Settings()
