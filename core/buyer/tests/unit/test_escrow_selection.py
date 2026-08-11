from __future__ import annotations

from dataclasses import FrozenInstanceError
from io import StringIO

import pytest
from rich.console import Console

from core_buyer.escrow_selection import select_escrow_entry


_TOKEN_A = "0x" + "11" * 20
_TOKEN_B = "0x" + "22" * 20
_BUYER = "0x" + "aa" * 20


def _entry(
    position: int,
    *,
    chain_name: str = "anvil",
    token: str = _TOKEN_A,
) -> dict:
    return {
        "chain_name": chain_name,
        "escrow_address": "0x" + f"{position:02x}" * 20,
        "literal_fields": {"token": token},
        "rates": [{"field": "amount", "per": "hour", "value": str(position)}],
    }


def _select(listing: dict, **overrides):
    kwargs = {
        "chain_name": "anvil",
        "token_contract_filter": None,
        "assume_yes": True,
        "rpc_url": "http://unused",
        "buyer_address": _BUYER,
    }
    kwargs.update(overrides)
    return select_escrow_entry(listing, **kwargs)


def test_zero_and_one_candidate_skip_preference() -> None:
    calls = 0

    def preference(candidates, context):
        nonlocal calls
        calls += 1
        return candidates[0].identity

    assert _select({"accepted_escrows": []}, preference=preference) is None
    sole = _entry(1)
    assert _select({"accepted_escrows": [sole]}, preference=preference) is sole
    assert calls == 0


def test_preference_sees_only_constrained_immutable_candidates() -> None:
    compatible_entries = [_entry(4), _entry(5)]
    listing = {
        "listing_id": "listing-1",
        "accepted_escrows": [
            _entry(1, chain_name="other"),
            _entry(2, token=_TOKEN_B),
            _entry(3),
            *compatible_entries,
        ],
    }

    def compatible(entry):
        return entry["escrow_address"] != _entry(3)["escrow_address"]

    def preference(candidates, context):
        assert tuple(candidate.position for candidate in candidates) == (0, 1)
        assert tuple(candidate.token_address for candidate in candidates) == (
            _TOKEN_A,
            _TOKEN_A,
        )
        assert context.listing_id == "listing-1"
        assert context.chain_name == "anvil"
        assert context.token_contract_filter == _TOKEN_A
        with pytest.raises(FrozenInstanceError):
            candidates[0].position = 9
        return (candidates[1].identity, candidates[0].identity)

    assert (
        _select(
            listing,
            token_contract_filter=_TOKEN_A.upper(),
            compatible=compatible,
            preference=preference,
        )
        is compatible_entries[1]
    )


def test_valid_preference_precedes_positive_balance(monkeypatch) -> None:
    first, second = _entry(1, token=_TOKEN_A), _entry(2, token=_TOKEN_B)
    balance_calls = 0

    def balance(**_kwargs):
        nonlocal balance_calls
        balance_calls += 1
        return 1

    monkeypatch.setattr("core_buyer.escrow_selection._balance", balance)

    def preference(candidates, _context):
        return candidates[0].identity

    assert (
        _select({"accepted_escrows": [first, second]}, preference=preference) is first
    )
    assert balance_calls == 0


def test_none_preference_then_positive_balance_then_list_order(monkeypatch) -> None:
    first, second = _entry(1, token=_TOKEN_A), _entry(2, token=_TOKEN_B)
    monkeypatch.setattr(
        "core_buyer.escrow_selection._balance",
        lambda **kwargs: 1 if kwargs["token_address"] == _TOKEN_B else 0,
    )

    def no_preference(_candidates, _context):
        return None

    listing = {"accepted_escrows": [first, second]}
    assert _select(listing, preference=no_preference) is second

    monkeypatch.setattr("core_buyer.escrow_selection._balance", lambda **_kwargs: 0)
    assert _select(listing, preference=no_preference) is first


@pytest.mark.parametrize(
    "mode", ["unknown", "duplicate", "exceptional", "inconsistent"]
)
def test_invalid_preference_output_uses_constrained_fallback(
    monkeypatch,
    caplog,
    mode: str,
) -> None:
    first, second = _entry(1), _entry(2)
    monkeypatch.setattr("core_buyer.escrow_selection._balance", lambda **_kwargs: 0)
    calls = 0

    def preference(candidates, _context):
        nonlocal calls
        calls += 1
        if mode == "unknown":
            return "outside-candidate-set"
        if mode == "duplicate":
            return (candidates[1].identity, candidates[1].identity)
        if mode == "exceptional":
            raise RuntimeError("policy unavailable")
        return candidates[calls - 1].identity

    assert (
        _select({"accepted_escrows": [first, second]}, preference=preference) is first
    )
    assert "constrained fallback" in caplog.text


def test_interactive_choice_is_authoritative(monkeypatch) -> None:
    first, second = _entry(1), _entry(2)

    def preference(_candidates, _context):
        raise AssertionError("interactive selection must not invoke preference")

    monkeypatch.setattr("core_buyer.escrow_selection.typer.prompt", lambda *_a, **_k: 2)
    picked = _select(
        {"accepted_escrows": [first, second]},
        assume_yes=False,
        console=Console(file=StringIO()),
        preference=preference,
    )
    assert picked is second
