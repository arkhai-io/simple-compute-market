"""The lease window the site recorded when a bare-metal deal's capacity was committed.

A lease begins at commit, so its window is the one commit returns: the first
commit records it, and a repeat returns the same window unchanged. The deal's
materialization, and through it the fulfillment request and the delivered
evidence's ``expires_at``, state that window rather than a clock of the
storefront's own.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _parsed(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def committed_lease_window(reservation: dict[str, Any] | None) -> tuple[datetime, datetime]:
    """The ``(start, end)`` a commit recorded; raises when it recorded none."""
    if not isinstance(reservation, dict):
        raise ValueError("the commit returned no reservation")
    start = _parsed(reservation.get("lease_start_utc"))
    end = _parsed(reservation.get("lease_end_utc"))
    if start is None or end is None:
        raise ValueError(
            f"reservation {reservation.get('capacity_reservation_id')!r}'s commit "
            "recorded no lease window"
        )
    return start, end


__all__ = ["committed_lease_window"]
