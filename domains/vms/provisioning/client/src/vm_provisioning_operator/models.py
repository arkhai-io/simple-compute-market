"""Typed request and response models for the Arkhai provisioning service REST API.

These models are VM's own HTTP contract. The host, job, and aggregate health
and version models are the compute family's, in
``compute_provisioning_contracts``.

Internal server-only types (``VmJobParams``, ``build_simple_params``,
``EvaluateJobRequest``) remain in the VM adapter and are not part of this
public surface; the mock routes' models are the compute family's.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal, Optional

from compute_provisioning_contracts import ResultEnvelope
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
    model_validator,
)


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


# ---------------------------------------------------------------------------
# Host diagnostics
# ---------------------------------------------------------------------------

#: The units every host diagnostics job reports: the hypervisor daemon, and the
#: relay client that carries buyers' connections to relayed guests.
LIBVIRTD_UNIT = "libvirtd.service"
RELAY_CLIENT_UNIT = "frpc-buyers.service"

#: The ``result_kind`` of a succeeded host diagnostics job's result.
HOST_DIAGNOSTICS_RESULT_KIND = "vm_diagnose"

# systemd's unit-name syntax (systemd.unit(5)) for a service: a prefix of
# letters, digits, ":", "-", "_", "." and "\", an optional "@" and instance of
# the same characters, then ".service", 255 characters at most. The name
# reaches the host as an argument to systemctl, so nothing outside this set
# may. Only a service has the main PID and restart count a diagnostics read
# reports; for any other unit type systemctl reports neither, and the typed
# parse would refuse the job's result.
_SERVICE_UNIT_NAME = re.compile(r"[A-Za-z0-9:_.\\-]+(?:@[A-Za-z0-9:_.\\-]*)?\.service")
_UNIT_NAME_MAX = 255


def check_service_unit_name(name: str) -> str:
    """Return ``name`` if it is a systemd service unit name; raise ``ValueError`` otherwise."""
    if len(name) > _UNIT_NAME_MAX or not _SERVICE_UNIT_NAME.fullmatch(name):
        raise ValueError(f"{name!r} is not a systemd service unit name")
    return name


class HostDiagnosticsRequest(VmActionRequest):
    """The inputs of a host diagnostics job, beside the shared overrides.

    ``management_unit`` names one more service to report, the operator's own
    management client, whose name this repository does not know. One that is
    not a systemd service unit name is refused here, so the typed client
    refuses it before sending and the route as 422 before any job is queued.
    """

    management_unit: Optional[str] = Field(
        default=None,
        description="A further systemd service to report, such as the operator's management client",
    )

    @field_validator("management_unit")
    @classmethod
    def _unit_name(cls, value: Optional[str]) -> Optional[str]:
        return value if value is None else check_service_unit_name(value)


class HostDiagnosticsError(ValueError):
    """A host diagnostics job's result that is not a well-formed diagnostics fact.

    ``field`` names the missing or malformed field, dotted from the result's
    value (``units.libvirtd.service.restart_count``).
    """

    def __init__(self, field: str, reason: str) -> None:
        super().__init__(f"host diagnostics field {field!r}: {reason}")
        self.field = field
        self.reason = reason


class UnitDiagnostics(BaseModel):
    """One systemd unit as ``systemctl show`` reports it.

    ``invocation_id`` changes each time the unit starts, so two reads with the
    same one saw the same run; ``restart_count`` counts systemd's automatic
    restarts since the unit was last started by hand. ``invocation_id`` and
    ``active_enter_timestamp`` are empty for a unit not started since boot.
    """

    model_config = ConfigDict(frozen=True)

    active_state: StrictStr
    invocation_id: StrictStr
    main_pid: StrictInt
    restart_count: StrictInt
    active_enter_timestamp: StrictStr
    result: StrictStr


class HostDiagnostics(BaseModel):
    """What a host diagnostics job read on its host.

    Read from a job with ``from_job_result``, which refuses a result lacking
    any field or carrying one of the wrong type, rather than returning part of
    it.
    """

    model_config = ConfigDict(frozen=True)

    host: StrictStr
    timestamp: StrictStr
    boot_id: StrictStr
    uptime_seconds: Annotated[float, Field(strict=True)]
    kernel: StrictStr
    running_guests: StrictInt
    management_unit: Optional[StrictStr]
    units: dict[StrictStr, UnitDiagnostics]

    @classmethod
    def from_job_result(cls, result: ResultEnvelope | None) -> "HostDiagnostics":
        """The diagnostics a succeeded job's result reports.

        Raises ``HostDiagnosticsError`` naming the first field that is missing
        or of the wrong type, the result's kind included; a result reporting no
        entry for ``libvirtd.service``, ``frpc-buyers.service`` or the
        management unit it names is missing that unit.
        """
        if result is None:
            raise HostDiagnosticsError("result", "the job reported no result")
        if result.result_kind != HOST_DIAGNOSTICS_RESULT_KIND:
            raise HostDiagnosticsError(
                "result_kind",
                f"{result.result_kind!r} is not {HOST_DIAGNOSTICS_RESULT_KIND!r}",
            )
        try:
            diagnostics = cls.model_validate(result.value)
        except ValidationError as exc:
            error = exc.errors()[0]
            raise HostDiagnosticsError(
                ".".join(str(part) for part in error["loc"]), error["msg"]
            ) from exc
        for unit in diagnostics.reported_units():
            if unit not in diagnostics.units:
                raise HostDiagnosticsError(f"units.{unit}", "the unit is not reported")
        return diagnostics

    def reported_units(self) -> tuple[str, ...]:
        """The units the job was asked to report, the management unit last."""
        units = (LIBVIRTD_UNIT, RELAY_CLIENT_UNIT)
        return units + (self.management_unit,) if self.management_unit else units

    @property
    def libvirtd(self) -> UnitDiagnostics:
        return self.units[LIBVIRTD_UNIT]

    @property
    def relay_client(self) -> UnitDiagnostics:
        return self.units[RELAY_CLIENT_UNIT]

    @property
    def management(self) -> UnitDiagnostics | None:
        """The management unit's state, or ``None`` when the job named none."""
        return self.units[self.management_unit] if self.management_unit else None
