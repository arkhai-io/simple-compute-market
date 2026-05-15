"""Unit tests for buyer-side counter policy.

Covers the default ``strict_echo`` (rejects any change to a
buyer-pinned field) and ``always_accept`` policies, plus the loader.
"""
from __future__ import annotations

import pytest

from service.schemas import EscrowProposal

from market_buyer.counter_policy import (
    DEFAULT_POLICY_NAME,
    CounterDecision,
    list_counter_policies,
    load_counter_policy,
    register_counter_policy,
)


_ESCROW_ADDR = "0x" + "AA" * 20
_TOKEN = "0x" + "11" * 20
_ARBITER = "0x" + "22" * 20


def _proposal(**overrides) -> EscrowProposal:
    base = dict(
        chain_name="anvil",
        escrow_address=_ESCROW_ADDR,
        fields={"payment_token": _TOKEN},
        expiration_unix=1_800_000_000,
    )
    base.update(overrides)
    return EscrowProposal(**base)


# ---------------------------------------------------------------------------
# strict_echo
# ---------------------------------------------------------------------------


def test_strict_echo_accepts_exact_echo():
    policy = load_counter_policy("strict_echo")
    decision = policy(_proposal(), _proposal())
    assert decision.action == "accept"
    assert decision.reason is None


def test_strict_echo_accepts_when_seller_adds_a_key_buyer_did_not_pin():
    """Buyer was silent about arbiter; seller picks a default — fine."""
    policy = load_counter_policy("strict_echo")
    sent = _proposal()  # fields = {payment_token: ...}
    returned = _proposal(
        fields={"payment_token": _TOKEN, "arbiter": _ARBITER},
    )
    decision = policy(sent, returned)
    assert decision.action == "accept"


def test_strict_echo_normalizes_hex_address_case():
    """EIP-55-checksummed vs lowercase address on the same field is the same value.

    The hex digits differ in case; the ``0x`` prefix stays lowercase
    either way (real-world wallets emit lowercase prefix).
    """
    policy = load_counter_policy("strict_echo")
    checksummed = "0xABcdef" + "0" * 34
    lowered = "0xabcdef" + "0" * 34
    sent = _proposal(fields={"payment_token": checksummed})
    returned = _proposal(fields={"payment_token": lowered})
    assert policy(sent, returned).action == "accept"


def test_strict_echo_rejects_missing_echo():
    policy = load_counter_policy("strict_echo")
    decision = policy(_proposal(), None)
    assert decision.action == "reject"
    assert decision.reason == "seller_did_not_echo"


def test_strict_echo_rejects_chain_swap():
    policy = load_counter_policy("strict_echo")
    decision = policy(_proposal(), _proposal(chain_name="mainnet"))
    assert decision.action == "reject"
    assert decision.reason is not None
    assert "chain_name_changed" in decision.reason


def test_strict_echo_rejects_escrow_address_swap():
    policy = load_counter_policy("strict_echo")
    other_addr = "0x" + "BB" * 20
    decision = policy(_proposal(), _proposal(escrow_address=other_addr))
    assert decision.action == "reject"
    assert decision.reason is not None
    assert "escrow_address_changed" in decision.reason


def test_strict_echo_rejects_expiration_change():
    policy = load_counter_policy("strict_echo")
    sent = _proposal(expiration_unix=1_800_000_000)
    returned = _proposal(expiration_unix=1_800_000_999)
    decision = policy(sent, returned)
    assert decision.action == "reject"
    assert decision.reason is not None
    assert "expiration_unix_changed" in decision.reason


def test_strict_echo_rejects_changed_buyer_pinned_field():
    policy = load_counter_policy("strict_echo")
    other_token = "0x" + "33" * 20
    sent = _proposal(fields={"payment_token": _TOKEN})
    returned = _proposal(fields={"payment_token": other_token})
    decision = policy(sent, returned)
    assert decision.action == "reject"
    assert decision.reason is not None
    assert "field_changed:payment_token" in decision.reason


def test_strict_echo_rejects_dropped_buyer_pinned_field():
    """Seller returns without a field the buyer set → reject."""
    policy = load_counter_policy("strict_echo")
    sent = _proposal(fields={"payment_token": _TOKEN, "arbiter": _ARBITER})
    returned = _proposal(fields={"payment_token": _TOKEN})  # arbiter missing
    decision = policy(sent, returned)
    assert decision.action == "reject"
    assert decision.reason is not None
    assert "field_changed:arbiter" in decision.reason


# ---------------------------------------------------------------------------
# always_accept
# ---------------------------------------------------------------------------


def test_always_accept_accepts_missing_echo():
    policy = load_counter_policy("always_accept")
    assert policy(_proposal(), None).action == "accept"


def test_always_accept_accepts_field_change():
    policy = load_counter_policy("always_accept")
    other_token = "0x" + "33" * 20
    decision = policy(
        _proposal(fields={"payment_token": _TOKEN}),
        _proposal(fields={"payment_token": other_token}),
    )
    assert decision.action == "accept"


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def test_load_default_is_strict_echo():
    """None / empty name → strict_echo."""
    assert load_counter_policy(None) is load_counter_policy("strict_echo")
    assert load_counter_policy("") is load_counter_policy("strict_echo")


def test_load_unknown_name_raises():
    with pytest.raises(ValueError) as exc:
        load_counter_policy("does_not_exist")
    msg = str(exc.value)
    assert "does_not_exist" in msg
    assert "strict_echo" in msg


def test_list_includes_builtins():
    names = list_counter_policies()
    assert "strict_echo" in names
    assert "always_accept" in names


def test_register_counter_policy_overrides():
    """Decorator-style registration overrides earlier same-name entries."""
    @register_counter_policy("test_temp_override")
    def _custom(sent, returned):
        return CounterDecision(action="reject", reason="custom_reject")

    try:
        policy = load_counter_policy("test_temp_override")
        decision = policy(_proposal(), _proposal())
        assert decision.action == "reject"
        assert decision.reason == "custom_reject"
    finally:
        # Cleanup so the test doesn't pollute the registry for siblings.
        from market_buyer.counter_policy import _REGISTRY
        _REGISTRY.pop("test_temp_override", None)


def test_default_policy_name_constant_matches_registered_default():
    """Sanity: DEFAULT_POLICY_NAME points at a registered policy."""
    assert DEFAULT_POLICY_NAME in list_counter_policies()
