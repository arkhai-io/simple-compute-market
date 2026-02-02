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
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    host: str = "0.0.0.0"
    port: int = 8081
    log_level: str = "info"

    database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/provisioning"
    redis_url: str = "redis://localhost:6379/0"
    redis_queue_name: str = "provisioning_jobs"

    ansible_timeout_seconds: int = 1800
    default_vm_host: str = "vm1"

    playbook_path: str | None = None
    inventory_path: str | None = None

    # Authentication settings
    enable_auth: bool = False  # Set to True to enable agent authentication
    registry_url: str | None = None  # URL of agent registry API for verification

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


settings = Settings()
