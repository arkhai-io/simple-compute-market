"""Accepted bare-metal recovery is independent of current admission policy."""

import base64
from types import SimpleNamespace

import httpx
import pytest
from arkhai_bare_metal_buyer.lifecycle import buyer_lifecycle
from market_arkhai_payments import ArkhaiPaymentsConfig, PaymentApproval, PaymentSettlementData
from market_deal_lifecycle.configuration import DisputeConfig
from market_deal_lifecycle_buyer import FileEvidenceStore
from market_identity import TrustedIdentitySet

from integration.test_payment_settlement_client import BUYER, SELLER, PAYER, PAYEE, SERVICE, harness, enabled


def context(h, tmp_path, *, approval=None, data=None):
    return buyer_lifecycle(
        agreement_bytes=base64.b64decode(h.opened["agreement_bytes"]),
        settlement_data=data or h.data.to_wire(), seller_url="http://test", signer=BUYER,
        publishers=TrustedIdentitySet(identities=(SELLER.identity,)),
        config=SimpleNamespace(arkhai_payments=None, payer_account=None, disputes=DisputeConfig(), timeout_seconds=30),
        approval=approval, store=FileEvidenceStore(tmp_path / "buyer-evidence"),
        transport=httpx.ASGITransport(app=h.app),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("configured", [True, False], ids=["changed-fee-policy", "removed-payment-policy"])
async def test_retained_mandate_allows_surrender_after_policy_rotation(harness, tmp_path, configured):
    h = harness
    h.serve()
    await h.settle()
    approval = PaymentApproval(ArkhaiPaymentsConfig(
        enabled=True, service_url="http://127.0.0.1:9", service_identity=SERVICE.identity,
        fee_bps=0, development_auth=True,
    ), PAYER, client_for_owner=h.payments) if configured else None
    async with context(h, tmp_path, approval=approval) as buyer:
        progress = await buyer.end_delivery(h.negotiation_id)
        assert progress.delivery.status == "accepted"
        assert progress.acknowledgement.selected_end.cause == "buyer_surrender"
        assert progress.payment.status == "rejected"  # Once-only surrender never invents a refund.
    assert len(h.provisioning.terminated) == 1
    async with context(h, tmp_path, approval=approval) as buyer:
        replay = await buyer.end_delivery(h.negotiation_id)
        assert replay.acknowledgement.receipt_at == progress.acknowledgement.receipt_at
    assert len(h.provisioning.terminated) == 1


@pytest.mark.asyncio
async def test_substituted_mandate_or_accepted_payer_is_rejected_before_peer_io(harness, tmp_path):
    h = harness
    agreement = h.runtime.lifecycle.agreement(h.negotiation_id)[0].model_dump(mode="json")
    agreement["amount"] = "200"
    other = PaymentSettlementData.for_agreement(agreement, ArkhaiPaymentsConfig(
        fee_bps=250, development_auth=True, service_url="http://127.0.0.1:9", service_identity=SERVICE.identity,
    ))
    with pytest.raises(ValueError, match="accepted Agreement"):
        async with context(h, tmp_path, data=other.to_wire()):
            raise AssertionError("substituted mandate yielded a buyer half")
    wrong = SimpleNamespace(payer_account=PAYEE)
    with pytest.raises(ValueError, match="another accepted payer"):
        async with context(h, tmp_path, approval=wrong):
            raise AssertionError("substituted payer yielded a buyer half")
    assert h.provisioning.begin_calls == []
