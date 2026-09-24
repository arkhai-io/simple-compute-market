"""The pool override record refuses what an override may not state."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from market_storefront.models.pool_override_models import PoolOverrideRecord

SHAPE = {"gpu": {"count": 1, "model": "H100"}, "memory": {"gib": 64}}
CLAUSE = {"mechanism": "alkahest.v1", "asset": "0x" + "22" * 20, "rate": "1", "per": "hour"}


def _record(**fields):
    return PoolOverrideRecord.model_validate({"site_id": "a", "pool_id": "gpu", **fields})


def test_a_record_stating_only_its_address_is_valid():
    record = _record()

    assert record.listing_shapes is None and record.settlements is None and record.sla is None


def test_a_complete_record_is_valid():
    record = _record(
        sla=99.5, min_price="3", token="0xtoken", max_duration_seconds=3600,
        settlements=[CLAUSE], listing_shapes=[SHAPE],
    )

    assert record.listing_shapes == [SHAPE]


@pytest.mark.parametrize(
    "fields",
    [
        pytest.param({"region": "us-east"}, id="region is the site's"),
        pytest.param({"offering_mode": "vm"}, id="offering mode is the site's"),
        pytest.param({"capacity_backing": "backed"}, id="backing is the site's"),
        pytest.param({"accepted_escrows": []}, id="raw escrows are not a clause"),
        pytest.param({"listing_shapes": []}, id="empty shape list"),
        pytest.param({"settlements": []}, id="empty clause list"),
        pytest.param({"listing_shapes": [{"gpu": {"count": 1}}]}, id="shape without a model"),
        pytest.param(
            {"listing_shapes": [{"gpu": {"count": 1, "model": "H100"}, "fpga": {"count": 1}}]},
            id="family outside the vocabulary",
        ),
        pytest.param({"sla": -1}, id="negative sla"),
        pytest.param({"max_duration_seconds": 0}, id="zero duration"),
        pytest.param({"max_duration_seconds": "60"}, id="quoted duration"),
        pytest.param({"min_price": 3}, id="numeric price"),
    ],
)
def test_a_record_is_refused(fields):
    with pytest.raises(ValidationError):
        _record(**fields)


@pytest.mark.parametrize("field", ["site_id", "pool_id"])
@pytest.mark.parametrize("value", ["", "a\x00b", 7])
def test_an_address_is_a_non_empty_string_without_nul(field, value):
    with pytest.raises(ValidationError):
        _record(**{field: value})


def test_a_shape_refusal_names_the_offending_shape():
    with pytest.raises(ValidationError) as caught:
        _record(listing_shapes=[SHAPE, {"gpu": {"count": 1, "model": "H100"}, "fpga": {}}])

    assert "[1]" in str(caught.value)
