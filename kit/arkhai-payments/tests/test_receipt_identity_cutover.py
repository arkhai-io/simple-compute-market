"""A receipt identity change is a cutover: the configured identities decide what verifies.

Unit tests over the kit's in-process payments engine (``FakePaymentsClient``),
which signs the approval receipt under one key and is then switched to sign its
snapshots under another. Nothing re-anchors a deal: one approved under an
identity the configuration still lists verifies, and one approved under an
identity it has dropped does not, whatever key signed the fresh snapshot.
"""

from __future__ import annotations

import asyncio

from market_deal_lifecycle_contracts.models import Accepted
from market_identity import Ed25519Signer

from market_arkhai_payments import ReceiptIdentity
from market_arkhai_payments.adapter import pinned_snapshot_verifier
from market_arkhai_payments.fixtures.receipts import build_signed_receipt
from market_arkhai_payments.seller import PaymentSellerStage, ReceiptInvalid, ReceiptVerified

from payment_terms import SERVICE, config
from rate_terms import NOW, approved

# A public deterministic development key; never use it on a public network.
# SERVICE, the key the engine approves under, is one too (payment_terms).
NEXT = Ed25519Signer(b"\x09" * 32)
SWITCH = NOW + 10
RETIRING_UNTIL = NOW + 600


def overlap():
    """The moment of the switch: the new identity current, the old one retiring."""

    return config(service_identity=NEXT.identity, receipt_identities=[
        ReceiptIdentity(identity=NEXT.identity, valid_from=SWITCH),
        ReceiptIdentity(identity=SERVICE.identity, valid_until=RETIRING_UNTIL, retiring=True),
    ])


def switched():
    """After the cutover: only the new identity is configured."""

    return config(service_identity=NEXT.identity)


def new_key_snapshot():
    """A deal the old identity approved, read after the engine signs under the new key."""

    raw, data, fake, _, _ = approved()
    fake.engine.signer = NEXT
    fake.observed_at = NOW + 20
    signed = fake.get_transaction(data.transaction_id)
    assert signed.snapshot.issuer.identifier == NEXT.identity.identifier
    assert signed.snapshot.receipt.receipt.issuer.identifier == SERVICE.identity.identifier
    return raw, data, fake, signed


def test_a_current_key_snapshot_attests_a_retiring_identitys_receipt_within_its_window():
    raw, data, fake, signed = new_key_snapshot()
    assert pinned_snapshot_verifier(raw, data, overlap())(signed, 0)

    # The seller stage's verifier is the same binding: its receipt check and adapter accept it.
    stage = PaymentSellerStage(overlap(), client_for_owner=fake)
    assert isinstance(stage.check_receipt_now(raw, data), ReceiptVerified)
    assert isinstance(asyncio.run(stage.payment_adapter(raw, data).read()).outcome, Accepted)
    assert stage.receipt_matches(fake.receipt, raw, data)


def test_a_deal_approved_under_a_removed_identity_is_refused_although_a_new_key_snapshot_embeds_it():
    raw, data, fake, signed = new_key_snapshot()
    assert not pinned_snapshot_verifier(raw, data, switched())(signed, 0)

    stage = PaymentSellerStage(switched(), client_for_owner=fake)
    assert isinstance(stage.check_receipt_now(raw, data), ReceiptInvalid)
    assert not isinstance(asyncio.run(stage.payment_adapter(raw, data).read()).outcome, Accepted)
    assert not stage.receipt_matches(fake.receipt, raw, data)
    stored = build_signed_receipt(signer=SERVICE, mandate=data.mandate)
    assert not stage.receipt_matches(stored, raw, data)


def test_without_receipt_identities_the_service_identity_alone_is_trusted():
    raw, data, fake, _, _ = approved()
    trusted = config()
    assert [pin.identity for pin in trusted.receipt_trust] == [SERVICE.identity]
    assert pinned_snapshot_verifier(raw, data, trusted)(fake.get_transaction(data.transaction_id), 0)

    stage = PaymentSellerStage(trusted, client_for_owner=fake)
    assert stage.receipt_matches(build_signed_receipt(signer=SERVICE, mandate=data.mandate), raw, data)
    assert not stage.receipt_matches(build_signed_receipt(signer=NEXT, mandate=data.mandate), raw, data)

    # A snapshot under any other key is refused, though it embeds the trusted receipt.
    fake.engine.signer = NEXT
    fake.observed_at = NOW + 20
    assert not pinned_snapshot_verifier(raw, data, trusted)(fake.get_transaction(data.transaction_id), 0)
    assert isinstance(stage.check_receipt_now(raw, data), ReceiptInvalid)
