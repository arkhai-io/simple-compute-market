"""Typed request models for each VM operation exposed by the provisioning API.

Each class maps to exactly one ``vm_action``.  Every class provides a
``to_ansible_job_params(vm_host, vm_name)`` method that accepts the path
parameters supplied by the controller and produces the internal
``AnsibleJobParams`` DTO consumed by ``AnsibleJobService``.

**Why vm_host and vm_name are not model fields:**

These values come from the URL path (``/api/v1/hosts/{host}/vms/{vm_name}``),
not from the request body.  Keeping them out of the model:

  - Prevents callers from supplying a body host that contradicts the URL host.
  - Makes the OpenAPI schema accurate — the schema only describes body fields.
  - Mirrors standard REST practice (resource identity in the URL).

Controllers pass them explicitly to ``to_ansible_job_params()``.

File naming: ``_model`` suffix marks this as a model definition file.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from models.jobs_model import AnsibleJobParams


# ---------------------------------------------------------------------------
# Shared optional body fields — present on every VM operation
# ---------------------------------------------------------------------------


class VmActionRequest(BaseModel):
    """Optional body fields shared by all single-target VM operations.

    ``host`` and ``vm_name`` come from the URL path; this model contains
    only the override/metadata fields that have no path equivalent.
    """

    buyer_agent_id: Optional[str] = Field(
        default=None, description="ERC-8004 agent ID of the buyer (tenant)"
    )
    max_retries: Optional[int] = Field(
        default=None,
        ge=0,
        le=10,
        description="Per-job retry limit override (default from service config)",
    )


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


class CreateVmRequest(BaseModel):
    """Provision a new KVM virtual machine on the host identified in the URL.

    ``POST /api/v1/hosts/{host}/vms``

    Returns a ``JobSubmitResponse`` containing a ``job_id``.
    Poll ``GET /api/v1/jobs/{job_id}`` for status.

    On success, ``result`` contains SSH connection details and, if FRP is
    configured, the external tunnel address.

    Credentials (root + tenant) are stored separately and accessible via
    ``GET /api/v1/jobs/{job_id}/credentials`` using the ``X-Agent-ID`` header.
    """

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "vm_target": "agent-vm-01",
                    "vm_ram": 4096,
                    "vm_vcpus": 2,
                    "vm_disk_size": "20G",
                    "ssh_pubkey": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI...",
                    "gpu_provisioned": True,
                    "frp_server_addr": "34.87.54.66",
                    "frp_domain": "example.com",
                    "frp_dashboard_password": "secret",
                }
            ]
        }
    }

    vm_target: str = Field(description="VM name to assign (libvirt domain name)")
    image_setup_type: Literal["scratch", "golden"] = Field(
        default="scratch",
        description=(
            "'scratch' boots from the base Ubuntu cloud image. "
            "'golden' clones from a pre-built qcow2 image stored in GCS — "
            "requires golden_* config keys to be set in the service config."
        ),
    )

    # Sizing
    vm_ram: Optional[int] = Field(
        default=None, ge=512, le=32768, description="RAM in MB"
    )
    vm_vcpus: Optional[int] = Field(
        default=None, ge=1, le=20, description="Virtual CPUs"
    )
    vm_disk_size: Optional[str] = Field(
        default=None, pattern=r"^\d+[GMTgmt]$", description="Disk size e.g. '20G'"
    )
    vm_os_variant: Optional[str] = Field(
        default=None,
        description="OS variant hint for virt-install (e.g. 'ubuntu22.04')",
    )

    # Tenant SSH
    ssh_pubkey: Optional[str] = Field(
        default=None,
        description=(
            "Tenant SSH public key injected into the VM at creation. "
            "If omitted, an SSH keypair is generated and the private key "
            "stored in the job credentials."
        ),
    )

    # GPU passthrough
    gpu_provisioned: Optional[bool] = Field(
        default=None, description="Enable GPU passthrough"
    )
    vm_gpu_count: Optional[int] = Field(
        default=None, ge=1, description="Number of GPUs to auto-select"
    )
    vm_gpu_device: Optional[str] = Field(
        default=None, description="Single GPU PCI address (e.g. '0000:03:00.0')"
    )
    vm_gpu_devices: Optional[list[str]] = Field(
        default=None,
        description="Multiple GPU PCI addresses for multi-GPU passthrough",
    )
    vm_gpu_partition_size: Optional[str] = Field(
        default=None, description="MIG or SR-IOV partition size (e.g. '1g.5gb')"
    )

    # FRP tunnelling
    frp_server_addr: Optional[str] = Field(
        default=None,
        description=(
            "IP address of the FRP server. When set, the VM's SSH port is "
            "tunnelled through FRP rather than exposed via direct port-forward. "
            "Requires frp_domain and frp_dashboard_password."
        ),
    )
    frp_domain: Optional[str] = Field(
        default=None,
        description="Base domain of the FRP server (e.g. 'arkhainet.example.com')",
    )
    frp_dashboard_password: Optional[str] = Field(
        default=None,
        description="FRP dashboard password (required when frp_server_addr is set)",
    )

    # Golden image overrides (create + golden mode only)
    golden_image_name: Optional[str] = Field(
        default=None,
        description=(
            "Override the golden image name from service config. "
            "Only used when image_setup_type='golden'."
        ),
    )
    gcs_bucket_url: Optional[str] = Field(
        default=None, description="GCS bucket URL to download the golden image from"
    )
    gcs_image_path: Optional[str] = Field(
        default=None,
        description="Path within the GCS bucket to the golden image",
    )

    # Shared overrides
    buyer_agent_id: Optional[str] = Field(
        default=None, description="ERC-8004 agent ID of the buyer (tenant)"
    )
    max_retries: Optional[int] = Field(
        default=None,
        ge=0,
        le=10,
        description="Per-job retry limit override (default from service config)",
    )

    @model_validator(mode="after")
    def _validate_frp(self) -> "CreateVmRequest":
        if self.frp_server_addr and not self.frp_dashboard_password:
            raise ValueError(
                "frp_dashboard_password is required when frp_server_addr is set"
            )
        return self

    def to_ansible_job_params(self, host: str) -> AnsibleJobParams:
        """Build ``AnsibleJobParams`` using path-supplied ``host``."""
        return AnsibleJobParams(
            vm_host=host,
            vm_action="create",
            vm_target=self.vm_target,
            image_setup_type=self.image_setup_type,
            vm_ram=self.vm_ram,
            vm_vcpus=self.vm_vcpus,
            vm_disk_size=self.vm_disk_size,
            vm_os_variant=self.vm_os_variant,
            ssh_pubkey=self.ssh_pubkey,
            gpu_provisioned=self.gpu_provisioned,
            vm_gpu_count=self.vm_gpu_count,
            vm_gpu_device=self.vm_gpu_device,
            vm_gpu_devices=self.vm_gpu_devices,
            vm_gpu_partition_size=self.vm_gpu_partition_size,
            frp_server_addr=self.frp_server_addr,
            frp_domain=self.frp_domain,
            frp_dashboard_password=self.frp_dashboard_password,
            golden_image_name=self.golden_image_name,
            gcs_bucket_url=self.gcs_bucket_url,
            gcs_image_path=self.gcs_image_path,
            buyer_agent_id=self.buyer_agent_id,
            max_retries=self.max_retries,
        )


# ---------------------------------------------------------------------------
# Expiry scheduling (body carries vm_expiry_at; host+vm_name from path)
# ---------------------------------------------------------------------------


class ScheduleVmExpiryRequest(BaseModel):
    """Schedule automatic VM destruction at a future UTC datetime.

    ``POST /api/v1/hosts/{host}/vms/{vm_name}/expiry``

    NYI(Item 2): will write directly to the ``vm_leases`` DB table once the
    DB-driven lease watchdog is implemented.  Currently submits a
    ``lease_end`` Ansible job that schedules an ``at`` daemon job on the
    KVM host.
    """

    vm_expiry_at: str = Field(
        description=(
            "UTC datetime for VM expiry in ISO 8601 format "
            "(e.g. '2025-12-31T23:59:00'). The VM will be destroyed at this time."
        )
    )
    buyer_agent_id: Optional[str] = Field(
        default=None, description="ERC-8004 agent ID of the buyer (tenant)"
    )
    max_retries: Optional[int] = Field(
        default=None, ge=0, le=10,
        description="Per-job retry limit override",
    )

    def to_ansible_job_params(self, host: str, vm_name: str) -> AnsibleJobParams:
        return AnsibleJobParams(
            vm_host=host,
            vm_action="lease_end",
            vm_target=vm_name,
            vm_expiry_at=self.vm_expiry_at,
            buyer_agent_id=self.buyer_agent_id,
            max_retries=self.max_retries,
        )


# ---------------------------------------------------------------------------
# Helper — build AnsibleJobParams for simple path-only actions
# (start, shutdown, reboot, destroy, undefine, monitor,
#  reset_password, cancel_expiry, list_vms, check_capacity)
# ---------------------------------------------------------------------------


def build_simple_params(
    action: str,
    host: str,
    body: VmActionRequest,
    vm_name: Optional[str] = None,
) -> AnsibleJobParams:
    """Produce ``AnsibleJobParams`` for actions whose only inputs are the
    path parameters and the shared optional overrides in ``VmActionRequest``.

    ``vm_name`` is ``None`` for host-level actions (list, check).
    """
    return AnsibleJobParams(
        vm_host=host,
        vm_action=action,
        vm_target=vm_name,
        buyer_agent_id=body.buyer_agent_id,
        max_retries=body.max_retries,
    )
