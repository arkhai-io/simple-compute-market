"""The payments kit's authority engine, the one the lanes' payments double serves,
on a clock a unit test moves, with one rate deal on the lane's terms.

The deal is a quarter-hour rate part at one period's price, held a week once
earned: the payer may stop it at once with its started period charged, a spot
seller on its notice with its period returned, and the dispute authority at once
through its ``chosen`` entry, which may also reverse and extend; the term ends
with its partial final period returned. Every account and key here is a
development fixture, never used on any network.
"""

from __future__ import annotations

from typing import Any

from market_arkhai_payments.fixtures import PaymentsAuthority
from market_identity import Ed25519Signer

# Development fixtures: two party accounts, the dispute authority's, and a
# receipt-signing seed.
PAYER = "11111111-1111-4111-8111-111111111111"
PAYEE = "22222222-2222-4222-8222-222222222222"
AUTHORITY = "33333333-3333-4333-8333-333333333333"
SIGNER = Ed25519Signer(bytes([9]) * 32)

T0 = 1_794_823_200
PERIOD_SECONDS = 900
PRICE = 250_000
#: Twelve whole periods and five minutes of a thirteenth, which the term end
#: returns.
TERM_END = T0 + 3 * 3600 + 300
ASSET = "USD/6"


class Engine:
    """The payments engine on a clock the test moves, and one rate deal on it."""

    def __init__(self, *, funds: int) -> None:
        self.now = T0
        self.authority = PaymentsAuthority(signer=SIGNER, clock=lambda: self.now)
        self.authority.fund(PAYER, ASSET, funds)

    def approve_and_start(self, *, payee_notice_seconds: int | None) -> str:
        stops = [{"account": PAYER, "notice": "PT0S", "partialPeriod": "charged"}]
        if payee_notice_seconds is not None:
            stops.append({"account": PAYEE, "notice": f"PT{payee_notice_seconds}S",
                          "partialPeriod": "returned"})
        stops.append({"account": AUTHORITY, "notice": "PT0S", "partialPeriod": "chosen"})
        mandate = {
            "from": PAYER, "to": PAYEE, "fee": {"bps": 250}, "nonce": "unit-rate",
            "deal": "ab" * 32, "expires": T0 + 300,
            "parts": [{
                "kind": "rate", "asset": ASSET, "amount": str(PRICE), "period": "PT15M",
                "reserveAhead": "PT15M", "hold": {"for": "P7D"},
                "end": {"at": TERM_END, "partialPeriod": "returned"},
                "authorities": {"stop": stops, "reverse": [PAYEE, AUTHORITY],
                                "extend": [AUTHORITY], "start": [PAYEE]},
                "maxHoldExtension": None,
            }],
        }
        transaction = self.authority.approve(mandate, account=PAYER).receipt.transaction.root
        self.submit(transaction, PAYEE, "start", {"kind": "start"})
        return transaction

    def submit(self, transaction: str, account: str, request_id: str,
               event: dict[str, Any]) -> dict[str, Any]:
        """One event from ``account``; the event payments stored."""
        return self.authority.submit(transaction, {"account": account, "requestId": request_id,
                                                   "event": event})

    def stop(self, transaction: str, account: str) -> None:
        self.submit(transaction, account, f"stop-{account}", {"kind": "stop"})

    def snapshot(self, transaction: str) -> dict[str, Any]:
        signed = self.authority.snapshot(transaction)
        return signed.snapshot.model_dump(mode="json", by_alias=True, exclude_none=True)
