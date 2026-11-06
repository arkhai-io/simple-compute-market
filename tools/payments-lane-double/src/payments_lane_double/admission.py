"""The service's admission policy for a new approval, which the engine does not hold.

The engine admits any mandate its caller funds: the in-process fake seeds its
approvals directly and has no policy of its own. The payments service refuses a
new approval, before it reserves funds, in this order; the double does the same.
A repeat of an approval already made never reaches these checks, so a payer
retrying a lost response gets its receipt back whatever has changed since.

The service's status for a code the engine itself never raises follows the
engine's own convention: a mandate the service will not accept is 422, an
account it does not know is 404.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from market_arkhai_payments.errors import PaymentsAPIError

from payments_lane_double.accounts import AccountDirectory


def admit(mandate: Mapping[str, Any], *, now: int, directory: AccountDirectory) -> None:
    """Refuse a new approval of ``mandate`` (its wire form) as the service would."""

    if now >= mandate["expires"]:
        raise PaymentsAPIError(409, "mandate_expired")
    if any(part["asset"] != directory.asset for part in mandate["parts"]):
        raise PaymentsAPIError(422, "unsupported_asset")
    if mandate["fee"]["bps"] != directory.fee_bps:
        raise PaymentsAPIError(422, "fee_mismatch")
    if not (directory.knows(mandate["from"]) and directory.knows(mandate["to"])):
        raise PaymentsAPIError(404, "account_not_found")
