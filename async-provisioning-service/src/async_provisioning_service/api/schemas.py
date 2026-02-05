from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class ProvisionRequest(BaseModel):
    ssh_pubkey: str = Field(..., description="SSH public key to authorize on the VM")
    vm_host: str = Field(default="vm1", description="Inventory host name")
    vm_target: str = Field(default="tenant-vm")
    vm_action: str = Field(default="create")
    vm_ram: int = Field(default=2048, ge=512)
    vm_vcpus: int = Field(default=2, ge=1)
    vm_disk_size: str = Field(default="25G")
    vm_lease_end: Optional[str] = Field(default=None, description="Lease end time for VM shutdown (format: 'YYYY-MM-DD HH:MM')")
    max_retries: Optional[int] = Field(default=None, description="Max retry attempts (overrides default)", ge=0, le=10)

    # Image setup configuration
    image_setup_type: str = Field(
        default="scratch",
        pattern="^(scratch|golden)$",
        description="VM image type: 'scratch' builds from base image, 'golden' uses pre-built image"
    )
    root_ssh_filename: Optional[str] = Field(
        default=None,
        description="SSH key filename for golden image root access (required for golden mode)"
    )
    root_ssh_password: Optional[str] = Field(
        default=None,
        description="Root password for golden image (required for golden mode)"
    )


class ProvisionResponse(BaseModel):
    job_id: str
    status: str


class ProvisionStatusResponse(BaseModel):
    job_id: str
    status: str
    params: dict[str, Any]
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    next_retry_at: Optional[datetime] = None


class ProvisionLogsResponse(BaseModel):
    job_id: str
    status: str
    logs: Optional[str] = None
