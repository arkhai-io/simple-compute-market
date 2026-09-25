"""Canonical VM capacity-dimension vocabulary.

These names and units are part of the VM domain contract. Translation into a
specific provisioning playbook belongs to that provider's requirement delegate.
"""

from market_capability_shape import CapabilitySchema, FieldKind, ShapeField

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

GPU_MODEL_ATTRIBUTE = "gpu_model"

# The VM vocabulary for family-grouped capability shapes. The flat names are
# the published listing fields, the capacity-claim dimensions, and the site's
# declared capacity keys, so they are the existing wire names rather than
# family-prefixed ones: ``memory.gib`` flattens to ``ram_gb`` and
# ``storage.gib`` to ``disk_gb``. Both are GiB, as the requirement delegate
# treats them. Only ``gpu`` is required; a family a shape omits commits
# nothing, and the site provisions it from its own defaults.
VM_CAPABILITY_SCHEMA = CapabilitySchema(
    fields=(
        ShapeField("gpu", "count", FieldKind.QUANTITY, GPU_COUNT_DIMENSION, required=True),
        ShapeField("gpu", "model", FieldKind.ATTRIBUTE, GPU_MODEL_ATTRIBUTE, required=True),
        ShapeField("cpu", "count", FieldKind.QUANTITY, VCPU_COUNT_DIMENSION),
        ShapeField("memory", "gib", FieldKind.QUANTITY, RAM_GB_DIMENSION),
        ShapeField("storage", "gib", FieldKind.QUANTITY, DISK_GB_DIMENSION),
    )
)

__all__ = [
    "DIMENSION_KEYS",
    "GPU_MODEL_ATTRIBUTE",
    "VM_CAPABILITY_SCHEMA",
    "DISK_GB_DIMENSION",
    "GPU_COUNT_DIMENSION",
    "RAM_GB_DIMENSION",
    "VCPU_COUNT_DIMENSION",
]
