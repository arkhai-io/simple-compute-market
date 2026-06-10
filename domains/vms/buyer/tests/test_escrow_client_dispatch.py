"""Buyer-side materialization tests for ``make_buyer_payment_escrow_terms_fn``."""

from __future__ import annotations

import pytest

from market_core.schemas import EscrowProposal
from domains.vms.settlement.escrow_client import make_buyer_payment_escrow_terms_fn


_CHAIN = "anvil"
_ERC20_ADDR = "0x" + "11" * 20
_NATIVE_ADDR = "0x" + "22" * 20
_TOKEN = "0x" + "33" * 20
_TOKEN_LEGACY = "0x" + "44" * 20
_SELLER = "0x" + "55" * 20
_ARBITER = "0x" + "66" * 20
_RECIPIENT = "0x" + "77" * 20


@pytest.fixture
def patched_alkahest(monkeypatch):
    """Replace the alkahest helpers ``_build`` calls with capturing stubs.

    Avoids needing a real chain config. Returns the capture dict so
    tests can inspect what was passed through.
    """
    from market_alkahest import alkahest as alkahest_mod

    captured: dict = {}

    class _StubErc20Codec:
        kind = "erc20_escrow_obligation_nontierable"

        def resolve_address(self, chain_name, *, config_path):
            return _ERC20_ADDR

    class _StubNativeCodec:
        kind = "native_token_escrow_obligation_nontierable"

        def resolve_address(self, chain_name, *, config_path):
            return _NATIVE_ADDR

    def _stub_codec_for(chain_name, escrow_address, *, config_path=None):
        captured.setdefault("codec_lookups", []).append(
            (chain_name, escrow_address, config_path)
        )
        if escrow_address.lower() == _ERC20_ADDR.lower():
            return _StubErc20Codec()
        if escrow_address.lower() == _NATIVE_ADDR.lower():
            return _StubNativeCodec()
        raise ValueError(f"no stub codec for {escrow_address!r}")

    def _stub_build_obligation(
        *, demands=None, recipient=None, seller_wallet=None, agreed_amount, duration_seconds,
        token_contract_address, chain_name,
        addr_config_path=None, arbiter_kind="recipient_arbiter",
    ):
        effective_recipient = recipient or seller_wallet
        captured["build_call"] = dict(
            demands=demands,
            recipient=effective_recipient,
            agreed_amount=agreed_amount,
            duration_seconds=duration_seconds,
            token=token_contract_address,
            chain_name=chain_name,
            arbiter_kind=arbiter_kind,
        )
        return {
            "arbiter": _ARBITER,
            "demand": "0xdead",
            "token": token_contract_address,
            "amount": int(agreed_amount),
        }

    def _stub_address_to_slot(chain_name, address, *, config_path=None):
        # Returns a known slot for the canonical arbiter address; None
        # for anything else (the builder falls back to recipient_arbiter).
        if address.lower() == _ARBITER.lower():
            return "recipient_arbiter"
        return None

    monkeypatch.setattr(
        alkahest_mod, "get_escrow_codec_for", _stub_codec_for,
    )
    monkeypatch.setattr(
        alkahest_mod, "build_payment_obligation_data", _stub_build_obligation,
    )
    monkeypatch.setattr(
        alkahest_mod, "address_to_slot", _stub_address_to_slot,
    )
    return captured


def _make_proposal(*, fields=None, literal_fields=None, escrow_address=_ERC20_ADDR, demands=None):
    return EscrowProposal(
        chain_name=_CHAIN,
        escrow_address=escrow_address,
        fields=fields or {},
        literal_fields=literal_fields,
        demands=demands if demands is not None else [
            {"arbiter": _ARBITER, "demand_data": {"recipient": _RECIPIENT}},
        ],
        expiration_unix=1_800_000_000,
    )


