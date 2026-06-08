"""Compatibility re-exports for VM capacity checks."""

from domains.vms.provisioning.capacity import (
    CapacityExceededError,
    CapacityViolation,
    check_slice_fits_host,
)

__all__ = [
    "CapacityExceededError",
    "CapacityViolation",
    "check_slice_fits_host",
]
