"""The whole-machine capacity claim both reservation paths make."""

from __future__ import annotations

import pytest

from arkhai_bare_metal_storefront.claims import ClaimAttributesMissing, whole_machine_claim


def test_one_unit_the_listing_attributes_and_the_mode():
    claim = whole_machine_claim({"claimed_attributes": {"gpu_model": "H200"}})

    assert claim == {"gpu_model": "H200", "dimensions": {"units": 1}, "offering_mode": "bare_metal"}


def test_the_offering_mode_is_the_accepted_options():
    claim = whole_machine_claim(
        {"claimed_attributes": {"gpu_model": "H200"}}, offering_mode="bare_metal"
    )

    assert claim["offering_mode"] == "bare_metal"


@pytest.mark.parametrize("context", [{}, {"claimed_attributes": {}}, {"claimed_attributes": "H200"}])
def test_a_context_naming_no_attributes_is_refused(context):
    with pytest.raises(ClaimAttributesMissing):
        whole_machine_claim(context)
