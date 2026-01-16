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


class ProvisionResponse(BaseModel):
    job_id: str
    status: str


class ProvisionStatusResponse(BaseModel):
    job_id: str
    status: str
    params: dict[str, Any]
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None


class ProvisionLogsResponse(BaseModel):
    job_id: str
    status: str
    logs: Optional[str] = None
