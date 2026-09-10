"""Declaration validation precedes Mapping coercion and historical extra handling."""

import copy
from collections import UserDict
from types import MappingProxyType

import pytest
from pydantic import ValidationError

from arkhai_bare_metal import BareMetalListing


DECLARATION_LISTING = {
    "kind": "bare_metal.v1", "virtualization_type": "bare_metal",
    "declaration_id": "declaration-example", "access_methods": ["none"],
    "site": {"region": "Example region"},
    "capabilities": {
        "gpu_model": "Example GPU", "gpu_count": 2, "vcpu_count": 8,
        "ram_gb": 32, "disk_gb": 256,
    },
}


@pytest.mark.parametrize("mapping", [dict, UserDict, MappingProxyType])
def test_declaration_listing_accepts_supported_mappings_without_changing_shape(mapping):
    value = copy.deepcopy(DECLARATION_LISTING)
    value["site"] = mapping(value["site"])
    value["capabilities"] = mapping(value["capabilities"])
    assert BareMetalListing.model_validate(mapping(value)).model_dump(mode="json") == DECLARATION_LISTING


@pytest.mark.parametrize("mapping", [dict, UserDict, MappingProxyType])
@pytest.mark.parametrize("mutation", [
    "unknown", "nonstring_key", "site_extra", "capabilities_extra", "coerced_count",
    "missing_site", "missing_capabilities", "tuple_access", "null_physical_id",
])
def test_declaration_listing_rejects_input_before_mapping_coercion(mapping, mutation):
    value = copy.deepcopy(DECLARATION_LISTING)
    if mutation == "unknown":
        value["unrecognized"] = "example"
    elif mutation == "nonstring_key":
        value[1] = "example"
    elif mutation == "site_extra":
        value["site"]["unrecognized"] = "example"
    elif mutation == "capabilities_extra":
        value["capabilities"]["unrecognized"] = "example"
    elif mutation == "coerced_count":
        value["capabilities"]["gpu_count"] = "2"
    elif mutation == "missing_site":
        value.pop("site")
    elif mutation == "missing_capabilities":
        value.pop("capabilities")
    elif mutation == "tuple_access":
        value["access_methods"] = ("none",)
    else:
        value["physical_host_id"] = None
    with pytest.raises(ValidationError):
        BareMetalListing.model_validate(mapping(value))


@pytest.mark.parametrize("mapping", [dict, UserDict, MappingProxyType])
@pytest.mark.parametrize("identifier", [b"declaration-example", bytearray(b"example"), 1, True, None, ["example"]])
def test_declaration_identifier_requires_a_string(mapping, identifier):
    value = {**DECLARATION_LISTING, "declaration_id": identifier}
    with pytest.raises(ValidationError):
        BareMetalListing.model_validate(mapping(value))


@pytest.mark.parametrize("mapping", [dict, UserDict, MappingProxyType])
def test_historical_listing_keeps_coercion_extra_handling_and_serialization(mapping):
    value = mapping({
        "machine_id": b"machine-example", "physical_host_id": b"host-example",
        "access_methods": ("ssh",), "min_duration_seconds": "60", "unknown": "ignored",
    })
    assert BareMetalListing.model_validate(value).model_dump(mode="json") == {
        "kind": "bare_metal.v1", "virtualization_type": "bare_metal",
        "machine_id": "machine-example", "physical_host_id": "host-example",
        "access_methods": ["ssh"], "min_duration_seconds": 60,
        "max_duration_seconds": None, "site": None, "capabilities": {},
    }
