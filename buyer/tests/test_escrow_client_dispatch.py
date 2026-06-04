"""Buyer-side dispatch tests for ``make_buyer_payment_escrow_terms_fn``.

The builder reads the proposal's token from ``literal_fields`` and
refuses to build for non-ERC20 escrow contracts with
``NotImplementedError``.
"""

from __future__ import annotations

import pytest

from service.schemas import EscrowProposal
from market_buyer.escrow_client import make_buyer_payment_escrow_terms_fn


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
    from service.clients import alkahest as alkahest_mod

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


def _make_proposal(*, fields=None, literal_fields=None, escrow_address=_ERC20_ADDR):
    return EscrowProposal(
        chain_name=_CHAIN,
        escrow_address=escrow_address,
        fields=fields or {},
        literal_fields=literal_fields,
        expiration_unix=1_800_000_000,
    )


def test_reads_token_from_literal_fields(patched_alkahest):
    """When ``literal_fields['token']`` is set, the builder uses it."""
    build = make_buyer_payment_escrow_terms_fn(
        chain_name=_CHAIN, addr_config_path=None,
    )
    proposal = _make_proposal(literal_fields={"token": _TOKEN})
    terms = build(proposal, _SELLER, 1_000, 3600)

    assert patched_alkahest["build_call"]["token"] == _TOKEN
    assert len(terms) == 1
    assert terms[0].maker == "buyer"
    assert terms[0].obligation_data["token"] == _TOKEN
    assert terms[0].obligation_data["amount"] == 1_000


def test_reads_recipient_from_literal_fields(patched_alkahest):
    build = make_buyer_payment_escrow_terms_fn(
        chain_name=_CHAIN, addr_config_path=None,
    )
    proposal = _make_proposal(
        literal_fields={"token": _TOKEN, "recipient": _RECIPIENT},
    )
    build(proposal, _SELLER, 1_000, 3600)

    assert patched_alkahest["build_call"]["recipient"] == _RECIPIENT


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
    build(proposal, _SELLER, 500, 1800)

    assert patched_alkahest["build_call"]["token"] == _TOKEN


def test_raises_when_literal_fields_token_missing(patched_alkahest):
    build = make_buyer_payment_escrow_terms_fn(
        chain_name=_CHAIN, addr_config_path=None,
    )
    proposal = _make_proposal(fields={"token": _TOKEN_LEGACY}, literal_fields={})
    with pytest.raises(ValueError, match="token missing"):
        build(proposal, _SELLER, 100, 3600)


def test_raises_not_implemented_for_non_erc20_escrow(patched_alkahest):
    """Phase 5 ships ERC20 only; other kinds raise loudly with the address."""
    build = make_buyer_payment_escrow_terms_fn(
        chain_name=_CHAIN, addr_config_path=None,
    )
    proposal = _make_proposal(
        literal_fields={"token": _TOKEN},
        escrow_address=_NATIVE_ADDR,
    )
    with pytest.raises(NotImplementedError) as exc_info:
        build(proposal, _SELLER, 100, 3600)
    msg = str(exc_info.value)
    assert "native_token_escrow_obligation_nontierable" in msg
    assert _NATIVE_ADDR in msg
    assert _CHAIN in msg


def test_dispatch_gate_runs_before_token_validation(patched_alkahest):
    """If the escrow is non-ERC20, NotImplementedError fires even when the
    token is missing — codec lookup is the first gate."""
    build = make_buyer_payment_escrow_terms_fn(
        chain_name=_CHAIN, addr_config_path=None,
    )
    proposal = _make_proposal(escrow_address=_NATIVE_ADDR)
    with pytest.raises(NotImplementedError):
        build(proposal, _SELLER, 100, 3600)


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

    # The stub address_to_slot recognizes _ARBITER and returns
    # "recipient_arbiter"; the builder threads that through as arbiter_kind.
    assert patched_alkahest["build_call"]["arbiter_kind"] == "recipient_arbiter"


def test_obligation_data_carries_agreed_amount(patched_alkahest):
    """Sanity: ``agreed_amount`` flows straight into obligation_data."""
    build = make_buyer_payment_escrow_terms_fn(
        chain_name=_CHAIN, addr_config_path=None,
    )
    proposal = _make_proposal(literal_fields={"token": _TOKEN})
    terms = build(proposal, _SELLER, 42_000_000, 3600)

    assert patched_alkahest["build_call"]["agreed_amount"] == 42_000_000
    assert patched_alkahest["build_call"]["duration_seconds"] == 3600
    assert terms[0].obligation_data["amount"] == 42_000_000
