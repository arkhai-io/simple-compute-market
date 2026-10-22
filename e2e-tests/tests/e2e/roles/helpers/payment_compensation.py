"""Compensation for a payment purchase a scenario left outstanding.

A payment scenario that fails part-way can leave an approved payment held at
the payments service and a host delivered at the site. Its cleanup finds the
purchase in the buyer's run log — which records each step as it happens, so a
purchase is found even when the buy command failed or timed out — refunds an
approved payment, then releases a host it finds; a host it cannot read or tear
down is reported, not released. Refund and release are idempotent, so they need
not know how far the scenario's stages got.

The buyer records a payment approved before the seller has verified its
receipt, and the seller refuses to refund a payment it has not verified. A
refusal that may clear is retried for a bounded window, so a receipt that is
merely late is still refunded; a refund that still fails is reported by the
purchase's negotiation and transaction, for an operator to reverse any hold.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from core_buyer.negotiation_client import AuthenticatedHTTPError
from storefront_client import StorefrontClientError

from tests.e2e.roles.helpers.cleanup import CleanupStep


@dataclass(frozen=True)
class Purchase:
    """A purchase's identifiers, as far as its run log recorded them."""

    negotiation_id: str | None = None
    transaction_id: str | None = None


def purchase_from_run_logs(run_dir: Path) -> Purchase:
    """Read the purchase's negotiation and approved payment from a run directory.

    Takes the last agreement and approval recorded across the directory's run
    logs, which is the purchase's while the directory holds one buy run. A line
    a crash left half-written is skipped.
    """

    negotiation_id = transaction_id = None
    for path in sorted(run_dir.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("event") == "agreement_accepted":
                negotiation_id = event.get("negotiation_id")
            elif event.get("event") == "payment_approved":
                transaction_id = event.get("transaction_id")
    return Purchase(negotiation_id=negotiation_id, transaction_id=transaction_id)


# The bare-metal status route's answer for a purchase with no fulfillment record
# whose payment it has not verified: a pending receipt, or a refund of a deal never
# delivered. Its other 409s describe a reserved or delivered host it cannot read.
# The route gives no structured reason, so this detail stands in for one; it is
# reliable while settlement records are intact, since a started delivery admits
# every status such a record can hold, but it is not a proof of absence. The
# storefront's own tests pin the fulfillment service's refusal, which the route
# forwards as its detail verbatim.
_UNVERIFIED_WITHOUT_FULFILLMENT = "bare-metal settlement is not authoritatively verified"


def fulfillment_or_none(
    read: Callable[[str], Mapping[str, Any]], negotiation_id: str
) -> Mapping[str, Any] | None:
    """A bare-metal purchase's fulfillment, or ``None`` when no host was delivered.

    "Not found" (404) means no fulfillment, and so does the 409 the route answers
    for a payment it has not verified and no fulfillment record. The route gives
    no structured reason, so that 409 is told apart by its signed detail; any
    other failure, including another 409, is raised, so a changed wording reports
    a failed read rather than hide a host.
    """

    try:
        return read(negotiation_id)
    except AuthenticatedHTTPError as error:
        if error.status_code == 404:
            return None
        detail = error.body.get("detail") if isinstance(error.body, dict) else None
        if error.status_code == 409 and detail == _UNVERIFIED_WITHOUT_FULFILLMENT:
            return None
        raise


def refund_may_clear(error: Exception) -> bool:
    """Whether a refund failure may clear on retry.

    The seller refuses a payment it has not yet verified (409) and answers 503
    while the payments service is unavailable; a storefront that cannot be
    reached may be reachable shortly. A 409 can also be final, so the retry is
    bounded.
    """

    if isinstance(error, StorefrontClientError):
        return error.status_code in (409, 503)
    return isinstance(error, httpx.TransportError)


class UnresolvedPayment(AssertionError):
    """An approved payment cleanup could not refund."""

    def __init__(self, purchase: Purchase, cause: BaseException) -> None:
        self.purchase = purchase
        super().__init__(
            f"payment {purchase.transaction_id} for negotiation "
            f"{purchase.negotiation_id} could not be refunded ({cause!r}); "
            "an operator reverses any hold that remains, and releases any host "
            "the seller delivers for it once its receipt verifies"
        )


@dataclass
class PurchaseCompensation:
    """The cleanup steps that refund and release one outstanding purchase.

    ``status`` reads the purchase's fulfillment, returning ``None`` when there is
    none (``fulfillment_or_none``); ``refund`` refunds it as the seller;
    ``release`` tears down a fulfillment and waits for its capacity to return;
    ``retryable`` says whether a refund failure may yet clear (``refund_may_clear``).
    """

    run_dir: Path
    status: Callable[[str], Mapping[str, Any] | None]
    refund: Callable[[str], object]
    release: Callable[[str, Mapping[str, Any]], object]
    retryable: Callable[[Exception], bool]
    refund_window: float = 60.0
    retry_interval: float = 2.0
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep

    def steps(self, *, settled: bool) -> list[CleanupStep]:
        """The steps for ``run_cleanup``; none once the scenario settled the deal itself."""

        if settled:
            return []
        found: dict[str, Any] = {"purchase": Purchase()}

        def find() -> None:
            found["purchase"] = purchase_from_run_logs(self.run_dir)

        def refund() -> None:
            purchase = found["purchase"]
            if not purchase.transaction_id:
                return
            started = self.clock()
            while True:
                try:
                    self.refund(purchase.negotiation_id)
                    return
                except Exception as error:
                    if not self.retryable(error) or (
                        self.clock() - started >= self.refund_window
                    ):
                        raise UnresolvedPayment(purchase, error) from error
                self.sleep(self.retry_interval)

        def release() -> None:
            purchase = found["purchase"]
            if not purchase.transaction_id:
                return  # without an approved payment no host can have been delivered
            # Read after the refund: delivery and a refund are serialised, and a
            # recorded refund stops any later delivery start, so after a refund
            # this read is final, whichever of the two the seller recorded first.
            # After a failed refund it reads only what has happened so far.
            status = self.status(purchase.negotiation_id)
            if status is not None and status.get("state") != "released":
                self.release(purchase.negotiation_id, status)

        return [
            ("find the outstanding purchase", find),
            ("refund the outstanding purchase", refund),
            ("release the outstanding purchase's host", release),
        ]


__all__ = [
    "Purchase",
    "PurchaseCompensation",
    "UnresolvedPayment",
    "fulfillment_or_none",
    "purchase_from_run_logs",
    "refund_may_clear",
]
