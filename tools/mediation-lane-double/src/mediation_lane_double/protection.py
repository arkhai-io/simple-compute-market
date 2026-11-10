"""Why a part payments will not extend is not held.

The payments snapshot states no reason: a part's status is ``held``,
``released``, ``reversed`` or ``settled``, and the engine reports ``settled`` alike
for a refunded part, a part both released and reversed, and a part where nothing
moved. So the reason is read from the part's signed amounts. Paid-out money comes
first because it is what mediation cannot recover, which a filer most needs to
know; then money returned to the payer, by reverse or refund; then nothing.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

NotHeldReason = Literal["paid_out", "reversed", "nothing_held"]


def not_held_reason(part: Mapping[str, Any]) -> NotHeldReason:
    """The contract's ``NotHeldPart.reason`` for one part of a signed snapshot."""

    if int(part["released"]) > 0:
        return "paid_out"
    if int(part["reversed"]) > 0 or int(part.get("refunded") or 0) > 0:
        return "reversed"
    return "nothing_held"
