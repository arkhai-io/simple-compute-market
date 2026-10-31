"""The real host a real-provisioning VM scenario provisions on.

The target is the ``REAL_VM_TARGET`` section of the e2e settings. It reaches
the settings from ``config-real-vm-target.yml`` in the e2e config directory
when a run selects the ``real-vm-target`` profile
(``ACTIVE_PROFILES=local,real-vm-target``). An environment owner renders that
file; the repository carries only ``config-real-vm-target.yml.example`` and
ignores the real file.

The section is validated before a scenario uses it, and nothing is defaulted:
a missing or misspelled field fails naming it, a version this reader does not
know is refused rather than interpreted, and an access mode the version does
not admit is refused. The models below are the format's documentation.

The section never carries the private key the provisioning service reaches the
host with: the service already holds it, and the target names only the path at
which the service reads it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

#: The settings section the target is read from.
SECTION = "REAL_VM_TARGET"
#: The profile a run selects to load the target, and the file it loads.
PROFILE = "real-vm-target"
PROFILE_FILE = f"config-{PROFILE}.yml"
#: The versions this reader understands.
SUPPORTED_VERSIONS = (1,)

#: A whole number that must be stated as one: a string or a boolean is refused
#: rather than read as a number.
_Count = Annotated[int, Field(strict=True, gt=0)]
_Text = Annotated[str, Field(strict=True, min_length=1)]

#: How the buyer reaches a delivered VM. Version 1 admits only direct access
#: through the host's forwarded port.
AccessMode = Literal["direct"]


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Capacity(_Section):
    """What the host sells: its hardware less what the environment owner keeps
    for the host itself, in the VM capacity dimensions.

    It is declared at the site unchanged, and the scenario deals on a shape
    equal to it, so it must be no more than a guest can be given.
    """

    vcpu_count: _Count = Field(description="Virtual CPUs the host sells.")
    ram_gb: _Count = Field(description="Memory the host sells, in GiB.")
    disk_gb: _Count = Field(description="Root disk the host sells, in GiB.")


class TargetHost(_Section):
    """The one host the scenario registers and provisions on."""

    host_id: _Text = Field(
        description="The executor host's identifier, registered by the scenario."
    )
    ssh_host: _Text = Field(
        description="The address the provisioning service connects to the host at."
    )
    ssh_user: _Text = Field(description="The user the provisioning service connects as.")
    ssh_port: Annotated[int, Field(strict=True, ge=1, le=65535)] = Field(
        description="The port the provisioning service connects to."
    )
    ssh_key_path: _Text = Field(
        description=(
            "Where the provisioning service reads the private key it reaches the "
            "host with: a path in the service's filesystem, never key material."
        )
    )
    public_host: _Text = Field(
        description="The address a buyer reaches the host's guests at."
    )
    capacity: Capacity


class Access(_Section):
    mode: AccessMode = Field(description="How the buyer reaches the delivered VM.")


class RealVmTarget(_Section):
    """Version 1 of the target: exactly one host, reached directly."""

    version: Literal[1] = Field(description="The format version; 1.")
    host: TargetHost
    access: Access


@dataclass(frozen=True)
class TargetNotConfigured:
    """No target section is present, so a scenario needing one has nothing to run on."""

    reason: str


class TargetInvalid(ValueError):
    """A target section is present and cannot be used as it stands."""


def _plain(value: Any) -> Any:
    """The section as plain mappings and lists, as the settings loader read it."""
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _field(location: tuple[Any, ...]) -> str:
    return ".".join([SECTION, *(str(part) for part in location)])


_ABSENT = object()


def load_real_vm_target(settings: Any) -> RealVmTarget | TargetNotConfigured:
    """The validated target from ``settings``, or why there is none.

    ``settings`` is the e2e settings object, or any mapping holding the
    section. An absent section is not an error: a run that does not select the
    profile, or selects it without its file, has no target. A section that is
    present, even empty, and is not a valid target raises ``TargetInvalid``
    naming each offending field.
    """
    section = settings.get(SECTION, _ABSENT)
    if section is _ABSENT:
        return TargetNotConfigured(
            f"no real-provisioning target: the settings hold no {SECTION} section. "
            f"Select the {PROFILE!r} profile (ACTIVE_PROFILES=local,{PROFILE}) with "
            f"{PROFILE_FILE} in the e2e config directory, rendered from "
            f"{PROFILE_FILE}.example; a selected profile whose file is missing, or "
            f"whose file names no {SECTION} section, loads nothing."
        )
    section = _plain(section)
    if not isinstance(section, dict):
        raise TargetInvalid(f"{SECTION} is {type(section).__name__}, not a mapping")
    version = section.get("version")
    # `type`, not `isinstance` or `in`: True and 1.0 both compare equal to 1.
    if type(version) is not int or version not in SUPPORTED_VERSIONS:
        raise TargetInvalid(
            f"{SECTION}.version is {version!r}; this scenario reads version "
            f"{', '.join(str(v) for v in SUPPORTED_VERSIONS)} and does not "
            "interpret another"
        )
    try:
        return RealVmTarget.model_validate(section)
    except ValidationError as error:
        problems = "; ".join(
            f"{_field(detail['loc'])}: {detail['msg']}" for detail in error.errors()
        )
        raise TargetInvalid(f"{SECTION} is not a valid target: {problems}") from None
