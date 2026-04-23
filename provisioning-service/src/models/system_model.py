"""Request and response models for the system diagnostics controller.

File naming: ``_model`` suffix marks this as a model definition file.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = Field(description="'ok' when all checks pass, 'degraded' otherwise")
    checks: dict[str, str] = Field(description="Per-subsystem status strings")


class VersionResponse(BaseModel):
    version: str = Field(description="Service version string")
    active_profiles: list[str] = Field(
        description="Dynaconf profiles currently active (from ACTIVE_PROFILES env var)"
    )


class FileInfo(BaseModel):
    path: str = Field(description="Absolute (expanded) filesystem path")
    exists: bool
    sha256: Optional[str] = Field(
        default=None,
        description="SHA-256 hex digest of the file contents (None if file absent)",
    )


class InventoryInfo(FileInfo):
    host_count: Optional[int] = Field(
        default=None,
        description="Number of hosts parsed from the inventory (None if unreadable)",
    )


class SshKeyInfo(FileInfo):
    raw_path: str = Field(
        description="Path as written in the inventory (may contain ~)",
    )
    referenced_by: list[str] = Field(
        description="Host aliases that reference this key path",
    )


class AnsibleReadinessResponse(BaseModel):
    ansible_version: Optional[str] = Field(
        default=None,
        description="ansible --version first line (None if ansible not on PATH)",
    )
    inventory: InventoryInfo
    playbook: FileInfo
    ssh_keys: list[SshKeyInfo] = Field(
        description=(
            "Unique SSH key paths referenced by inventory hosts, "
            "with existence and integrity information."
        )
    )
