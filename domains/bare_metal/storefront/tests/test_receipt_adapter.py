"""Bare-metal receipt claims are optional, selected-interface and credential independent."""

import asyncio
import sqlite3
from types import SimpleNamespace

import pytest
from market_arkhai_mediation.fixtures import market_signer
from market_arkhai_mediation.fixtures.authority import MediationContractFake
from market_deal_lifecycle.adapters import DeliveryEndIntent, DisputeAdapterTable, DisputeBinding, PaymentSelector
from market_deal_lifecycle.terms import DisputeAuthority
from market_identity import canonical_json
from arkhai_bare_metal_storefront.lifecycle import BareMetalLifecycle
from market_deal_servicing import SellerDeal


class Claims:
    def __init__(self):
        self.calls = []

    def sign_delivery_end(self, intent, signer):
        self.calls.append((intent, signer))
        return {"owned_by": "selected-adapter"}

    def verify_delivery_end(self, signed, intent):
        return True

    def concurrent_request(self, intent, signed):
        return None


def accepted():
    peer = MediationContractFake()
    filing = peer.data["filing"]["request"]
    signer = market_signer("ed25519")
    agreement = {**filing["agreement"], "seller": signer.identity.model_dump(mode="json")}
    binding = DisputeBinding("deal", filing["transaction"], DisputeAuthority.model_validate(peer.authority))
    return agreement, binding, signer

@pytest.mark.parametrize("installed", [False, True])
def test_receipt_claim_is_owned_by_the_resolved_adapter(installed, tmp_path):
    agreement, binding, signer = accepted()
    path = tmp_path / "seller.sqlite"
    deal = SellerDeal(negotiation_id="deal", commitment_ref=binding.commitment_ref, domain="fixture",
                      buyer=signer.identity, payment=PaymentSelector("fixture"), dispute=binding.authority)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE servicing_seller_deals (negotiation_id TEXT PRIMARY KEY, deal TEXT)")
        conn.execute("INSERT INTO servicing_seller_deals VALUES (?,?)", ("deal", deal.model_dump_json()))
    claims = Claims()
    table = DisputeAdapterTable([(binding.authority.interface, lambda _: claims)] if installed else [])
    lifecycle = SimpleNamespace(
        agreement=lambda _: (SimpleNamespace(settlement=SimpleNamespace(lifecycle=agreement["settlement"]["lifecycle"])), None),
        agreement_bytes=lambda _: canonical_json(agreement), runtime=SimpleNamespace(marketplace_signer=signer),
        path=path, seller=SimpleNamespace(disputes=table))
    with sqlite3.connect(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        result = BareMetalLifecycle.receipt_claim(lifecycle, "deal", 1800000000)
    assert result == ({"owned_by": "selected-adapter"} if installed else None)
    assert claims.calls == ([(DeliveryEndIntent(ended_at=1800000000, delivered=True, cause="payer"), signer)]
                            if installed else [])


def test_receipt_adapter_constructs_without_an_authority_credential():
    agreement, binding, signer = accepted()
    lifecycle = SimpleNamespace(agreement_bytes=lambda _: canonical_json(agreement), credential_available=lambda _: False,
        runtime=SimpleNamespace(settlement_composition=SimpleNamespace(disputes=SimpleNamespace(
            config=SimpleNamespace(credential_for=lambda _: None)))), clock=lambda: 1800001800)
    adapter = BareMetalLifecycle.dispute(lifecycle, binding)
    intent = DeliveryEndIntent(ended_at=1800000000, delivered=True, cause="payer")
    assert adapter.verify_delivery_end(adapter.sign_delivery_end(intent, signer), intent)
    assert asyncio.run(adapter.read()).outcome.status == "rejected"
