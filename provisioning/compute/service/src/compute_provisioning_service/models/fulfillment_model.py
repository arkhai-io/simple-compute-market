"""VM-domain fulfillment request and provider metadata models."""
from pydantic import BaseModel, Field

class VmFulfillmentRequirements(BaseModel):
    vm_target: str = Field(min_length=1)
    image_setup_type: str = 'scratch'
    vm_ram: int = Field(gt=0)
    vm_vcpus: int = Field(gt=0)
    vm_disk_size: str = Field(min_length=1)
    vm_os_variant: str | None = None
    ssh_pubkey: str = Field(min_length=1)
    gpu_provisioned: bool | None = None
    vm_gpu_count: int | None = Field(default=None, ge=0)
    vm_gpu_device: str | None = None
    vm_gpu_devices: list[str] | None = None
    vm_gpu_partition_size: str | None = None

class AnsibleFulfillmentMetadata(BaseModel):
    create_job_id: str
    vm_host: str
    vm_target: str
    teardown_job_id: str | None = None
    current_job_id: str
    operation: str
