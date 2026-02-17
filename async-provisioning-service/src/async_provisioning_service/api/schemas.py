from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator

VM_ACTIONS = Literal[
    "create", "list", "start", "shutdown", "destroy", "reboot",
    "undefine", "monitor", "reset_password", "lease_end", "lease_remove", "check"
]


class ProvisionRequest(BaseModel):
    """VM provisioning job request.

    Specifies the target host, action, and optional resource/network parameters.
    Required fields depend on the chosen ``vm_action`` (see validation rules).
    """

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "vm_host": "ww1",
                    "vm_target": "agent-vm-01",
                    "vm_action": "create",
                    "vm_ram": 4096,
                    "vm_vcpus": 2,
                    "vm_disk_size": "20G",
                    "ssh_pubkey": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI... agent@market",
                    "gpu_provisioned": True,
                    "frp_server_addr": "34.87.54.66",
                    "frp_domain": "example.com",
                    "frp_dashboard_password": "secret",
                },
                {
                    "vm_host": "ww1",
                    "vm_action": "list",
                },
                {
                    "vm_host": "ww1",
                    "vm_target": "agent-vm-01",
                    "vm_action": "lease_end",
                    "vm_lease_end": "2025-12-31 23:59",
                },
            ]
        }
    }

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

    # --- Marketplace context ---
    order_id: Optional[str] = Field(default=None, description="Marketplace order ID this VM fulfills")
    seller_agent_id: Optional[str] = Field(default=None, description="Seller agent ID (compute provider)")
    buyer_agent_id: Optional[str] = Field(default=None, description="Buyer agent ID (compute consumer)")
    negotiation_id: Optional[str] = Field(default=None, description="Negotiation thread ID")
    escrow_uid: Optional[str] = Field(default=None, description="Escrow UID from alkahest")

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
    """Confirmation returned when a provisioning job is accepted."""

    job_id: str = Field(description="Unique identifier for the queued job")
    status: str = Field(description="Initial job status (always 'queued')")


class AnsibleActionResult(BaseModel):
    """Structured result parsed from Ansible debug output."""
    action: str
    data: dict[str, Any]


class ProvisionStatusResponse(BaseModel):
    """Full job status including parameters, result, and retry metadata."""

    job_id: str = Field(description="Unique job identifier")
    status: str = Field(description="Current status: queued, running, succeeded, failed, or cancelled")
    params: dict[str, Any] = Field(description="Original request parameters submitted with the job")
    result: Optional[dict[str, Any]] = Field(default=None, description="Structured result from Ansible on success (SSH info, VM state, etc.)")
    error: Optional[str] = Field(default=None, description="Error message if the job failed")
    retry_count: int = Field(default=0, description="Number of retries attempted so far")
    max_retries: int = Field(default=3, description="Maximum retries allowed for this job")
    next_retry_at: Optional[datetime] = Field(default=None, description="Scheduled time for the next retry attempt (UTC)")
    agent_id: Optional[str] = Field(default=None, description="ERC-8004 agent ID that submitted the job")


class ProvisionLogsResponse(BaseModel):
    """Raw Ansible playbook output for a provisioning job."""

    job_id: str = Field(description="Unique job identifier")
    status: str = Field(description="Current job status")
    logs: Optional[str] = Field(default=None, description="Raw Ansible stdout/stderr captured during execution")


class JobListResponse(BaseModel):
    """Paginated list of provisioning jobs."""

    jobs: list[ProvisionStatusResponse] = Field(description="Jobs on the current page")
    total: int = Field(description="Total number of jobs matching the query")
    offset: int = Field(description="Number of jobs skipped (pagination offset)")
    limit: int = Field(description="Maximum jobs returned per page")


class ProvisionedVMResponse(BaseModel):
    """Provisioned VM with credential fields filtered by requesting agent's role."""

    id: str
    job_id: str
    vm_name: str
    vm_host: str
    vm_ip_internal: str | None = None
    vm_state: str | None = None
    order_id: str | None = None
    seller_agent_id: str | None = None
    buyer_agent_id: str | None = None
    negotiation_id: str | None = None
    escrow_uid: str | None = None
    # Credential fields — populated based on requesting agent's role
    root_password: str | None = None
    root_ssh_key_path: str | None = None
    root_ssh_commands: dict | None = None
    tenant_user: str | None = None
    tenant_password: str | None = None
    tenant_ssh_commands: dict | None = None
    external_ssh_port: str | None = None
    frp_domain: str | None = None
    created_at: datetime | None = None


class ProvisionedVMListResponse(BaseModel):
    """List of provisioned VMs."""

    vms: list[ProvisionedVMResponse]
    total: int
