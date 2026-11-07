"""The whole-machine capacity claim both reservation paths make."""

from __future__ import annotations

import pytest
from market_site.ledger import dict_resource_satisfies_claim

from arkhai_bare_metal_storefront.claims import ClaimAttributesMissing, whole_machine_claim


def test_one_unit_the_listing_attributes_and_the_mode():
    claim = whole_machine_claim({"claimed_attributes": {"gpu_model": "H200"}})

    assert claim == {"gpu_model": "H200", "dimensions": {"units": 1}, "offering_mode": "bare_metal"}


def test_the_offering_mode_is_the_accepted_options():
    claim = whole_machine_claim(
        {"claimed_attributes": {"gpu_model": "H200"}}, offering_mode="bare_metal"
    )

    assert claim["offering_mode"] == "bare_metal"


@pytest.mark.parametrize("context", [{}, {"claimed_attributes": "H200"}, {"claimed_attributes": None}])
def test_a_record_carrying_no_claimed_attributes_is_refused(context):
    with pytest.raises(ClaimAttributesMissing):
        whole_machine_claim(context)


def test_a_machine_without_gpus_claims_one_unit_and_no_attribute():
    claim = whole_machine_claim({"claimed_attributes": {}})

    assert claim == {"dimensions": {"units": 1}, "offering_mode": "bare_metal"}


# -- the claim against the site's own admission matcher ---------------------
#
# ``dict_resource_satisfies_claim`` is the site ledger's exported matcher: the
# same claim parsing and feasibility admission applies, over a snapshot row.
# These cases tie the whole-machine claim's spelling to what the site does with
# it, which a recording capacity double cannot show.



def _declaration(*, gpu_model="H200", available=None):
    capacity = {"units": 1, "gpu_count": 8, "ram_gb": 2048}
    return {
        "resource_id": "resource-1",
        "pool_id": "pool-a",
        "resource_type": "compute.bare-metal",
        "available": dict(capacity if available is None else available),
        "attributes": {"gpu_model": gpu_model, "physical_host_id": "physical-host-1"},
    }


def _claim():
    claim = whole_machine_claim({"claimed_attributes": {"gpu_model": "H200"}})
    claim["resource_id"] = "resource-1"
    return claim


def test_the_site_admits_the_claim_for_the_machine_the_listing_published():
    assert dict_resource_satisfies_claim(_declaration(), _claim()) is True


def test_the_site_refuses_the_claim_once_the_declared_model_changed():
    assert dict_resource_satisfies_claim(_declaration(gpu_model="B200"), _claim()) is False


def test_the_site_refuses_the_claim_once_the_machine_is_taken():
    taken = {"units": 0, "gpu_count": 8, "ram_gb": 2048}
    assert dict_resource_satisfies_claim(_declaration(available=taken), _claim()) is False


def test_the_site_admits_a_claim_with_no_attribute_for_a_machine_without_gpus():
    declaration = {
        **_declaration(available={"units": 1, "vcpu_count": 64, "ram_gb": 512}),
        "attributes": {"physical_host_id": "physical-host-1"},
    }
    claim = {**whole_machine_claim({"claimed_attributes": {}}), "resource_id": "resource-1"}

    assert dict_resource_satisfies_claim(declaration, claim) is True


def test_hardware_quantities_are_not_requested():
    """Only the unit is requested: a machine whose GPUs are all accounted as
    available still matches, and so would one whose hardware dimensions the
    claim never names."""
    no_hardware = {"units": 1}
    assert dict_resource_satisfies_claim(_declaration(available=no_hardware), _claim()) is True
