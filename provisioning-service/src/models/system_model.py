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


class InventoryInfo(BaseModel):
    """Host inventory diagnostics.

    ``source`` is ``'database'`` when inventory is read from the ``hosts``
    table (normal operation) or ``'file'`` for a legacy INI path.
    ``host_count`` is the number of enabled hosts found.
    ``path`` is the DB URL or file path, for informational purposes.
    """

    source: str = Field(description="'database' or 'file'")
    path: str = Field(description="DB URL or inventory file path")
    exists: bool = Field(description="True if the source is reachable")
    host_count: Optional[int] = Field(
        default=None,
        description="Number of enabled hosts (None if source is unreadable)",
    )


class SshKeyInfo(BaseModel):
    key_type: str = Field(description="'path' or 'embedded'")
    raw_path: str = Field(
        description=(
            "For 'path': the configured key path. "
            "For 'embedded': '<encrypted>' sentinel."
        ),
    )
    path: str = Field(description="Expanded path (path-type) or '<encrypted>'")
    exists: bool = Field(
        description=(
            "For 'path': whether the key file exists on disk. "
            "For 'embedded': always True (key is stored in DB)."
        )
    )
    sha256: Optional[str] = Field(
        default=None,
        description=(
            "SHA-256 of the key file (path-type only; None for embedded or absent files)."
        ),
    )
    referenced_by: list[str] = Field(
        description="Host aliases that use this key configuration.",
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
            "SSH key diagnostics per unique key reference across all enabled hosts."
        )
    )
