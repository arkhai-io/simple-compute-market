"""Re-anchoring a running rate deal's approval trust during a receipt identity overlap.

A deal's approval receipt is signed by the payments service's key of the day.
When that key retires, a running rate deal moves its trust to a fresh snapshot
signed by the current key that embeds the original receipt exactly as signed:
the re-anchoring evidence. It is produced only through the shared snapshot
verifier, which binds the mandate, parties, mode and the caller's minimum
sequence; the original receipt's bytes are never rewritten.

The caller persists the evidence through its evidence store and passes the
deal's latest anchor back to the verifier, so the deal keeps verifying once the
retiring key is removed from configuration. The verifier trusts a supplied
anchor as it trusts the caller's minimum sequence: as the caller's own durable
record, here of a re-anchoring this module accepted, so only an anchor read
from that record may be supplied. Re-anchoring is scoped to rate
deals: a once-only deal that depends on a retiring key drains before the key is
removed, and a deal whose payment mode differs from the configured one cannot
re-anchor at all. See openspec/specs/settlement-servicing/spec.md, "Running
hosted rate deals can re-anchor during identity overlap".
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from market_deal_lifecycle.evidence import EvidenceRecord, EvidenceStore
from market_deal_lifecycle_contracts.models import EvidenceItem
from market_identity import Identity as MarketplaceIdentity

from .models import Identity, Mandate, SignedReceipt, SignedTransactionSnapshot
from .receipts import ReceiptIdentity, snapshot_signer, verify_snapshot

REANCHORING_EVIDENCE_KIND = "arkhai.payments.reanchoring-snapshot.v1"


class ReanchoringRefused(ValueError):
    """A snapshot cannot re-anchor the deal; the reason names what failed."""


@dataclass(frozen=True)
class ReanchoringEvidence:
    """A verified current-key snapshot attesting a deal's original receipt.

    Produced only by ``reanchoring_evidence``. The stored body is the snapshot's
    signed content exactly, so the snapshot read back still verifies.
    """

    negotiation_id: str
    snapshot: SignedTransactionSnapshot
    signer: Identity

    @property
    def sequence(self) -> int:
        return self.snapshot.snapshot.latestEventSequence or 0

    @property
    def order(self) -> tuple[int, int]:
        return _order(self.snapshot)

    @property
    def body(self) -> bytes:
        """The signed snapshot's wire JSON, every signed field as received."""

        return self.snapshot.model_dump_json(by_alias=True, exclude_unset=True).encode()

    @property
    def evidence_id(self) -> str:
        return "arkhai-payments-reanchor:" + hashlib.sha256(self.body).hexdigest()

    def evidence_item(self, recorded_at: int) -> EvidenceItem:
        return EvidenceItem(
            evidence_id=self.evidence_id, kind=REANCHORING_EVIDENCE_KIND, classification="independent",
            recorded_at=recorded_at, body=base64.b64encode(self.body),
            context={"transaction": self.snapshot.snapshot.transaction.root, "sequence": self.sequence,
                     "signer": self.signer.identifier},
        )


def reanchoring_evidence(
    signed: SignedTransactionSnapshot, trust: Sequence[ReceiptIdentity], *, negotiation_id: str,
    receipt: SignedReceipt, mandate: Mandate | Mapping[str, Any], agreement_json: Mapping[str, Any],
    livemode: bool, minimum_sequence: int = 0, anchor: SignedTransactionSnapshot | None = None,
) -> ReanchoringEvidence:
    """Verify a fresh snapshot as evidence re-anchoring a rate deal to a current key.

    ``receipt`` is the deal's original approval receipt, which the snapshot must
    embed exactly; ``anchor`` is the deal's latest persisted re-anchoring
    snapshot, if any, whose sequence the evidence may not fall below. Raises
    ``ReanchoringRefused`` for a once-only mandate, a mode change, a snapshot
    the shared verifier refuses, or one signed by no current identity.
    """

    expected = Mandate.model_validate(mandate)
    if not any(part.root.kind == "rate" for part in expected.parts):
        raise ReanchoringRefused("re-anchoring is scoped to rate deals; a once-only deal drains before its key retires")
    if receipt.receipt.livemode is not livemode:
        raise ReanchoringRefused("a payment mode change cannot re-anchor a running deal; it must drain")
    floor = minimum_sequence
    if anchor is not None:
        if anchor.snapshot.receipt != receipt:
            raise ReanchoringRefused("the persisted anchor attests another receipt")
        floor = max(floor, anchor.snapshot.latestEventSequence or 0)
    if signed.snapshot.receipt != receipt:
        raise ReanchoringRefused("the snapshot does not embed the deal's approval receipt as signed")
    if not verify_snapshot(signed, trust, mandate=expected, agreement_json=agreement_json, livemode=livemode,
                           minimum_sequence=floor, anchor=anchor):
        raise ReanchoringRefused(
            "the snapshot does not verify for this deal, mode, identity window and sequence floor")
    current = tuple(item for item in trust if not item.retiring)
    pin = snapshot_signer(signed, current)
    if pin is None:
        raise ReanchoringRefused("the snapshot is signed by no current identity; a retiring key cannot re-anchor")
    return ReanchoringEvidence(
        negotiation_id=negotiation_id, snapshot=signed,
        signer=Identity.model_validate(pin.identity.model_dump(mode="json")),
    )


