from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator

VM_ACTIONS = Literal[
    "create", "list", "start", "shutdown", "destroy", "reboot",
    "undefine", "monitor", "reset_password", "lease_end", "lease_remove", "check"
]


class ProvisionRequest(BaseModel):
    # --- Core (always required) ---
    vm_host: str = Field(default="ww1", description="KVM host from inventory")
    vm_action: VM_ACTIONS = Field(default="create")

    # --- Required for most actions (not list/check) ---
    vm_target: Optional[str] = Field(default=None, description="VM name (libvirt domain)")

    # --- Image setup (create only) ---
    image_setup_type: Optional[Literal["scratch", "golden"]] = Field(default="scratch")

    # --- Sizing (create only, defaults from group_vars/all.yml) ---
    vm_ram: Optional[int] = Field(default=None, ge=512, le=32768, description="RAM in MB")
    vm_vcpus: Optional[int] = Field(default=None, ge=1, le=20, description="Virtual CPUs")
    vm_disk_size: Optional[str] = Field(default=None, pattern=r"^\d+[GMTgmt]$", description="Disk size e.g. '20G'")
    vm_os_variant: Optional[str] = Field(default=None, description="OS variant for virt-install")

    # --- Tenant SSH (create only, optional) ---
    ssh_pubkey: Optional[str] = Field(default=None, description="Tenant SSH public key")

    # --- GPU (create only) ---
    gpu_provisioned: Optional[bool] = Field(default=None, description="Enable GPU passthrough")
    vm_gpu_count: Optional[int] = Field(default=None, ge=1, description="Number of GPUs to auto-select")
    vm_gpu_device: Optional[str] = Field(default=None, description="Single GPU PCI address")
    vm_gpu_devices: Optional[list[str]] = Field(default=None, description="Multiple GPU PCI addresses")
    vm_gpu_partition_size: Optional[str] = Field(default=None, description="MIG/SR-IOV partition")

    # --- FRP tunneling (create only) ---
    frp_server_addr: Optional[str] = Field(default=None, description="FRP server IP")
    frp_domain: Optional[str] = Field(default=None, description="FRP domain")
    frp_dashboard_password: Optional[str] = Field(default=None, description="FRP dashboard password")

    # --- Golden image overrides (create + golden mode) ---
    golden_image_name: Optional[str] = Field(default=None)
    gcs_bucket_url: Optional[str] = Field(default=None)
    gcs_image_path: Optional[str] = Field(default=None)

    # --- Lease (lease_end action) ---
    vm_lease_end: Optional[str] = Field(default=None, description="UTC datetime 'YYYY-MM-DD HH:MM'")

    # --- Retry ---
    max_retries: Optional[int] = Field(default=None, description="Max retry attempts (overrides default)", ge=0, le=10)

    @model_validator(mode="after")
    def validate_action_params(self):
        """Validate required params per action."""
        a = self.vm_action
        needs_target = a not in ("list", "check")
        if needs_target and not self.vm_target:
            raise ValueError(f"vm_target is required for action '{a}'")
        if a == "lease_end" and not self.vm_lease_end:
            raise ValueError("vm_lease_end is required for action 'lease_end'")
        if a == "create" and self.frp_server_addr and not self.frp_dashboard_password:
            raise ValueError("frp_dashboard_password required when frp_server_addr is set")
        return self


class ProvisionResponse(BaseModel):
    job_id: str
    status: str


class AnsibleActionResult(BaseModel):
    """Structured result parsed from Ansible debug output."""
    action: str
    data: dict[str, Any]


class ProvisionStatusResponse(BaseModel):
    job_id: str
    status: str
    params: dict[str, Any]
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    next_retry_at: Optional[datetime] = None
    agent_id: Optional[str] = None


class ProvisionLogsResponse(BaseModel):
    job_id: str
    status: str
    logs: Optional[str] = None


class JobListResponse(BaseModel):
    jobs: list[ProvisionStatusResponse]
    total: int
    offset: int
    limit: int
