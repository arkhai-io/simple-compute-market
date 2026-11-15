"""Re-anchoring a rate deal across a receipt identity rotation.

Unit tests over in-process doubles: the kit's payments engine signs the approval
receipt under one key, then rotates to another mid-deal, and persistence goes
through an in-memory evidence store that keeps the port's contract (idempotent
by evidence ID, changed bytes refused, insertion order kept). A consumer's
durable store and restart are not exercised here.
"""

from __future__ import annotations

import asyncio

import pytest
from market_deal_lifecycle.evidence import EvidenceRecord
from market_deal_lifecycle.operations import OperationKeys
from market_deal_lifecycle_contracts.models import Accepted, LifecycleCommand
from market_identity import Ed25519Signer

from market_arkhai_payments import (
    AnchoredDeal, ReanchoringRefused, ReceiptIdentity, derive_mandate, mandate_policy_for_agreement,
    reanchored_snapshot, reanchoring_evidence, record_reanchoring, retirement_inventory,
)
from market_arkhai_payments.fixtures.receipts import build_signed_receipt
from market_arkhai_payments.seller import PaymentSellerStage, ReceiptInvalid, ReceiptVerified

from payment_terms import SERVICE, agreement, config
from rate_terms import NOW, MemoryOperations, approved, rate_agreement, rate_data

# Public deterministic development keys; never use them on a public network.
NEXT = Ed25519Signer(b"\x09" * 32)
LATER = Ed25519Signer(b"\x0a" * 32)
# Both rotations fall inside the hour-long deal's term, so the engine records no
# terms end between them.
ROTATION = NOW + 10
RETIREMENT = NOW + 600


def overlap(**settings):
    """The operator's overlap: the new current key beside the old one, retiring at its date."""

    return config(service_identity=NEXT.identity, receipt_identities=[
        ReceiptIdentity(identity=NEXT.identity, valid_from=ROTATION),
        ReceiptIdentity(identity=SERVICE.identity, valid_until=RETIREMENT, retiring=True),
    ], **settings)


def retired():
    """After removal: only the new key is configured."""

    return config(service_identity=NEXT.identity)


def second_overlap():
    """The next rotation: LATER is current, NEXT retiring, the first key long gone."""

    return config(service_identity=LATER.identity, receipt_identities=[
        ReceiptIdentity(identity=LATER.identity, valid_from=RETIREMENT + 10),
        ReceiptIdentity(identity=NEXT.identity, valid_until=RETIREMENT + 600, retiring=True),
    ])


class MemoryEvidence:
    """An evidence store keeping the port's contract, in memory."""

    def __init__(self):
        self.items = {}

    async def put(self, negotiation_id, item):
        held = self.items.setdefault(negotiation_id, {})
        previous = held.get(item.evidence_id)
        if previous is not None:
            if previous.model_dump(exclude={"recorded_at"}) != item.model_dump(exclude={"recorded_at"}):
                raise ValueError("evidence ID retry changes content")
            return
        held[item.evidence_id] = item

    async def read(self, negotiation_id):
        return EvidenceRecord(negotiation_id=negotiation_id, commitments=[],
                              items=list(self.items.get(negotiation_id, {}).values()))


async def stop_rate(adapter, key):
    command = LifecycleCommand(negotiation_id=adapter.negotiation_id, kind="stop", operation_key=key,
                               payload={"part": "1"})
    return await adapter.submit(command, OperationKeys(adapter.negotiation_id, key, MemoryOperations()))


def rotate(fake, at=NOW + 20):
    fake.engine.signer = NEXT
    fake.observed_at = at


def test_a_current_key_snapshot_re_anchors_the_old_receipt_and_keeps_the_deal_verifying_after_removal():
    async def drive():
        raw, data, fake, adapter, evidence = approved()
        original = fake.receipt
        started = await adapter.start_billing(OperationKeys(adapter.negotiation_id, "billing", MemoryOperations()),
                                              evidence)
        assert isinstance(started.outcome, Accepted)

        rotate(fake)
        produced = PaymentSellerStage(overlap(), client_for_owner=fake).reanchoring_evidence_now(
            raw, data, receipt=original)
        assert produced.signer.identifier == NEXT.identity.identifier
        # The receipt is attested as signed: issuer, proof and bytes unchanged.
        assert produced.snapshot.snapshot.receipt == original
        assert produced.snapshot.snapshot.receipt.receipt.issuer.identifier == SERVICE.identity.identifier

        store = MemoryEvidence()
        await record_reanchoring(store, produced, recorded_at=NOW + 20)
        # A second put of the same evidence is idempotent.
        await record_reanchoring(store, produced, recorded_at=NOW + 21)
        anchor = reanchored_snapshot(await store.read(adapter.negotiation_id))
        assert anchor == produced.snapshot

        stage = PaymentSellerStage(retired(), client_for_owner=fake)
        unanchored = await stage.payment_adapter(raw, data).read()
        assert not isinstance(unanchored.outcome, Accepted)
        anchored = stage.payment_adapter(raw, data, anchor=anchor)
        assert isinstance((await anchored.read()).outcome, Accepted)
        # The stage's receipt check and stored-receipt revalidation hold through the anchor too.
        assert isinstance(stage.check_receipt_now(raw, data), ReceiptInvalid)
        assert isinstance(await stage.check_receipt(raw, data, anchor=anchor), ReceiptVerified)
        assert not stage.receipt_matches(original, raw, data)
        assert stage.receipt_matches(original, raw, data, anchor=anchor)
        # A monetary operation after the old key is gone is verified through the
        # anchor: the payee's stop, pending through its notice.
        assert isinstance(await stop_rate(anchored, "stop-after-removal"), Accepted)
        assert (await anchored.read()).parts[0].pending_stop is not None

        # Once the anchor's own signer is removed too, it attests nothing.
        later = config(service_identity=LATER.identity)
        fake.engine.signer = LATER
        assert not isinstance((await PaymentSellerStage(later, client_for_owner=fake).payment_adapter(
            raw, data, anchor=anchor).read()).outcome, Accepted)

    asyncio.run(drive())


