from __future__ import annotations

import pytest

from market_storefront.utils.resource_csv_importer import (
    parse_accepted_escrows_cell,
)
from market_config.config_loader import EscrowTemplate, RateSlot


def _template(
    name: str,
    *,
    chain: str = "anvil",
    escrow_address: str = "0x" + "ab" * 20,
    literal: dict | None = None,
    rates: dict[str, RateSlot] | None = None,
) -> EscrowTemplate:
    return EscrowTemplate(
        name=name,
        chain=chain,
        escrow_address=escrow_address,
        literal_fields=literal or {},
        rate_slots=rates or {},
    )


# --- empty + whitespace ---------------------------------------------------


def test_empty_cell_returns_empty_list():
    assert parse_accepted_escrows_cell("", {}) == []
    assert parse_accepted_escrows_cell("   ", {}) == []
    assert parse_accepted_escrows_cell(";", {}) == []


# --- explicit slot form ---------------------------------------------------


def test_named_slots_emit_materialized_entry():
    template = _template(
        "usdc",
        literal={"token": "0xUSDC"},
        rates={"amount": RateSlot(field="amount", per="hour")},
    )
    result = parse_accepted_escrows_cell("usdc:amount=150", {"usdc": template})
    assert result == [
        {
            "chain_name": "anvil",
            "escrow_address": "0x" + "ab" * 20,
            "literal_fields": {"token": "0xUSDC"},
            "rates": [{"field": "amount", "per": "hour", "value": "150"}],
        }
    ]


def test_multi_slot_template_preserves_template_order():
    template = _template(
        "bundle",
        rates={
            "usdc": RateSlot(field="erc20Amounts[0]", per="hour"),
            "credits": RateSlot(field="erc20Amounts[1]", per="hour"),
            "eth": RateSlot(field="nativeAmount", per="hour"),
        },
    )
    # CSV order differs from template order — output follows template.
    result = parse_accepted_escrows_cell(
        "bundle:eth=0,credits=10,usdc=180", {"bundle": template},
    )
    assert [r["field"] for r in result[0]["rates"]] == [
        "erc20Amounts[0]", "erc20Amounts[1]", "nativeAmount",
    ]
    assert [r["value"] for r in result[0]["rates"]] == ["180", "10", "0"]


def test_multiple_entries_separated_by_semicolon():
    a = _template("a", rates={"amount": RateSlot(field="amount", per="hour")})
    b = _template("b", rates={"amount": RateSlot(field="amount", per="hour")})
    result = parse_accepted_escrows_cell("a:amount=10; b:amount=20", {"a": a, "b": b})
    assert len(result) == 2
    assert result[0]["rates"][0]["value"] == "10"
    assert result[1]["rates"][0]["value"] == "20"


# --- single-slot ergonomic sugar ------------------------------------------


def test_single_slot_sugar_resolves_to_sole_slot():
    template = _template(
        "usdc",
        literal={"token": "0xUSDC"},
        rates={"amount": RateSlot(field="amount", per="hour")},
    )
    result = parse_accepted_escrows_cell("usdc=150", {"usdc": template})
    assert result[0]["rates"] == [
        {"field": "amount", "per": "hour", "value": "150"}
    ]


def test_single_slot_sugar_fails_on_multi_slot_template():
    template = _template(
        "bundle",
        rates={
            "usdc": RateSlot(field="erc20Amounts[0]"),
            "credits": RateSlot(field="erc20Amounts[1]"),
        },
    )
    with pytest.raises(ValueError, match="bare value form"):
        parse_accepted_escrows_cell("bundle=150", {"bundle": template})


def test_single_slot_sugar_fails_on_zero_slot_template():
    template = _template("attest", literal={"attestationUid": "0xab"})
    with pytest.raises(ValueError, match="bare value form"):
        parse_accepted_escrows_cell("attest=150", {"attest": template})


# --- zero-slot attestation form -------------------------------------------


def test_bare_template_name_for_zero_slot_attestation():
    template = _template(
        "service_attestation",
        literal={"attestationUid": "0xab"},
        rates={},
    )
    result = parse_accepted_escrows_cell(
        "service_attestation", {"service_attestation": template},
    )
    assert result == [
        {
            "chain_name": "anvil",
            "escrow_address": "0x" + "ab" * 20,
            "literal_fields": {"attestationUid": "0xab"},
            "rates": [],
        }
    ]


def test_bare_template_name_fails_on_rate_bearing_template():
    template = _template(
        "usdc", rates={"amount": RateSlot(field="amount")},
    )
    with pytest.raises(ValueError, match="bare template form"):
        parse_accepted_escrows_cell("usdc", {"usdc": template})


# --- validation errors ----------------------------------------------------


def test_unknown_template_errors():
    with pytest.raises(ValueError, match="unknown template 'nope'"):
        parse_accepted_escrows_cell("nope:amount=1", {})


def test_unknown_slot_errors():
    template = _template(
        "usdc", rates={"amount": RateSlot(field="amount")},
    )
    with pytest.raises(ValueError, match="unknown slot"):
        parse_accepted_escrows_cell("usdc:creditz=1", {"usdc": template})


def test_missing_slot_errors():
    template = _template(
        "bundle",
        rates={
            "usdc": RateSlot(field="erc20Amounts[0]"),
            "credits": RateSlot(field="erc20Amounts[1]"),
        },
    )
    with pytest.raises(ValueError, match="missing slot"):
        parse_accepted_escrows_cell("bundle:usdc=1", {"bundle": template})


def test_duplicate_slot_errors():
    template = _template(
        "usdc", rates={"amount": RateSlot(field="amount")},
    )
    with pytest.raises(ValueError, match="specified more than once"):
        parse_accepted_escrows_cell("usdc:amount=1,amount=2", {"usdc": template})


def test_colon_with_no_slots_errors():
    template = _template(
        "usdc", rates={"amount": RateSlot(field="amount")},
    )
    with pytest.raises(ValueError, match="no slot assignments"):
        parse_accepted_escrows_cell("usdc:", {"usdc": template})


def test_slot_missing_equals_errors():
    template = _template(
        "usdc", rates={"amount": RateSlot(field="amount")},
    )
    with pytest.raises(ValueError, match="missing '='"):
        parse_accepted_escrows_cell("usdc:amount150", {"usdc": template})


# --- escrow_address is lower-cased on emit --------------------------------


def test_escrow_address_lowercased_on_materialize():
    template = _template(
        "usdc",
        escrow_address="0xABCDEF" + "00" * 17,
        rates={"amount": RateSlot(field="amount")},
    )
    result = parse_accepted_escrows_cell("usdc:amount=1", {"usdc": template})
    assert result[0]["escrow_address"] == "0xabcdef" + "00" * 17


# --- literal_fields are deep-copied so caller mutation is safe ------------


def test_literal_fields_are_copied_not_shared():
    literal = {"token": "0xUSDC"}
    template = _template(
        "usdc",
        literal=literal,
        rates={"amount": RateSlot(field="amount")},
    )
    result = parse_accepted_escrows_cell("usdc:amount=1", {"usdc": template})
    result[0]["literal_fields"]["mutated"] = True
    assert "mutated" not in literal
