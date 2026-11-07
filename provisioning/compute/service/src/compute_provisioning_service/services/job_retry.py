"""The deployment's job retry policy, read from the service's settings."""

from __future__ import annotations

from typing import Any

from compute_provisioning.jobs import JobRetryPolicy


def retry_policy_from(settings: Any) -> JobRetryPolicy:
    """The retry policy the service's settings declare for every job."""
    return JobRetryPolicy(
        default_max_retries=settings.default_max_retries,
        backoff_initial_seconds=settings.retry_backoff_initial_seconds,
        backoff_multiplier=settings.retry_backoff_multiplier,
        backoff_max_seconds=settings.retry_backoff_max_seconds,
    )


__all__ = ["retry_policy_from"]
