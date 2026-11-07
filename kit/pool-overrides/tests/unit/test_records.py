"""The override record refuses what an override may not state."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from market_pool_overrides import PoolOverrideRecord

ADDRESS = {"site_id": "site-a", "pool_id": "gpu", "offering_mode": "vm"}
SHAPE = {"gpu": {"count": 1, "model": "H100"}}


def test_a_record_stating_shapes_settlements_and_terms_is_valid():
    record = PoolOverrideRecord.model_validate(
        {**ADDRESS, "listing_shapes": [SHAPE], "settlements": [{"mechanism": "m"}],
         "terms": {"sla": 99.0}}
    )

    assert record.address.offering_mode == "vm"


@pytest.mark.parametrize(
    "fields",
    [
        pytest.param({}, id="states nothing"),
        pytest.param({"terms": {}}, id="empty terms state nothing"),
        pytest.param({"listing_shapes": []}, id="empty shape list"),
        pytest.param({"settlements": []}, id="empty clause list"),
        pytest.param({"terms": {"sla": 1}, "region": "us-east"}, id="region is the site's"),
        pytest.param({"terms": {"sla": 1}, "capacity_backing": "backed"}, id="backing is the site's"),
        pytest.param({"listing_shapes": ["not an object"]}, id="shape not an object"),
    ],
)
def test_a_record_is_refused(fields):
    with pytest.raises(ValidationError):
        PoolOverrideRecord.model_validate({**ADDRESS, **fields})


@pytest.mark.parametrize("field", ["site_id", "pool_id", "offering_mode"])
@pytest.mark.parametrize("value", [None, "", "a\x00b", 7])
def test_every_address_component_is_a_non_empty_string_and_never_defaulted(field, value):
    fields = {**ADDRESS, "terms": {"sla": 1}}
    if value is None:
        del fields[field]
    else:
        fields[field] = value

    with pytest.raises(ValidationError):
        PoolOverrideRecord.model_validate(fields)
