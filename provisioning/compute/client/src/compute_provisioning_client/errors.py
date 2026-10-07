"""The errors every compute provisioning client raises."""

from __future__ import annotations


class ComputeProvisioningError(Exception):
    """A refused or failed request; ``status_code`` is the HTTP status, if any."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ComputeProvisioningAuthenticationError(ComputeProvisioningError):
    """A request the caller may not sign, or a response without a valid authority proof."""


class ComputeProvisioningJobError(ComputeProvisioningError):
    """A polled job ended ``failed`` or ``cancelled``."""


class ComputeProvisioningTimeoutError(ComputeProvisioningError):
    """A polled job did not finish within the caller's deadline."""


__all__ = [
    "ComputeProvisioningAuthenticationError",
    "ComputeProvisioningError",
    "ComputeProvisioningJobError",
    "ComputeProvisioningTimeoutError",
]
