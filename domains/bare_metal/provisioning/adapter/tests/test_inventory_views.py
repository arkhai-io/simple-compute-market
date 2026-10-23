"""Bare metal's resource view: a whole machine offered for sale.

Each view is built with its pool's context; what the declaration says about the
machine reaches the view only as the pool's backing delegate carries it, and a
declaration no valid view can be built from is reported, never raised.
"""

from __future__ import annotations

import pytest
from arkhai_bare_metal.fixtures.publication_view import (
    validate_bare_metal_publication_view,
)
from compute_provisioning import InventoryPoolContext, ResourceViews
from market_resource_pools_contracts.backing import BACKED, UNBACKED
from market_resource_pools_contracts.hints import PoolDeclarations

from bare_metal_provisioning_adapter.inventory_views import (
    BARE_METAL_PUBLICATION_ATTR,
    BareMetalPublicationViews,
)

VIEWS = BareMetalPublicationViews()
VIEW = "bare_metal.v2"
DELIVERY_TERMS = {"host_id", "physical_host_id", "access_methods", "available"}


def _pool(backing=BACKED, pool_id="whole-host-pool"):
    return InventoryPoolContext(
        pool_id=pool_id,
        provider="bare_metal.ansible",
        declarations=PoolDeclarations(
            advertisable_modes=frozenset({"bare_metal"}), backing=backing
        ),
    )


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


def _built(declaration, backing=BACKED) -> ResourceViews:
    return VIEWS.resource_views(declaration, pool=_pool(backing))


def _view(declaration, backing=BACKED):
    return _built(declaration, backing).views.get(VIEW)


def _problems(declaration, backing=BACKED):
    built = _built(declaration, backing)
    assert VIEW not in built.views
    return built.problems[VIEW]


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
    validate_bare_metal_publication_view(
        view, backing=BACKED, physical_resource_id="physical-resource-1",
        pool_id="whole-host-pool",
    )


def test_the_machine_is_unavailable_when_any_dimension_is_held():
    assert _view(_declaration(available={"gpu_count": 7, "ram_gb": 512}))["available"] is False


def test_the_machine_is_unavailable_when_its_declaration_is_disabled():
    assert _view(_declaration(enabled=False))["available"] is False


def test_a_declaration_with_no_positive_dimension_has_nothing_to_sell():
    declaration = _declaration(capacity={"gpu_count": 0}, available={"gpu_count": 0})

    assert _view(declaration)["available"] is False


def test_a_publication_that_is_not_enabled_projects_no_view_and_no_problem():
    declaration = _declaration()
    declaration["attributes"][BARE_METAL_PUBLICATION_ATTR]["enabled"] = False

    assert _built(declaration) == ResourceViews()


@pytest.mark.parametrize("host_id", [None, "bm-host-1"])
def test_an_unbacked_pools_view_carries_no_delivery_terms(host_id):
    """Host or no host, access methods declared or not: nothing stands behind
    them, so the view carries none and still sells the machine's shape."""
    view = _view(_declaration(host_id=host_id), backing=UNBACKED)

    assert DELIVERY_TERMS.isdisjoint(view)
    assert view["capacity"] == {"gpu_count": 8, "ram_gb": 512}
    assert view["capabilities"] == {"gpu_model": "H200", "ram_gb": 512}
    validate_bare_metal_publication_view(
        view, backing=UNBACKED, physical_resource_id="physical-resource-1",
        pool_id="whole-host-pool",
    )


def test_an_unbacked_view_needs_no_physical_host_or_access_methods():
    declaration = _declaration(host_id=None)
    del declaration["attributes"]["physical_host_id"]
    del declaration["attributes"][BARE_METAL_PUBLICATION_ATTR]["access_methods"]

    assert _view(declaration, backing=UNBACKED) is not None


@pytest.mark.parametrize(
    ("damage", "named"),
    [
        pytest.param(lambda d: d.update(host_id=None), "host_id", id="no host"),
        pytest.param(
            lambda d: d["attributes"][BARE_METAL_PUBLICATION_ATTR].pop("access_methods"),
            "access_methods",
            id="no access methods",
        ),
        pytest.param(
            lambda d: d["attributes"][BARE_METAL_PUBLICATION_ATTR].update(access_methods=[]),
            "access_methods",
            id="empty access methods",
        ),
        pytest.param(
            lambda d: d["attributes"].pop("physical_host_id"),
            "physical_host_id",
            id="no physical host",
        ),
        pytest.param(
            lambda d: d["attributes"].pop("allocation_mode"),
            "allocation_mode",
            id="no allocation mode",
        ),
        pytest.param(
            lambda d: d["attributes"].update(allocation_mode="shareable"),
            "allocation_mode",
            id="invalid allocation mode",
        ),
        pytest.param(
            lambda d: d["attributes"][BARE_METAL_PUBLICATION_ATTR].update(
                capabilities={"service_url": "https://private.invalid"}
            ),
            "service_url",
            id="private capability",
        ),
        pytest.param(
            lambda d: d.update(capacity={"gpu_count": 8, "credential": 1}),
            "credential",
            id="private capacity key",
        ),
    ],
)
def test_a_backed_declaration_no_view_can_be_built_from_is_a_problem(damage, named):
    declaration = _declaration()
    damage(declaration)

    problems = _problems(declaration)

    assert any(named in problem for problem in problems), problems


def test_a_private_capability_is_a_problem_in_an_unbacked_pool_too():
    declaration = _declaration()
    declaration["attributes"][BARE_METAL_PUBLICATION_ATTR]["capabilities"] = {
        "nested": {"password": "secret"},
    }

    assert any("password" in problem for problem in _problems(declaration, UNBACKED))


def test_the_publication_attribute_is_consumed_and_no_pool_view_is_produced():
    assert VIEWS.consumed_attributes == {BARE_METAL_PUBLICATION_ATTR}
    assert VIEWS.pool_views(None, pool_id="p", provider="bare_metal.ansible") == {}
