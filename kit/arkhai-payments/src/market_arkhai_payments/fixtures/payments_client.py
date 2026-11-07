"""An in-memory stand-in for ``PaymentsClient``, the code that wraps the payments service.

Integration tests inject it through a stage's or approval's ``client_for_owner``
factory, so everything above the HTTP boundary runs for real. One instance plays
the whole service for a test: it serves at most one receipt, records every call,
and can simulate an unreachable service or a service error code.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from market_identity import Ed25519Signer, Signer

from market_arkhai_payments.canonical import jcs_bytes, wire_json
from market_arkhai_payments.errors import (
    PaymentsAPIError,
    PaymentsProtocolError,
    PaymentsTransportError,
)
from market_arkhai_payments.fixtures.receipts import build_signed_receipt
from market_arkhai_payments.fixtures.authority import PaymentsAuthority, sign_snapshot
from market_arkhai_payments.mandates import PaymentsOptionParams
from market_arkhai_payments.models import (
    Balance,
    Mandate,
    SignedReceipt,
    SignedTransactionSnapshot,
    StoredDealAttachment,
    StoredEvent,
)

# Public deterministic development identity; never use on a public network.
_FIXTURE_SIGNER = Ed25519Signer(bytes([7]) * 32)


class FakePaymentsClient:
    """Records calls and answers like the payments service for one transaction."""

    def __init__(
        self,
        *,
        signer: Signer | None = None,
        observed_at: int = 1_800_000_100,
        livemode: bool = False,
    ) -> None:
        self.signer = signer
        self.observed_at = observed_at
        # The mode the receipts this fake signs on approval carry: false plays a
        # test or development payments service, true a live one.
        self.livemode = livemode
        self.receipt: SignedReceipt | None = None
        self.attachments: list[dict[str, Any]] = []
        self.owners: list[str] = []
        self.calls: list[tuple[str, Any]] = []
        self.unavailable = False
        self.attach_unavailable = False
        self.reverse_error: str | None = None
        self.read_error: tuple[int, str] | None = None
        self.reversed = False
        self.engine = PaymentsAuthority(
            signer=signer or _FIXTURE_SIGNER, clock=lambda: self.observed_at,
            livemode=livemode,
        )

    # ``client_for_owner`` factory and context-manager protocol -----------------

    def __call__(self, owner_account: str) -> FakePaymentsClient:
        self.owners.append(owner_account)
        return self

    def __enter__(self) -> FakePaymentsClient:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def close(self) -> None:
        return None

    # Test controls --------------------------------------------------------------

    def serve(
        self, receipt: SignedReceipt | None, *, mandate: Mandate | Mapping[str, Any] | None = None
    ) -> None:
        """Serve this receipt for whatever transaction is read, or none at all."""

        self.receipt = receipt
        if receipt is not None:
            self.engine.livemode = receipt.receipt.livemode
            if mandate is None:
                self.engine.load_receipt(receipt)
            else:
                self.engine.load(mandate, receipt)

    def count(self, name: str) -> int:
        return sum(1 for call, _ in self.calls if call == name)

    # PaymentsClient surface -----------------------------------------------------

    def approve(
        self, mandate: Mandate | Mapping[str, Any], *, agreement: dict[str, Any] | None = None
    ) -> SignedReceipt:
        self.calls.append(("approve", agreement is not None))
        self._require_available()
        if self.signer is None and self.receipt is None:
            raise AssertionError("FakePaymentsClient needs a signer or a served receipt to approve")
        if self.signer is not None:
            self.receipt = build_signed_receipt(
                signer=self.signer, mandate=mandate, livemode=self.livemode
            )
            # Approval fixtures seed an immutable receipt at their chosen instant;
            # admission/expiry/funding scenarios use the authority's approve directly.
            self.engine.load(mandate, self.receipt)
        if agreement is not None:
            self._store_attachment(agreement)
        assert self.receipt is not None
        return self.receipt

    def get_transaction(self, transaction: str) -> SignedTransactionSnapshot:
        self.calls.append(("get_transaction", transaction))
        self._require_available()
        if self.read_error is not None:
            raise PaymentsAPIError(*self.read_error)
        if self.receipt is None:
            raise PaymentsAPIError(404, "transaction_not_found")
        return self._snapshot(transaction)

    def get_balance(self, account: str) -> Balance:
        self.calls.append(("get_balance", account))
        self._require_available()
        return self.engine.balance(account)

    def poll(
        self, transaction: str, *, timeout: float = 300.0, interval: float = 1.0
    ) -> SignedTransactionSnapshot:
        del timeout, interval
        return self.get_transaction(transaction)

    def attach_agreement(
        self, transaction: str, agreement_json: dict[str, Any]
    ) -> StoredDealAttachment:
        self.calls.append(("attach_agreement", transaction))
        if self.attach_unavailable:
            raise PaymentsTransportError("payments service request failed")
        return self._store_attachment(agreement_json)

    def ensure_agreement_attached(
        self, transaction: str, agreement_json: dict[str, Any], option: PaymentsOptionParams
    ) -> StoredDealAttachment | None:
        self.calls.append(("ensure_agreement_attached", transaction))
        if self.attach_unavailable:
            raise PaymentsTransportError("payments service request failed")
        if not option.deposit_agreement:
            return None
        # Same rule as the real client: any attachment with another hash breaks
        # the service contract, wherever it appears.
        digest = hashlib.sha256(jcs_bytes(agreement_json)).hexdigest()
        if any(stored["sha256"] != digest for stored in self.attachments):
            raise PaymentsProtocolError("transaction contains an unexpected deal attachment")
        if self.attachments:
            return StoredDealAttachment.model_validate(self.attachments[0])
        return self._store_attachment(agreement_json)

    def reverse(self, transaction: str) -> StoredEvent:
        self.calls.append(("reverse", transaction))
        self._require_available()
        if self.reverse_error is not None:
            raise PaymentsAPIError(409, self.reverse_error)
        if self.receipt is None:
            raise PaymentsAPIError(404, "transaction_not_found")
        result = self.engine.submit(
            self.receipt.receipt.transaction.root,
            {"account": self.receipt.receipt.to.root, "requestId": f"reverse-{transaction}",
             "event": {"kind": "reverse"}},
        )
        self.reversed = True
        return StoredEvent.model_validate(result)

    def submit_event(
        self, transaction: str, event: Mapping[str, Any], *, request_id: str,
    ) -> StoredEvent:
        self.calls.append(("reverse" if event.get("kind") == "reverse" else "submit_event", transaction))
        self._require_available()
        if self.reverse_error is not None and event.get("kind") == "reverse":
            raise PaymentsAPIError(409, self.reverse_error)
        if self.receipt is None:
            raise PaymentsAPIError(404, "transaction_not_found")
        return self.submit(transaction, {
            "account": self.owners[-1] if self.owners else self.receipt.receipt.to.root,
            "requestId": request_id, "event": dict(event),
        })

    def submit(self, transaction: str, request: Mapping[str, Any]) -> StoredEvent:
        """Exercise the same authority command path used by an HTTP double."""

        self._require_available()
        return StoredEvent.model_validate(self.engine.submit(transaction, request))

    # Internals ------------------------------------------------------------------

    def _require_available(self) -> None:
        if self.unavailable:
            raise PaymentsTransportError("payments service request failed")

    def _store_attachment(self, agreement_json: dict[str, Any]) -> StoredDealAttachment:
        canonical = jcs_bytes(agreement_json)
        stored = {
            "kind": "deal",
            "content": agreement_json,
            "sha256": hashlib.sha256(canonical).hexdigest(),
            "name": "deal.json",
            "mediaType": "application/json",
            "size": len(canonical),
            "uploader": (
                self.receipt.receipt.to.root
                if self.receipt is not None
                else "00000000-0000-4000-8000-000000000000"
            ),
        }
        self.attachments.append(stored)
        return StoredDealAttachment.model_validate(stored)

    def _snapshot(self, transaction: str) -> SignedTransactionSnapshot:
        assert self.receipt is not None
        reference = self.receipt.receipt.transaction.root
        if self.reversed:
            # Explicit fault/state controls remain outside the authority algorithm.
            try:
                self.engine.submit(reference, {
                    "account": self.receipt.receipt.to.root,
                    "requestId": f"reverse-{transaction}", "event": {"kind": "reverse"},
                })
            except PaymentsAPIError as exc:
                if exc.code != "hold_not_reversible":
                    raise
        snapshot = self.engine.snapshot(reference)
        wire = snapshot.model_dump(mode="json", by_alias=True, exclude_none=True)
        wire["snapshot"]["attachments"] = list(self.attachments)
        # serve() may deliberately supply another transaction/mode/key as a fault.
        wire["snapshot"]["transaction"] = transaction
        return sign_snapshot(self.engine.signer, wire["snapshot"])


__all__ = ["FakePaymentsClient"]
