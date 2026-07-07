"""Bare-metal domain contracts."""

from .models import (
    BARE_METAL_EXECUTOR_KIND,
    EXCLUSIVE_ALLOCATION_MODE,
    PHYSICAL_HOST_ID_REF_KEY,
    BareMetalLeaseCreate,
    BareMetalLeaseView,
    bare_metal_executor_ref,
)

__all__ = [
    "BARE_METAL_EXECUTOR_KIND",
    "EXCLUSIVE_ALLOCATION_MODE",
    "PHYSICAL_HOST_ID_REF_KEY",
    "BareMetalLeaseCreate",
    "BareMetalLeaseView",
    "bare_metal_executor_ref",
]
