"""The compute family's capability-shape vocabulary.

Every compute domain states and reads capacity in these families and fields, so
a VM listing and a bare-metal listing with the same hardware flatten to the same
published fields, claim dimensions, and site declaration keys. Translation into
a specific provisioning playbook belongs to that provider's requirement
delegate, not here. See openspec/specs/market-composition/spec.md.
"""

from __future__ import annotations

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

# The flat names are the published listing fields, the capacity-claim
# dimensions, and the site's declared capacity keys, so they are the existing
# wire names rather than family-prefixed ones: ``memory.gib`` flattens to
# ``ram_gb`` and ``storage.gib`` to ``disk_gb``. Both are GiB. Only ``gpu`` is
# required; a family a shape omits states nothing about it.
COMPUTE_CAPABILITY_SCHEMA = CapabilitySchema(
    fields=(
        ShapeField("gpu", "count", FieldKind.QUANTITY, GPU_COUNT_DIMENSION, required=True),
        ShapeField("gpu", "model", FieldKind.ATTRIBUTE, GPU_MODEL_ATTRIBUTE, required=True),
        ShapeField("cpu", "count", FieldKind.QUANTITY, VCPU_COUNT_DIMENSION),
        ShapeField("memory", "gib", FieldKind.QUANTITY, RAM_GB_DIMENSION),
        ShapeField("storage", "gib", FieldKind.QUANTITY, DISK_GB_DIMENSION),
    )
)

__all__ = [
    "COMPUTE_CAPABILITY_SCHEMA",
    "DIMENSION_KEYS",
    "DISK_GB_DIMENSION",
    "GPU_COUNT_DIMENSION",
    "GPU_MODEL_ATTRIBUTE",
    "RAM_GB_DIMENSION",
    "VCPU_COUNT_DIMENSION",
]
