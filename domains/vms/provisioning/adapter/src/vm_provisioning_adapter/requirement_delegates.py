"""Registered translators from canonical VM dimensions to playbook variables."""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from arkhai_vms import (
    DISK_GB_DIMENSION,
    GPU_COUNT_DIMENSION,
    RAM_GB_DIMENSION,
    VCPU_COUNT_DIMENSION,
)
from market_fulfillment import ProviderConfigInvalidError

DEFAULT_REQUIREMENT_DELEGATE = "vm_management_v1"


class RequirementDelegate(ABC):
    """Validate and translate committed dimensions for one playbook contract."""

    @abstractmethod
    def translate(self, dimensions: Mapping[str, Any] | None) -> dict[str, Any]:
        raise NotImplementedError


class VmManagementV1RequirementDelegate(RequirementDelegate):
    """Variable contract used by the repository's vm-management playbook."""

    _MIB_PER_GIB = 1024

    @staticmethod
    def _integer(dims: Mapping[str, Any], key: str, *, minimum: int) -> int:
        value = dims[key]
        if isinstance(value, bool):
            parsed = None
        elif isinstance(value, int):
            parsed = value
        elif isinstance(value, (str, Decimal)):
            try:
                decimal_value = Decimal(value)
            except (InvalidOperation, ValueError):
                parsed = None
            else:
                parsed = int(decimal_value) if decimal_value == decimal_value.to_integral_value() else None
        else:
            parsed = None
        if parsed is None or parsed < minimum:
            raise ProviderConfigInvalidError(
                f"reservation dimension '{key}' must be an integer >= {minimum}"
            )
        return parsed

    def translate(self, dimensions: Mapping[str, Any] | None) -> dict[str, Any]:
        dims = dict(dimensions or {})
        values: dict[str, Any] = {}
        if GPU_COUNT_DIMENSION in dims:
            count = self._integer(dims, GPU_COUNT_DIMENSION, minimum=0)
            values["vm_gpu_count"] = count
            values["gpu_provisioned"] = count > 0
        if VCPU_COUNT_DIMENSION in dims:
            values["vm_vcpus"] = self._integer(dims, VCPU_COUNT_DIMENSION, minimum=1)
        if RAM_GB_DIMENSION in dims:
            values["vm_ram"] = self._integer(dims, RAM_GB_DIMENSION, minimum=1) * self._MIB_PER_GIB
        if DISK_GB_DIMENSION in dims:
            size = self._integer(dims, DISK_GB_DIMENSION, minimum=1)
            values["vm_disk_size"] = f"{size}G"
        return values


_REQUIREMENT_DELEGATES: dict[str, type[RequirementDelegate]] = {
    DEFAULT_REQUIREMENT_DELEGATE: VmManagementV1RequirementDelegate,
}


def registered_requirement_delegate_names() -> frozenset[str]:
    return frozenset(_REQUIREMENT_DELEGATES)


def resolve_requirement_delegate(name: str) -> RequirementDelegate:
    try:
        delegate_type = _REQUIREMENT_DELEGATES[name]
    except KeyError as exc:
        raise ProviderConfigInvalidError(
            f"unknown Ansible requirement delegate '{name}'"
        ) from exc
    return delegate_type()
