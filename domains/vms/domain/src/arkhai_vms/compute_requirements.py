"""Canonical VM capacity-dimension vocabulary.

VM capacity is stated in the compute family's vocabulary, which every compute
domain binds from one owner so a VM listing and a bare-metal listing with the
same hardware publish the same fields. The names are re-exported here so VM
code keeps reading them from its own domain package. Translation into a
specific provisioning playbook belongs to that provider's requirement delegate.
"""

from arkhai_compute import (
    COMPUTE_CAPABILITY_SCHEMA,
    DIMENSION_KEYS,
    DISK_GB_DIMENSION,
    GPU_COUNT_DIMENSION,
    GPU_MODEL_ATTRIBUTE,
    RAM_GB_DIMENSION,
    VCPU_COUNT_DIMENSION,
)

# A VM shape is a compute-family shape: the VM domain adds no family or field.
VM_CAPABILITY_SCHEMA = COMPUTE_CAPABILITY_SCHEMA

__all__ = [
    "DIMENSION_KEYS",
    "GPU_MODEL_ATTRIBUTE",
    "VM_CAPABILITY_SCHEMA",
    "DISK_GB_DIMENSION",
    "GPU_COUNT_DIMENSION",
    "RAM_GB_DIMENSION",
    "VCPU_COUNT_DIMENSION",
]
