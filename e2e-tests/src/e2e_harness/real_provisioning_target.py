"""Typed operator targets for the real-provisioning scenarios.

The ignored ``config-real-provisioning-target.yml`` profile holds public host
metadata, public SSH host keys and service-side authentication key paths. Each lane
selects its own domain's host; missing configuration skips, invalid configuration
fails before scenario mutations.
"""
from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel, ConfigDict, Field, ValidationError, ValidationInfo,
    field_validator, model_validator,
)

from vm_provisioning_operator import check_service_unit_name

from e2e_harness.ssh_host_key import canonical_host_public_key

SECTION = "REAL_PROVISIONING_TARGET"
PROFILE = "real-provisioning-target"
PROFILE_FILE = f"config-{PROFILE}.yml"
SUPPORTED_VERSIONS = (2,)
_Count = Annotated[int, Field(strict=True, gt=0)]
_Text = Annotated[str, Field(strict=True, min_length=1)]


#: The private ranges the VM host kit's guest policy drops a guest's forwarded
#: packets to unless a seller lists the destination
#: (``domains/vms/provisioning/iac/ansible/roles/vm-setup/templates/guest-policy.rules.j2``).
GUEST_POLICY_PRIVATE_RANGES = tuple(
    ipaddress.IPv4Network(block)
    for block in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10")
)
#: libvirt's ``default`` network, which every VM guest is attached to.
GUESTS_NETWORK = ipaddress.IPv4Network("192.168.122.0/24")


def _harness_local_path(value: str, field: str) -> str:
    """A path on the harness's own machine: absolute, with no ``..`` component."""
    if not value.startswith("/") or ".." in value.split("/"):
        raise ValueError(f"{field} must be an absolute harness-local path")
    return value


def _guest_policy_private_address(value: str, field: str) -> str:
    """An IPv4 address in one of the guest policy's private ranges."""
    try:
        address = ipaddress.IPv4Address(value)
    except ValueError:
        raise ValueError(f"{field} must be an IPv4 address") from None
    if not any(address in block for block in GUEST_POLICY_PRIVATE_RANGES):
        ranges = ", ".join(str(block) for block in GUEST_POLICY_PRIVATE_RANGES)
        raise ValueError(f"{field} must be in a private range the guest policy drops ({ranges})")
    if address in GUESTS_NETWORK:
        raise ValueError(f"{field} must not be on the guests' own network {GUESTS_NETWORK}, "
                         "which the guest policy's other rules decide")
    return str(address)


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Capacity(_Section):
    """Sellable host capacity, excluding resources retained by the operator."""

    vcpu_count: _Count
    ram_gb: _Count
    disk_gb: _Count


class Connection(_Section):
    """How the provisioning service reaches the host; the key path is service-local."""

    ssh_host: _Text
    ssh_user: _Text
    ssh_port: Annotated[int, Field(strict=True, ge=1, le=65535)]
    ssh_key_path: _Text


class DirectAccess(_Section):
    mode: Literal["direct"]
    public_host: _Text


class RelayAccess(_Section):
    mode: Literal["relay"]
    relay_id: _Text
    #: A file of the relay's admission plugin decision lines
    #: (``tools/frp-grant-admission/README.md#the-log``) that the deployment
    #: keeps current on the harness's machine. Without it, a qualification
    #: stage checking a lease's admission skips, naming this field.
    admission_log: _Text | None = None

    @field_validator("admission_log")
    @classmethod
    def absolute_admission_log(cls, value: str | None) -> str | None:
        return value if value is None else _harness_local_path(value, "admission_log")


Access = Annotated[DirectAccess | RelayAccess, Field(discriminator="mode")]


class _Host(_Section):
    host_id: _Text
    connection: Connection
    access: Access
    capacity: Capacity


class CleanupOperator(_Section):
    """A harness-local operator route to a host, running fixed observer code
    under ``sudo -n``; its key is referenced, never copied. The bare-metal
    cleanup qualification and the VM guest-isolation proof each name one."""

    host: _Text
    port: Annotated[int, Field(strict=True, ge=1, le=65535)]
    user: _Text
    key_path: _Text

    @field_validator("key_path")
    @classmethod
    def absolute_key_path(cls, value: str) -> str:
        return _harness_local_path(value, "key_path")


class PrivateDestinations(_Section):
    """Two private destinations a guest probes, neither of which needs to answer:
    one host preparation was not given (``refused``) and one it was given in
    ``guest_allowed_private_destinations`` (``listed``)."""

    refused: _Text
    listed: _Text

    @field_validator("refused", "listed")
    @classmethod
    def private_address(cls, value: str, info: ValidationInfo) -> str:
        return _guest_policy_private_address(value, info.field_name)

    @model_validator(mode="after")
    def distinct(self) -> Self:
        if self.refused == self.listed:
            raise ValueError("listed must differ from refused")
        return self


class GuestIsolation(_Section):
    """The opt-in inputs of the VM guest-isolation proof: the operator route its
    host-side steps take, and the private destinations its guests probe."""

    operator: CleanupOperator
    private_destinations: PrivateDestinations | None = None


