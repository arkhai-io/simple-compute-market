"""Bare metal's resource view: a whole machine offered for sale."""

from __future__ import annotations

import pytest

from bare_metal_provisioning_adapter.inventory_views import (
    BARE_METAL_PUBLICATION_ATTR,
    BareMetalPublicationViews,
)

VIEWS = BareMetalPublicationViews()


def _declaration(**overrides):
    declaration = {
        "resource_id": "physical-resource-1",
        "host_id": "bm-host-1",
        "capacity": {"gpu_count": 8, "ram_gb": 512},
        "available": {"gpu_count": 8, "ram_gb": 512},
        "attributes": {
            "physical_host_id": "physical-host-1",
            "allocation_mode": "exclusive",
            BARE_METAL_PUBLICATION_ATTR: {
                "enabled": True,
                "access_methods": ["ssh"],
                "capabilities": {"gpu_model": "H200", "ram_gb": 512},
            },
        },
        "enabled": True,
    }
    declaration.update(overrides)
    return declaration


def _view(declaration):
    return VIEWS.resource_views(declaration, pool_id="whole-host-pool").get("bare_metal.v2")


def test_an_enabled_publication_is_the_machine_with_its_pool():
    view = _view(_declaration())

    assert view == {
        "physical_resource_id": "physical-resource-1",
        "pool_id": "whole-host-pool",
        "physical_host_id": "physical-host-1",
        "host_id": "bm-host-1",
        "available": True,
        "allocation_mode": "exclusive",
        "access_methods": ["ssh"],
        "capacity": {"gpu_count": 8, "ram_gb": 512},
        "capabilities": {"gpu_model": "H200", "ram_gb": 512},
    }


def test_the_machine_is_unavailable_when_any_dimension_is_held():
    assert _view(_declaration(available={"gpu_count": 7, "ram_gb": 512}))["available"] is False


def test_the_machine_is_unavailable_when_its_declaration_is_disabled():
    assert _view(_declaration(enabled=False))["available"] is False


def test_a_declaration_with_no_positive_dimension_has_nothing_to_sell():
    declaration = _declaration(capacity={"gpu_count": 0}, available={"gpu_count": 0})

    assert _view(declaration)["available"] is False


def test_a_publication_that_is_not_enabled_projects_no_view():
    declaration = _declaration()
    declaration["attributes"][BARE_METAL_PUBLICATION_ATTR]["enabled"] = False

    assert _view(declaration) is None


def test_a_declaration_naming_no_host_has_no_machine_to_sell():
    assert _view(_declaration(host_id=None)) is None


def test_a_publication_exposing_a_private_capability_fails_closed():
    declaration = _declaration()
    declaration["attributes"][BARE_METAL_PUBLICATION_ATTR]["capabilities"] = {
        "service_url": "https://private.invalid",
    }

    with pytest.raises(ValueError):
        _view(declaration)


def test_the_publication_attribute_is_consumed_and_no_pool_view_is_produced():
    assert VIEWS.consumed_attributes == {BARE_METAL_PUBLICATION_ATTR}
    assert VIEWS.pool_views(None, pool_id="p", provider="bare_metal.ansible") == {}
