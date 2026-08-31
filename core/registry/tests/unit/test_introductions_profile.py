"""The loose-listing introduction-market profile loads and matches tolerantly."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.api.filter_eval import build_criteria, evaluate_all
from src.api.filter_spec import load_filter_spec

_PROFILE = Path(__file__).resolve().parents[2] / "filter-spec.introductions.yaml"


@pytest.fixture
def spec():
    return load_filter_spec(_PROFILE)


def _listing(**overrides) -> dict:
    listing = {
        "listing_id": "intro-1",
        "storefront_url": "https://broker.example",
        "offer_resource": {"description": "8x H100 blocks, private broker"},
        "settlement_options": [
            {
                "option_id": "aa" * 32,
                "mechanism": "contact-exchange.v1",
                "asset": "introduction",
                "rates": [],
                "params": {"channel": "telegram", "terms": "prose"},
            }
        ],
    }
    listing.update(overrides)
    return listing


def _match(spec, listing, **params) -> bool:
    stringified = {key: str(value) for key, value in params.items()}
    return evaluate_all(listing, build_criteria(spec, stringified))


def test_profile_loads_with_schema_identity(spec) -> None:
    assert spec.schema_identity is not None
    assert spec.schema_identity.id == "introductions.market"
    assert {item.name for item in spec.filters} == {"region", "mechanism", "channel"}


def test_sparse_listings_stay_discoverable(spec) -> None:
    sparse = _listing(
        offer_resource={},
        settlement_options=[
            {
                "option_id": "bb" * 32,
                "mechanism": "contact-exchange.v1",
                "asset": "introduction",
                "rates": [],
                "params": {"terms": "prose only, no stated channel"},
            }
        ],
    )
    assert _match(spec, sparse, region="California, US")
    assert _match(spec, sparse, channel="signal")


def test_stated_fields_still_filter_exactly(spec) -> None:
    listing = _listing()
    assert _match(spec, listing, channel="telegram")
    assert _match(spec, listing, mechanism="contact-exchange.v1")


def test_option_projections_reject_stated_mismatches(spec) -> None:
    listing = _listing()
    assert not _match(spec, listing, channel="carrier-pigeon")
    assert not _match(spec, listing, mechanism="fiat.stripe.v1")