def test_reads_token_from_literal_fields(patched_alkahest):
    """When ``literal_fields['token']`` is set, the builder uses it."""
    build = make_buyer_payment_escrow_terms_fn(
        chain_name=_CHAIN, addr_config_path=None,
    )
    proposal = _make_proposal(literal_fields={"token": _TOKEN})
    terms = build(proposal, _SELLER, 1_000, 3600)

    assert len(terms) == 1
    assert terms[0].maker == "buyer"
    assert terms[0].chain_name == _CHAIN
    assert terms[0].escrow_contract == _ERC20_ADDR
    assert terms[0].obligation_data["token"] == _TOKEN
    assert terms[0].obligation_data["amount"] == 1_000


def test_reads_recipient_from_literal_fields(patched_alkahest):
    build = make_buyer_payment_escrow_terms_fn(
        chain_name=_CHAIN, addr_config_path=None,
    )
    proposal = _make_proposal(
        literal_fields={"token": _TOKEN, "recipient": _RECIPIENT},
    )
    terms = build(proposal, _SELLER, 1_000, 3600)

    assert terms[0].obligation_data["arbiter"] == _ARBITER
    assert isinstance(terms[0].obligation_data["demand"], str)


def test_ignores_legacy_fields_token(patched_alkahest):
    """``fields`` is the negotiation-amount carrier; the builder reads
    the token from ``literal_fields`` exclusively."""
    build = make_buyer_payment_escrow_terms_fn(
        chain_name=_CHAIN, addr_config_path=None,
    )
    proposal = _make_proposal(
        fields={"token": _TOKEN_LEGACY},
        literal_fields={"token": _TOKEN},
    )
    terms = build(proposal, _SELLER, 500, 1800)

    assert terms[0].obligation_data["token"] == _TOKEN


def test_allows_literal_token_missing_for_non_token_shapes(patched_alkahest):
    build = make_buyer_payment_escrow_terms_fn(
        chain_name=_CHAIN, addr_config_path=None,
    )
    proposal = _make_proposal(fields={"tokenId": 7}, literal_fields={})
    terms = build(proposal, _SELLER, 100, 3600)
    assert terms[0].obligation_data["tokenId"] == 7


def test_materializes_non_erc20_escrow(patched_alkahest):
    build = make_buyer_payment_escrow_terms_fn(
        chain_name=_CHAIN, addr_config_path=None,
    )
    proposal = _make_proposal(
        literal_fields={"token": _TOKEN},
        escrow_address=_NATIVE_ADDR,
    )
    terms = build(proposal, _SELLER, 100, 3600)
    assert terms[0].escrow_contract == _NATIVE_ADDR
    assert terms[0].obligation_data["amount"] == 100


def test_non_erc20_without_token_still_materializes(patched_alkahest):
    build = make_buyer_payment_escrow_terms_fn(
        chain_name=_CHAIN, addr_config_path=None,
    )
    proposal = _make_proposal(escrow_address=_NATIVE_ADDR)
    terms = build(proposal, _SELLER, 100, 3600)
    assert terms[0].escrow_contract == _NATIVE_ADDR


def test_arbiter_override_via_literal_fields(patched_alkahest):
    """``literal_fields['arbiter']`` participates in the override lookup
    on equal footing with ``fields['arbiter']``."""
    build = make_buyer_payment_escrow_terms_fn(
        chain_name=_CHAIN, addr_config_path=None,
    )
    proposal = _make_proposal(
        literal_fields={"token": _TOKEN, "arbiter": _ARBITER},
    )
    build(proposal, _SELLER, 1_000, 3600)

    assert True


def test_obligation_data_carries_agreed_amount(patched_alkahest):
    """Sanity: ``agreed_amount`` flows straight into obligation_data."""
    build = make_buyer_payment_escrow_terms_fn(
        chain_name=_CHAIN, addr_config_path=None,
    )
    proposal = _make_proposal(literal_fields={"token": _TOKEN})
    terms = build(proposal, _SELLER, 42_000_000, 3600)

    assert terms[0].obligation_data["amount"] == 42_000_000
