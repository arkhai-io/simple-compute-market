"""The main compute spec filters settlement options, not just escrows."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.api.filter_eval import build_criteria, evaluate_all
from src.api.filter_spec import load_filter_spec

_SPEC = Path(__file__).resolve().parents[2] / "filter-spec.yaml"
_TOKEN = "0x" + "ab" * 20
_OTHER_TOKEN = "0x" + "cd" * 20


@pytest.fixture
def spec():
    return load_filter_spec(_SPEC)


def _option_listing(**params_overrides) -> dict:
    params = {
        "accepted_escrow": {
            "chain_name": "base-sepolia",
            "escrow_address": "0x" + "11" * 20,
            "literal_fields": {"token": _TOKEN},
            "rates": [{"field": "amount", "per": "hour", "value": "100"}],
        }
    }
    params.update(params_overrides)
    return {
        "listing_id": "opt-1",
        "settlement_options": [
            {
                "option_id": "aa" * 32,
                "mechanism": "alkahest.v1",
                "asset": _TOKEN,
                "rates": [{"field": "amount", "per": "hour", "value": "100"}],
                "params": params,
            }
        ],
    }


def _match(spec, listing, **params) -> bool:
    stringified = {key: str(value) for key, value in params.items()}
    return evaluate_all(listing, build_criteria(spec, stringified))


def test_compute_spec_declares_the_option_aware_filters(spec) -> None:
    names = {item.name for item in spec.filters}
    assert {"mechanism", "option_token", "option_token_exclude"} <= names


def test_mechanism_filter_is_option_aware_and_missing_tolerant(spec) -> None:
    listing = _option_listing()
    assert _match(spec, listing, mechanism="in:[alkahest.v1]")
    assert not _match(spec, listing, mechanism="in:[fiat.stripe.v1]")
    escrow_only = {"listing_id": "legacy-1", "accepted_escrows": [{}]}
    assert _match(spec, escrow_only, mechanism="in:[alkahest.v1]")


def test_option_token_filters_read_the_embedded_escrow_template(spec) -> None:
    listing = _option_listing()
    assert _match(spec, listing, option_token=f"in:[{_TOKEN}]")
    assert not _match(spec, listing, option_token=f"in:[{_OTHER_TOKEN}]")
    assert not _match(spec, listing, option_token_exclude=f"not_in:[{_TOKEN}]")
    assert _match(spec, listing, option_token_exclude=f"not_in:[{_OTHER_TOKEN}]")


def test_option_token_missing_is_underreport_friendly(spec) -> None:
    rateless = _option_listing(accepted_escrow=None)
    rateless["settlement_options"][0]["params"] = {"channel": "telegram"}
    assert _match(spec, rateless, option_token=f"in:[{_TOKEN}]")
    assert _match(spec, rateless, option_token_exclude=f"not_in:[{_TOKEN}]")
