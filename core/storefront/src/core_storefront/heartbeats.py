"""Deal heartbeat validation and principal-bound durable evidence."""

from __future__ import annotations

import time as _time
from typing import Any, Protocol, runtime_checkable

from market_identity import Identity

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
    buyer_principal: Identity,
    seller_principal: Identity,
    sent_at_unix: float,
    payload: dict[str, Any] | None = None,
    now: float | None = None,
    max_skew_seconds: float = DEFAULT_MAX_SKEW_SECONDS,
) -> dict[str, Any]:
    """Validate and persist a monotonic heartbeat for the exact deal parties."""

    now_f = _time.time() if now is None else now
    if abs(now_f - sent_at_unix) > max_skew_seconds:
        raise HeartbeatError(
            f"heartbeat sent_at {sent_at_unix} outside ±{max_skew_seconds}s window",
            status_code=400,
        )

    last = await store.latest_heartbeat(deal_ref)
    if last is not None:
        if last.get("buyer_principal") != buyer_principal.model_dump(mode="json"):
            raise HeartbeatError("heartbeat buyer principal does not match deal history", status_code=403)
        if last.get("seller_principal") != seller_principal.model_dump(mode="json"):
            raise HeartbeatError("heartbeat seller principal does not match deal history", status_code=403)
        if sent_at_unix <= float(last["sent_at_unix"]):
            raise HeartbeatError(
                "heartbeat is not newer than the last recorded one",
                status_code=409,
            )

    record = {
        "deal_ref": deal_ref,
        "buyer_principal": buyer_principal.model_dump(mode="json"),
        "seller_principal": seller_principal.model_dump(mode="json"),
        "sent_at_unix": float(sent_at_unix),
        "payload": dict(payload or {}),
        "received_at_unix": now_f,
    }
    await store.insert_heartbeat(record)
    return record


def heartbeat_gap_seconds(
    last: dict[str, Any] | None,
    *,
    now: float | None = None,
) -> float | None:
    """Return seconds since the deal's last heartbeat, or ``None`` if absent."""

    if last is None:
        return None
    now_f = _time.time() if now is None else now
    return now_f - float(last["sent_at_unix"])
