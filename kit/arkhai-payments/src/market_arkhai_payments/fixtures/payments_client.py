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

from market_identity import Signer

from market_arkhai_payments.canonical import jcs_bytes
from market_arkhai_payments.errors import PaymentsAPIError, PaymentsTransportError
from market_arkhai_payments.fixtures.receipts import build_signed_receipt
from market_arkhai_payments.mandates import PaymentsOptionParams
from market_arkhai_payments.models import (
    Mandate,
    SignedReceipt,
    SignedTransactionSnapshot,
    StoredDealAttachment,
    StoredEvent,
)

# Sellers trust only the independently signed receipt inside a snapshot, so the
# snapshot's own proof is a structurally valid placeholder.
_PLACEHOLDER_PROOF = {"scheme": "ed25519", "value": "A" * 86}


class FakePaymentsClient:
    """Records calls and answers like the payments service for one transaction."""

    def __init__(self, *, signer: Signer | None = None, observed_at: int = 1_800_000_100) -> None:
        self.signer = signer
        self.observed_at = observed_at
        self.receipt: SignedReceipt | None = None
        self.attachments: list[dict[str, Any]] = []
        self.owners: list[str] = []
        self.calls: list[tuple[str, Any]] = []
        self.unavailable = False
        self.attach_unavailable = False
        self.reverse_error: str | None = None
        self.reversed = False

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

    def serve(self, receipt: SignedReceipt | None) -> None:
        """Serve this receipt for whatever transaction is read, or none at all."""

        self.receipt = receipt

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
            self.receipt = build_signed_receipt(signer=self.signer, mandate=mandate)
        if agreement is not None:
            self._store_attachment(agreement)
        assert self.receipt is not None
        return self.receipt

    def get_transaction(self, transaction: str) -> SignedTransactionSnapshot:
        self.calls.append(("get_transaction", transaction))
        self._require_available()
        if self.receipt is None:
            raise PaymentsAPIError(404, "transaction_not_found")
        return self._snapshot(transaction)

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
        digest = hashlib.sha256(jcs_bytes(agreement_json)).hexdigest()
        for stored in self.attachments:
            if stored["sha256"] == digest:
                return StoredDealAttachment.model_validate(stored)
        return self._store_attachment(agreement_json)

    def reverse(self, transaction: str) -> StoredEvent:
        self.calls.append(("reverse", transaction))
        self._require_available()
        if self.reverse_error is not None:
            raise PaymentsAPIError(409, self.reverse_error)
        if self.receipt is None:
            raise PaymentsAPIError(404, "transaction_not_found")
        self.reversed = True
        return StoredEvent.model_validate(
            {
                "account": self.receipt.receipt.to.root,
                "requestId": f"reverse-{transaction}",
                "event": {"kind": "reverse"},
                "receivedAt": self.observed_at,
            }
        )

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
        receipt = self.receipt.model_dump(mode="json", by_alias=True, exclude_none=True)
        state = "reversed" if self.reversed else "held"
        parts = [
            {
                "part": index,
                "asset": part["asset"],
                "gross": part["gross"],
                "held": "0" if self.reversed else part["net"],
                "released": "0",
                "reversed": part["gross"] if self.reversed else "0",
                "feePaid": "0" if self.reversed else part["fee"],
                "hold": part["hold"],
                "status": state,
            }
            for index, part in enumerate(receipt["receipt"]["parts"])
        ]
        return SignedTransactionSnapshot.model_validate(
            {
                "snapshot": {
                    "transaction": transaction,
                    "receipt": receipt,
                    "observedAt": self.observed_at,
                    "parts": parts,
                    "events": [],
                    "attachments": list(self.attachments),
                    "issuer": receipt["receipt"]["issuer"],
                },
                "proof": _PLACEHOLDER_PROOF,
            }
        )


__all__ = ["FakePaymentsClient"]