class VmHost(_Host):
    domain: Literal["vm"]
    resource_id: _Text | None = None
    listing_shape: Capacity
    #: Without it, every host-side stage of the guest-isolation proof skips,
    #: naming this field.
    guest_isolation: GuestIsolation | None = None
    ssh_host_public_key: _Text | None = None

    @field_validator("ssh_host_public_key")
    @classmethod
    def valid_host_key(cls, value: str | None) -> str | None:
        return canonical_host_public_key(value) if value is not None else None
    #: The operator's management client on the host, a systemd service whose
    #: name this repository cannot know, for host diagnostics to report beside
    #: the host's own units. Optional.
    management_unit: _Text | None = None

    @field_validator("management_unit")
    @classmethod
    def service_unit_name(cls, value: str | None) -> str | None:
        return value if value is None else check_service_unit_name(value)

    @field_validator("listing_shape")
    @classmethod
    def fits_two_guests(cls, shape: Capacity, info: ValidationInfo) -> Capacity:
        capacity = info.data.get("capacity")
        if capacity is not None:
            for dimension in Capacity.model_fields:
                if getattr(shape, dimension) * 2 > getattr(capacity, dimension):
                    raise ValueError(f"listing_shape.{dimension} must fit twice within capacity.{dimension}")
        return shape


class CleanupQualification(_Section):
    """Explicit opt-in to disposable tenant fixtures and independent observations."""

    policy_id: _Text
    operator: CleanupOperator


class BareMetalHost(_Host):
    domain: Literal["bare_metal"]
    physical_host_id: _Text
    pool_id: _Text | None = None
    resource_id: _Text | None = None
    cleanup_qualification: CleanupQualification | None = None
    ssh_host_public_key: _Text

    @field_validator("ssh_host_public_key")
    @classmethod
    def valid_host_key(cls, value: str) -> str:
        return canonical_host_public_key(value)


TargetHost = Annotated[VmHost | BareMetalHost, Field(discriminator="domain")]


class RealProvisioningTarget(_Section):
    version: Literal[2]
    hosts: Annotated[list[TargetHost], Field(min_length=1)]

    @model_validator(mode="after")
    def unique_domains(self) -> Self:
        domains: set[str] = set()
        for host in self.hosts:
            if host.domain in domains:
                raise ValueError(f"hosts.domain {host.domain!r} is repeated; at most one host per domain is allowed")
            domains.add(host.domain)
        return self

    def host_for(self, domain: Literal["vm", "bare_metal"]) -> VmHost | BareMetalHost | None:
        return next((host for host in self.hosts if host.domain == domain), None)


@dataclass(frozen=True)
class TargetNotConfigured:
    reason: str


class TargetInvalid(ValueError):
    """A present target is invalid and must not be treated as a missing target."""


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _field(location: tuple[Any, ...]) -> str:
    return ".".join([SECTION, *(str(part) for part in location)])


_CONVERSION = (
    f"Use profile {PROFILE!r} and {PROFILE_FILE}: rename REAL_VM_TARGET to "
    f"{SECTION}, set version: 2, put host under hosts with domain: vm, move "
    "ssh_host/ssh_user/ssh_port/ssh_key_path into connection and access into that "
    "host, move public_host into direct access, and state listing_shape fitting "
    "twice within capacity. Relay access names relay_id instead of public_host."
)
_ABSENT = object()


def load_real_provisioning_target(settings: Any) -> RealProvisioningTarget | TargetNotConfigured:
    """Read and validate the complete target before selecting a lane's host."""
    section = settings.get(SECTION, _ABSENT)
    if section is _ABSENT:
        if settings.get("REAL_VM_TARGET", _ABSENT) is not _ABSENT:
            raise TargetInvalid(f"REAL_VM_TARGET version 1 is no longer supported. {_CONVERSION}")
        return TargetNotConfigured(
            f"no real-provisioning target: settings hold no {SECTION} section. "
            f"Select profile {PROFILE!r} (ACTIVE_PROFILES=local,{PROFILE}) with "
            f"{PROFILE_FILE} rendered from {PROFILE_FILE}.example in the e2e config directory."
        )
    section = _plain(section)
    if not isinstance(section, dict):
        raise TargetInvalid(f"{SECTION} is {type(section).__name__}, not a mapping")
    version = section.get("version")
    if type(version) is int and version == 1:
        raise TargetInvalid(f"{SECTION}.version 1 is no longer supported. {_CONVERSION}")
    if type(version) is not int or version not in SUPPORTED_VERSIONS:
        raise TargetInvalid(f"{SECTION}.version is {version!r}; this scenario reads version 2 and does not interpret another")
    try:
        return RealProvisioningTarget.model_validate(section)
    except ValidationError as error:
        problems = "; ".join(f"{_field(detail['loc'])}: {detail['msg']}" for detail in error.errors())
        raise TargetInvalid(f"{SECTION} is not a valid target: {problems}") from None
