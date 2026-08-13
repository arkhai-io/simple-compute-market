"""Canonical VM capacity-dimension vocabulary.

These names and units are part of the VM domain contract. Translation into a
specific provisioning playbook belongs to that provider's requirement delegate.
"""

GPU_COUNT_DIMENSION = "gpu_count"
VCPU_COUNT_DIMENSION = "vcpu_count"
RAM_GB_DIMENSION = "ram_gb"
DISK_GB_DIMENSION = "disk_gb"

DIMENSION_KEYS: tuple[str, ...] = (
    GPU_COUNT_DIMENSION,
    VCPU_COUNT_DIMENSION,
    RAM_GB_DIMENSION,
    DISK_GB_DIMENSION,
)

__all__ = [
    "DIMENSION_KEYS",
    "DISK_GB_DIMENSION",
    "GPU_COUNT_DIMENSION",
    "RAM_GB_DIMENSION",
    "VCPU_COUNT_DIMENSION",
]