def test_during_the_overlap_the_old_receipt_verifies_without_an_anchor():
    async def drive():
        raw, data, fake, _, _ = approved()
        rotate(fake)
        adapter = PaymentSellerStage(overlap(), client_for_owner=fake).payment_adapter(raw, data)
        assert isinstance((await adapter.read()).outcome, Accepted)

    asyncio.run(drive())


def test_a_retiring_key_cannot_re_anchor():
    raw, data, fake, _, _ = approved()
    # Still inside the old key's window, the engine has not rotated: its fresh
    # snapshot verifies, but under a retiring identity.
    fake.observed_at = NOW + 20
    with pytest.raises(ReanchoringRefused, match="no current identity"):
        PaymentSellerStage(overlap(), client_for_owner=fake).reanchoring_evidence_now(raw, data, receipt=fake.receipt)


def test_a_mode_change_cannot_re_anchor_a_running_deal():
    raw, data, fake, _, _ = approved()
    rotate(fake)
    with pytest.raises(ReanchoringRefused, match="mode change"):
        PaymentSellerStage(overlap(livemode=True), client_for_owner=fake).reanchoring_evidence_now(
            raw, data, receipt=fake.receipt)


def test_a_once_only_deal_is_not_re_anchored():
    raw, data, fake, _, _ = approved()
    rotate(fake)
    signed = fake.get_transaction(data.transaction_id)
    once = agreement()
    with pytest.raises(ReanchoringRefused, match="scoped to rate deals"):
        reanchoring_evidence(signed, overlap().receipt_trust, negotiation_id="neg-1", receipt=fake.receipt,
                             mandate=derive_mandate(once, mandate_policy_for_agreement(once, config())),
                             agreement_json=once, livemode=False)


def test_evidence_below_the_persisted_sequence_neither_re_anchors_nor_displaces_the_anchor():
    async def drive():
        raw, data, fake, adapter, evidence = approved()
        await adapter.start_billing(OperationKeys(adapter.negotiation_id, "billing", MemoryOperations()), evidence)
        rotate(fake)
        stage = PaymentSellerStage(overlap(), client_for_owner=fake)
        earlier = stage.reanchoring_evidence_now(raw, data, receipt=fake.receipt)
        fresh_stage = PaymentSellerStage(overlap(), client_for_owner=fake)
        await stop_rate(fresh_stage.payment_adapter(raw, data), "advance")
        newer = stage.reanchoring_evidence_now(raw, data, receipt=fake.receipt)
        assert newer.sequence > earlier.sequence

        store = MemoryEvidence()
        await record_reanchoring(store, newer, recorded_at=NOW + 30)
        with pytest.raises(ReanchoringRefused, match="older than the persisted anchor"):
            await record_reanchoring(store, earlier, recorded_at=NOW + 31)
        # A stale item that reached the store anyway does not displace the anchor.
        await store.put(adapter.negotiation_id, earlier.evidence_item(NOW + 31))
        assert reanchored_snapshot(await store.read(adapter.negotiation_id)) == newer.snapshot
        # Nor can a stale snapshot be offered as evidence against the anchor or the caller's floor.
        with pytest.raises(ReanchoringRefused, match="sequence floor"):
            reanchoring_evidence(earlier.snapshot, overlap().receipt_trust, negotiation_id=adapter.negotiation_id,
                                 receipt=fake.receipt, mandate=data.mandate, agreement_json=raw, livemode=False,
                                 anchor=newer.snapshot)
        with pytest.raises(ReanchoringRefused, match="sequence floor"):
            stage.reanchoring_evidence_now(raw, data, receipt=fake.receipt, minimum_sequence=newer.sequence + 1)

    asyncio.run(drive())


