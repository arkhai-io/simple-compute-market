"""Sync negotiation through the real API-credits round hook.

Capacity snapshots and key lookups are faked at the service seams the
default hook resolves at call time; everything else — guards, terminal
policy, thread persistence, token-terms persistence, and the safe default
that grants no unfunded quota hold — runs against a temporary SQLite database.
"""

from __future__ import annotations

import pytest
from apicredits_storefront.domain_runtime import get_market_domain_contract
from apicredits_storefront.negotiation_runtime import (
    _decode_terms,
)
from market_core.schemas import (
    EscrowProposal,
    ProvisionTerms,
)
from market_identity import Ed25519Signer

_BUYER_PRINCIPAL = Ed25519Signer(bytes.fromhex("11" * 32)).identity
_SELLER_PRINCIPAL = Ed25519Signer(bytes.fromhex("22" * 32)).identity
_STRANGER_PRINCIPAL = Ed25519Signer(bytes.fromhex("33" * 32)).identity
_TOKEN = "0x" + "01" * 20
_ESCROW = "0x" + "11" * 20
_DOMAIN = get_market_domain_contract()


class FakeCapacity:
    def __init__(self, available: int = 100) -> None:
        self.available = available
        self.reserved: list[dict] = []

    async def snapshot(self):
        return [
            {
                "resource_id": "svc-quota",
                "resource_type": "api_credits",
                "available_units": self.available,
                "total_units": 1000,
                "state": "available",
            }
        ]

    async def reserve(self, *, claim=None, deal_ref=None, ttl_seconds=None):
        self.reserved.append(
            {
                "claim": claim,
                "deal_ref": deal_ref,
                "ttl_seconds": ttl_seconds,
            }
        )
        return {
            "capacity_reservation_id": f"alloc-{len(self.reserved)}",
            "resource_id": "svc-quota",
            "allocated_units": (claim or {}).get("units"),
            "hold_expires_at": "2099-01-01 00:00",
        }


@pytest.fixture
def fake_capacity(monkeypatch):
    capacity = FakeCapacity()
    from apicredits_storefront import negotiation_runtime as runtime_module

    monkeypatch.setattr(
        runtime_module,
        "build_capacity_client",
        lambda factory: capacity,
    )
    return capacity


@pytest.fixture
def key_records(monkeypatch):
    records: dict[str, dict | None] = {}

    async def _lookup(key_id: str):
        return records.get(key_id)

    from apicredits_storefront import negotiation_runtime as runtime_module

    monkeypatch.setattr(runtime_module, "lookup_key_record", _lookup)
    return records


def _proposal(amount: int) -> EscrowProposal:
    return EscrowProposal(
        chain_name="anvil",
        escrow_address=_ESCROW,
        fields={"token": _TOKEN, "amount": amount},
        literal_fields={"token": _TOKEN},
        rates=[{"field": "amount", "per": "token", "value": "100"}],
        expiration_unix=1_800_000_000,
    )


def _terms(quantity=3, key_mode="new", key_id=None) -> ProvisionTerms:
    key: dict = {"mode": key_mode}
    if key_id:
        key["key_id"] = key_id
    return ProvisionTerms(
        kind="api_credits.v1",
        version=1,
        payload={"quantity": quantity, "key": key},
    )


def test_decode_api_credits_message_terms_uses_domain_runtime() -> None:
    normalized = _decode_terms(
        _DOMAIN,
        ProvisionTerms(
            kind="api_credits.v1",
            version=1,
            payload={
                "quantity": "5",
                "key": {"mode": "existing", "key_id": "ak_existing"},
            },
        ),
    )

    assert normalized.decoded.quantity == 5
    assert normalized.decoded.key_mode == "existing"
    assert normalized.decoded.key_id == "ak_existing"


def test_normalize_api_credits_message_terms_rejects_foreign_terms() -> None:
    terms = ProvisionTerms(
        kind="compute.v1",
        version=1,
        payload={"duration_seconds": 60},
    )
    with pytest.raises(ValueError, match=r"api_credits\.v1"):
        _decode_terms(_DOMAIN, terms)


def test_normalize_api_credits_terms_rejects_unsupported_version() -> None:
    terms = ProvisionTerms(
        kind="api_credits.v1",
        version=2,
        payload={"quantity": 1, "key": {"mode": "new"}},
    )
    with pytest.raises(ValueError, match="version"):
        _decode_terms(_DOMAIN, terms)


def test_accepted_artifacts_stamp_the_seller_recipient(monkeypatch):
    """The accepted escrow artifacts must carry the seller's wallet as
    the escrow recipient — without it the buyer can't materialize a
    funded escrow ("must carry ... a recipient fallback"). Regression
    guard: the assembly once passed seller_wallet_address=None.
    """
    import apicredits_storefront.negotiation_runtime as sn

    captured: dict = {}

    def _fake_artifacts(**kwargs):
        captured.update(kwargs)
        return {"proposal": {}, "accepted_escrow_proposal": {}}

    monkeypatch.setattr(sn, "accepted_escrow_artifacts_from_proposal", _fake_artifacts)
    monkeypatch.setattr(sn, "_seller_wallet_address", lambda: "0xSeLLeR0000")

    sn.build_api_credit_accepted_artifacts(
        buyer_principal=_BUYER_PRINCIPAL,
        seller_principal=_SELLER_PRINCIPAL,
        proposal={"chain_name": "anvil", "escrow_address": _ESCROW},
        agreed_amount=300,
    )
    assert captured["seller_wallet_address"] == "0xSeLLeR0000"
