"""VM-domain heartbeat schema: what a compute-lease heartbeat attests.

The endpoint shell, replay protection, and persistence are core
mechanics (``core_storefront.heartbeats``); this module owns the
``vms.heartbeat.v1`` payload vocabulary — the first instantiation of
the design's "what a heartbeat attests ... is domain policy".

v1 attests exactly one thing: the buyer can reach their VM and is
satisfied ("healthy"). Evidence-bundle construction for oracle
arbitration builds on these records in work item I.5.
"""

from __future__ import annotations

from typing import Any

VM_HEARTBEAT_SCHEMA = "vms.heartbeat.v1"

_VALID_STATUSES = frozenset({"healthy", "degraded"})


class VmHeartbeatError(ValueError):
    """Payload doesn't conform to the VM heartbeat schema."""


def validate_vm_heartbeat_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Validate (and normalize) a ``vms.heartbeat.v1`` payload.

    An empty payload is accepted as a bare liveness ping and normalized
    to ``{"schema": ..., "status": "healthy"}`` — the signature itself
    is the attestation; v1 fields only qualify it.
    """
    data = dict(payload or {})
    schema = data.setdefault("schema", VM_HEARTBEAT_SCHEMA)
    if schema != VM_HEARTBEAT_SCHEMA:
        raise VmHeartbeatError(
            f"unsupported heartbeat schema {schema!r} (expected {VM_HEARTBEAT_SCHEMA!r})"
        )
    status = data.setdefault("status", "healthy")
    if status not in _VALID_STATUSES:
        raise VmHeartbeatError(
            f"unsupported heartbeat status {status!r} "
            f"(expected one of {sorted(_VALID_STATUSES)})"
        )
    return data
