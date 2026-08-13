from __future__ import annotations

from types import SimpleNamespace

from src.hosted_real_stripe.lifecycle_bridge import LifecycleBridge


class _Marketplace:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def verify_composition(self):
        self.calls.append("verify_composition")
        return SimpleNamespace(authority_ready=True)

    def verify_runtime(self):
        self.calls.append("verify_runtime")
        return SimpleNamespace(wallet_free=True, runtime_ready=True, account_ready=True)

    def create_and_publish_listing(self):
        self.calls.append("publish")
        return SimpleNamespace(listing_id="listing-001")

    def discover_listing(self, listing_id: str):
        self.calls.append("discover")
        return listing_id

    def negotiate(self, listing_id: str):
        self.calls.append("negotiate")
        assert listing_id == "listing-001"
        return SimpleNamespace(
            negotiation_id="negotiation-001", accepted_mechanism="fiat.stripe.v1"
        )

    def materialize(self, negotiation_id: str):
        self.calls.append("materialize")
        assert negotiation_id == "negotiation-001"
        return SimpleNamespace(
            settlement_ref="settlement-001",
            operation_ref="market-operation-001",
            amount=1250,
            currency="usd",
            transfer_group="market-group-001",
            action=SimpleNamespace(
                kind="redirect",
                url="https://checkout.stripe.com/c/pay/private",
            ),
        )

    def wait_funded(self, settlement_ref: str):
        self.calls.append("wait_funded")
        return settlement_ref == "settlement-001"

    def complete_vm_fulfillment(self, settlement_ref: str):
        self.calls.append("fulfill")
        return SimpleNamespace(condition_decision="satisfied")

    def wait_terminal(self, settlement_ref: str):
        self.calls.append("wait_terminal")
        return SimpleNamespace(
            operation_ref="market-operation-001",
            effect_kind="transfer",
            marketplace_status="collected",
            authority_status="collected",
        )


def test_bridge_drives_public_marketplace_ports_without_test_provider_readiness() -> None:
    marketplace = _Marketplace()
    bridge = LifecycleBridge(marketplace)
    prepared = bridge.request({"action": "prepare_collection"})
    assert prepared["accepted_mechanism"] == "fiat.stripe.v1"
    assert prepared["condition_profile"] == "portable"
    operation_ref = prepared["operation_ref"]
    bridge.request({"action": "wait_authoritative_funding", "operation_ref": operation_ref})
    bridge.request(
        {"action": "complete_portable_vm_fulfillment", "operation_ref": operation_ref}
    )
    terminal = bridge.request(
        {"action": "wait_authoritative_collection", "operation_ref": operation_ref}
    )
    assert terminal == {
        "ok": True,
        "marketplace_state": "collected",
        "authority_state": "collected",
        "fulfillment_state": "fulfilled",
    }
    assert marketplace.calls == [
        "verify_composition",
        "verify_runtime",
        "publish",
        "discover",
        "negotiate",
        "materialize",
        "wait_funded",
        "fulfill",
        "wait_terminal",
    ]


def test_bridge_reports_refund_unavailable_without_substituting_another_provider() -> None:
    bridge = LifecycleBridge(_Marketplace())
    assert bridge.request({"action": "prepare_refund"}) == {
        "ok": True,
        "available": False,
    }
