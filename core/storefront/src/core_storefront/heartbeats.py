"""Deal heartbeat mechanics: validation, replay protection, persistence.

Work item I.4 of ``docs/development/design-settlement-lifecycle-and-
capacity.md``. Heartbeats are off-chain signed messages from buyer to
seller attesting "the service is healthy, keep collecting": the buyer
emits them while satisfied, the seller persists them as evidence for
oracle bundles, and missing heartbeats are how a deal ends early.

Core owns the mechanics only — monotonicity/replay protection, skew
bounds, persistence protocol. Request *authentication* is the existing
signed-request verification (``core_storefront.auth``: the signature
covers ``deal_heartbeat:<deal_ref>:<sent_at>``, so a replayed request
re-presents an old ``sent_at`` and fails the monotonic check here).
What a heartbeat's payload attests and how evidence bundles are built
is domain policy (work item I.5).
"""

from __future__ import annotations

import time as _time
from typing import Any, Protocol, runtime_checkable

DEFAULT_MAX_SKEW_SECONDS = 300.0


class HeartbeatError(Exception):
    """Validation failure; ``status_code`` maps onto the HTTP layer."""

    def __init__(self, detail: str, *, status_code: int = 400) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


@runtime_checkable
class HeartbeatStore(Protocol):
    """Persistence the composition root supplies."""

    async def latest_heartbeat(self, deal_ref: str) -> dict[str, Any] | None: ...

    async def insert_heartbeat(self, record: dict[str, Any]) -> None: ...


async def record_heartbeat(
    store: HeartbeatStore,
    *,
    deal_ref: str,
    signer: str,
    sent_at_unix: float,
    payload: dict[str, Any] | None = None,
    now: float | None = None,
    max_skew_seconds: float = DEFAULT_MAX_SKEW_SECONDS,
) -> dict[str, Any]:
    """Validate and persist one heartbeat; returns the stored record.

    Rejections (``HeartbeatError``):
      * ``sent_at_unix`` outside ``±max_skew_seconds`` of now — stale or
        clock-skewed beyond tolerance (409 for stale-vs-last, 400 here).
      * ``sent_at_unix`` not strictly newer than the deal's last recorded
        heartbeat — replayed or out-of-order delivery (409).

    Monotonicity is per ``deal_ref`` and keyed on the *claimed* send
    time, which is exactly what the request signature covers — so a
    captured request cannot be replayed once any newer heartbeat lands.
    """
    now_f = _time.time() if now is None else now
    if abs(now_f - sent_at_unix) > max_skew_seconds:
        raise HeartbeatError(
            f"heartbeat sent_at {sent_at_unix} outside ±{max_skew_seconds}s window",
            status_code=400,
        )

    last = await store.latest_heartbeat(deal_ref)
    if last is not None and sent_at_unix <= float(last["sent_at_unix"]):
        raise HeartbeatError(
            "heartbeat is not newer than the last recorded one (replay?)",
            status_code=409,
        )

    record = {
        "deal_ref": deal_ref,
        "signer": signer,
        "sent_at_unix": float(sent_at_unix),
        "payload": dict(payload or {}),
        "received_at_unix": now_f,
    }
    await store.insert_heartbeat(record)
    return record


def heartbeat_gap_seconds(
    last: dict[str, Any] | None, *, now: float | None = None
) -> float | None:
    """Seconds since the deal's last heartbeat (None = never heartbeat).

    The claims/lifecycle side's primitive: policies compare this against
    the agreed cadence to decide "the buyer has gone quiet".
    """
    if last is None:
        return None
    now_f = _time.time() if now is None else now
    return now_f - float(last["sent_at_unix"])
