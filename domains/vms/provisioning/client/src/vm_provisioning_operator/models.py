"""Typed request and response models for the Arkhai provisioning service REST API.

These models are VM's own HTTP contract. The host, job, and aggregate health
and version models are the compute family's, in
``compute_provisioning_contracts``.

Internal server-only types (``VmJobParams``, ``build_simple_params``,
``EvaluateJobRequest``, ``EvaluateJobResponse``) remain in the VM adapter and
are not part of this public surface.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Host registry
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


class VmActionRequest(BaseModel):
    """Optional body fields shared by all single-target VM operations.

    ``host`` and ``vm_name`` come from the URL path; this model contains
    only the override/metadata fields that have no path equivalent.
    """

    max_retries: Optional[int] = Field(
        default=None,
        ge=0,
        le=10,
        description="Per-job retry limit override (default from service config)",
    )


class CreateVmRequest(BaseModel):
    """Provision a new KVM virtual machine on the host identified in the URL.

    ``POST /api/v1/hosts/{host}/vms``

    Returns a ``JobSubmitResponse`` containing a ``job_id``.
    Poll ``GET /api/v1/jobs/{job_id}`` for status.

    On success, ``result`` contains SSH connection details and, if FRP is
    configured, the external tunnel address.

    Credentials (root + tenant) are stored separately and accessible via
    ``GET /api/v1/jobs/{job_id}/credentials``.
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
                    "relay_id": "site-a",
                    "vm_remote_port": 6100,
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

    # Relay tunnelling. Relay-neutral names: the buyer receives a host and a
    # port and has no reason to learn which relay implementation produced them.
    relay_id: Optional[str] = Field(
        default=None,
        description=(
            "Which registered relay this VM is reached through. A reference, "
            "not an endpoint: the address and the admission token are resolved "
            "from the relay at execution, so a token rotated after this request "
            "was accepted still reaches the job, and no credential is written "
            "into the job's persisted parameters — which the job endpoints "
            "return. Requires vm_remote_port."
        ),
    )
    vm_remote_port: Optional[int] = Field(
        default=None,
        description=(
            "Remote port to bind on the relay for this VM. Leased by the "
            "provisioning service before dispatch; the playbook applies what "
            "it is given and selects nothing, because a port binds a listening "
            "socket on the relay and only one authority can avoid collisions."
        ),
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
    max_retries: Optional[int] = Field(
        default=None,
        ge=0,
        le=10,
        description="Per-job retry limit override (default from service config)",
    )

    @model_validator(mode="after")
    def _validate_relay(self) -> "CreateVmRequest":
        """A relay address with nothing to go with it produces an unreachable VM.

        The failure being prevented is a partial relay configuration that
        selects neither access path: the VM is created, no external route
        exists, and the job reports success.
        """
        if not self.relay_id:
            return self
        if not self.vm_remote_port:
            raise ValueError("vm_remote_port is required when relay_id is set")
        return self