def _order(signed: SignedTransactionSnapshot) -> tuple[int, int]:
    # An idle deal's snapshots at a later rotation carry the same sequence, so
    # the authority's observation instant orders them: the later re-anchoring wins.
    return (signed.snapshot.latestEventSequence or 0, signed.snapshot.observedAt)


def reanchored_snapshot(record: EvidenceRecord) -> SignedTransactionSnapshot | None:
    """The deal's current anchor: its latest re-anchoring snapshot, by sequence then observation.

    An earlier snapshot stored later never displaces it, so a restart cannot
    roll the anchor back.
    """

    held = [SignedTransactionSnapshot.model_validate_json(item.body)
            for item in record.items if item.kind == REANCHORING_EVIDENCE_KIND]
    return max(held, key=_order, default=None)


async def record_reanchoring(
    store: EvidenceStore, evidence: ReanchoringEvidence, *, recorded_at: int,
) -> SignedTransactionSnapshot:
    """Persist re-anchoring evidence beside the deal's original evidence, and return the anchor.

    The original receipt and every earlier item stay as stored. Evidence older
    than the persisted anchor, by sequence then observation, or attesting
    another receipt or mode, is refused rather than stored.
    """

    current = reanchored_snapshot(await store.read(evidence.negotiation_id))
    if current is not None:
        if evidence.order < _order(current):
            raise ReanchoringRefused("re-anchoring evidence is older than the persisted anchor")
        if (current.snapshot.receipt != evidence.snapshot.snapshot.receipt
                or current.snapshot.livemode is not evidence.snapshot.snapshot.livemode):
            raise ReanchoringRefused("re-anchoring evidence attests another receipt or mode than the persisted anchor")
    await store.put(evidence.negotiation_id, evidence.evidence_item(recorded_at))
    return evidence.snapshot


@dataclass(frozen=True)
class AnchoredDeal:
    """A hosted deal still serviced against the payment authority, and what its trust rests on."""

    negotiation_id: str
    mandate: Mandate
    receipt: SignedReceipt
    anchor: SignedTransactionSnapshot | None = None

    @property
    def rate(self) -> bool:
        return any(part.root.kind == "rate" for part in self.mandate.parts)

    @property
    def trusted_signer(self) -> Identity:
        """The key the deal's approval trust rests on: its anchor's signer, else its receipt's issuer."""

        return self.anchor.snapshot.issuer if self.anchor is not None else self.receipt.receipt.issuer


@dataclass(frozen=True)
class RetirementInventory:
    """Every hosted deal that keeps a retiring key from being removed, and what it needs."""

    retiring: MarketplaceIdentity
    reanchor: tuple[str, ...]
    must_drain: tuple[str, ...]

    @property
    def removable(self) -> bool:
        return not self.reanchor and not self.must_drain


def retirement_inventory(
    deals: Iterable[AnchoredDeal], retiring: MarketplaceIdentity, *, livemode: bool,
) -> RetirementInventory:
    """Inventory the deals whose trust rests on ``retiring``.

    A running rate deal in the configured mode needs re-anchoring; a once-only
    deal, or a deal in the other mode, must drain. The key is removable only
    when neither list holds a deal. ``deals`` are every hosted deal still
    serviced against the payment authority, once-only deals included.
    """

    reanchor: list[str] = []
    must_drain: list[str] = []
    for deal in deals:
        signer = deal.trusted_signer
        if (signer.scheme, signer.identifier) != (retiring.scheme.value, retiring.identifier):
            continue
        if deal.rate and deal.receipt.receipt.livemode is livemode:
            reanchor.append(deal.negotiation_id)
        else:
            must_drain.append(deal.negotiation_id)
    return RetirementInventory(retiring=retiring, reanchor=tuple(reanchor), must_drain=tuple(must_drain))


__all__ = [
    "REANCHORING_EVIDENCE_KIND",
    "AnchoredDeal",
    "ReanchoringEvidence",
    "ReanchoringRefused",
    "RetirementInventory",
    "reanchored_snapshot",
    "reanchoring_evidence",
    "record_reanchoring",
    "retirement_inventory",
]
