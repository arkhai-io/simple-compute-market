"""Whether an accepted negotiation settles through Arkhai payments.

Kept free of storefront imports so the failure policy can ask without depending
on the payment settlement service, which depends on the domain runtime.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from market_arkhai_payments import ARKHAI_PAYMENTS_MECHANISM


def agreement_bytes(thread: Mapping[str, Any] | None) -> bytes | None:
    raw = thread.get("agreement_bytes") if thread else None
    if isinstance(raw, memoryview):
        raw = raw.tobytes()
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    return raw if isinstance(raw, bytes) else None


def selects_payments(thread: Mapping[str, Any] | None) -> bool:
    raw = agreement_bytes(thread)
    if raw is None:
        return False
    try:
        agreement = json.loads(raw)
    except ValueError:
        return False
    selected = agreement.get("settlement") if isinstance(agreement, dict) else None
    return isinstance(selected, dict) and selected.get("mechanism") == ARKHAI_PAYMENTS_MECHANISM


__all__ = ["agreement_bytes", "selects_payments"]
