#!/usr/bin/env python3
"""Shared production-facing role contracts for live artifacts and correlation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


SCHEMA_VERSION = "2026-03-23"

ROLE_KINDS = {
    "buyer",
    "seller",
    "platform",
    "support",
    "host",
}

DEFAULT_CORRELATION_KEYS = (
    "order_id",
    "job_id",
    "vm_target",
)


def build_artifact(
    *,
    role: str,
    action: str,
    status: str,
    request_url: str,
    auth_url: str,
    correlation: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the shared outer artifact shape for production-facing role flows."""
    if role not in ROLE_KINDS:
        raise ValueError(f"Unsupported role: {role}")
    created_at = datetime.now(timezone.utc).isoformat()
    normalized_correlation = {key: None for key in DEFAULT_CORRELATION_KEYS}
    if correlation:
        normalized_correlation.update(correlation)
    return {
        "schema_version": SCHEMA_VERSION,
        "role": role,
        "action": action,
        "status": status,
        "created_at": created_at,
        "endpoints": {
            "request_url": request_url,
            "auth_url": auth_url,
        },
        "correlation": normalized_correlation,
        "details": dict(details or {}),
    }