def test_an_idle_deal_re_anchors_again_at_the_next_rotation():
    async def drive():
        raw, data, fake, _, _ = approved()
        original = fake.receipt
        rotate(fake)
        store = MemoryEvidence()
        first = PaymentSellerStage(overlap(), client_for_owner=fake).reanchoring_evidence_now(
            raw, data, receipt=original)
        await record_reanchoring(store, first, recorded_at=NOW + 20)

        # No authority event since: the next rotation's snapshot has the same sequence.
        fake.engine.signer = LATER
        fake.observed_at = RETIREMENT + 20
        second = PaymentSellerStage(second_overlap(), client_for_owner=fake).reanchoring_evidence_now(
            raw, data, receipt=original, anchor=first.snapshot)
        assert second.sequence == first.sequence
        await record_reanchoring(store, second, recorded_at=RETIREMENT + 20)
        anchor = reanchored_snapshot(await store.read(data_negotiation(raw)))
        assert anchor == second.snapshot
        deal = AnchoredDeal(data_negotiation(raw), data.mandate, original, anchor)
        assert retirement_inventory([deal], NEXT.identity, livemode=False).removable
        # The first anchor, offered again, is older than the persisted one.
        with pytest.raises(ReanchoringRefused, match="older than the persisted anchor"):
            await record_reanchoring(store, first, recorded_at=RETIREMENT + 21)
        adapter = PaymentSellerStage(config(service_identity=LATER.identity), client_for_owner=fake).payment_adapter(
            raw, data, anchor=anchor)
        assert isinstance((await adapter.read()).outcome, Accepted)

    asyncio.run(drive())


def data_negotiation(raw):
    return str(raw["negotiation_id"])


def test_an_anchor_attests_only_its_own_deal_and_receipt():
    async def drive():
        raw, data, fake, _, _ = approved()
        other_raw, other_data, other_fake, _, _ = approved(setup=None)
        assert other_data.transaction_id != data.transaction_id
        rotate(fake)
        rotate(other_fake)
        trust = overlap().receipt_trust
        other = PaymentSellerStage(overlap(), client_for_owner=other_fake).reanchoring_evidence_now(
            other_raw, other_data, receipt=other_fake.receipt)
        signed = fake.get_transaction(data.transaction_id)
        # Another deal's anchor neither verifies this deal after removal nor re-anchors it.
        assert not PaymentSellerStage(retired(), client_for_owner=fake).payment_adapter(
            raw, data, anchor=other.snapshot).snapshots.verify(signed, 0)
        with pytest.raises(ReanchoringRefused, match="anchor attests another receipt"):
            reanchoring_evidence(signed, trust, negotiation_id=data_negotiation(raw), receipt=fake.receipt,
                                 mandate=data.mandate, agreement_json=raw, livemode=False, anchor=other.snapshot)
        # A store whose anchor attests another receipt refuses this deal's evidence,
        # observed later so its age is not what refuses it.
        fake.observed_at = NOW + 25
        mine = PaymentSellerStage(overlap(), client_for_owner=fake).reanchoring_evidence_now(
            raw, data, receipt=fake.receipt)
        store = MemoryEvidence()
        await store.put(data_negotiation(raw), other.evidence_item(NOW + 20))
        with pytest.raises(ReanchoringRefused, match="another receipt or mode"):
            await record_reanchoring(store, mine, recorded_at=NOW + 21)

    asyncio.run(drive())


def test_the_retirement_inventory_lists_every_deal_resting_on_the_retiring_key():
    rate = rate_data(rate_agreement()).mandate
    once_raw = agreement()
    once = derive_mandate(once_raw, mandate_policy_for_agreement(once_raw, config()))
    old_rate = build_signed_receipt(signer=SERVICE, mandate=rate, livemode=False)
    old_once = build_signed_receipt(signer=SERVICE, mandate=once, livemode=False)
    live_rate = build_signed_receipt(signer=SERVICE, mandate=rate, livemode=True)
    new_rate = build_signed_receipt(signer=NEXT, mandate=rate, livemode=False)
    raw, data, fake, _, _ = approved()
    rotate(fake)
    anchor = fake.get_transaction(data.transaction_id)

    deals = [
        AnchoredDeal("rate-on-old-key", rate, old_rate),
        AnchoredDeal("once-on-old-key", once, old_once),
        AnchoredDeal("rate-in-other-mode", rate, live_rate),
        AnchoredDeal("rate-re-anchored", data.mandate, fake.receipt, anchor),
        AnchoredDeal("rate-on-new-key", rate, new_rate),
    ]
    inventory = retirement_inventory(deals, SERVICE.identity, livemode=False)
    assert inventory.reanchor == ("rate-on-old-key",)
    assert inventory.must_drain == ("once-on-old-key", "rate-in-other-mode")
    assert not inventory.removable
    assert retirement_inventory(deals[3:], SERVICE.identity, livemode=False).removable
    # A key that anchors a re-anchored deal is itself a dependency when it retires.
    assert retirement_inventory(deals, NEXT.identity, livemode=False).reanchor == (
        "rate-re-anchored", "rate-on-new-key")
