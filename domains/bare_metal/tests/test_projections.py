from __future__ import annotations

import pytest
from pydantic import ValidationError

from arkhai_bare_metal import (
    BARE_METAL_VIEW_DELIVERY_TERMS,
    BareMetalResourceProjection,
    TrustedBareMetalProjection,
    TrustedBareMetalResource,
)


def _resource(**overrides):
    values = {
        "physical_resource_id": "resource-1",
        "physical_host_id": "host-physical-1",
        "host_id": "executor-machine-1",
        "available": True,
        "allocation_mode": "exclusive",
        "access_methods": ["ssh"],
        "capacity": {"gpu_count": 8, "ram_gb": 512},
        "capabilities": {"gpu_model": "H200", "ram_gb": 512},
    }
    values.update(overrides)
    return values


def test_publication_only_capabilities_may_differ_from_capacity():
    """Nothing reads them, so a disagreement cannot refuse a site's generation."""
    projection = BareMetalResourceProjection.model_validate(
        _resource(capacity={"ram_gb": 256}, capabilities={"ram_gb": 512})
    )

    assert projection.capacity == {"ram_gb": 256}


def test_resource_projection_preserves_distinct_identities_and_public_data():
    projection = BareMetalResourceProjection.model_validate(_resource())

    assert projection.physical_resource_id == "resource-1"
    assert projection.physical_host_id == "host-physical-1"
    assert projection.host_id == "executor-machine-1"
    assert projection.available is True
    assert projection.access_methods == ["ssh"]
    assert projection.capacity == {"gpu_count": 8, "ram_gb": 512}
    assert projection.capabilities == {"gpu_model": "H200", "ram_gb": 512}


@pytest.mark.parametrize(
    "overrides",
    [
        {"physical_resource_id": ""},
        {"physical_host_id": ""},
        {"host_id": ""},
        {"allocation_mode": "shareable"},
        {"access_methods": ["ssh", " "]},
        {"capabilities": {"service_url": "https://private.invalid"}},
        {"capabilities": {"nested": {"password": "secret"}}},
        {"provider_config": {"inventory": "private"}},
    ],
)
def test_resource_projection_rejects_incomplete_or_private_data(
    overrides,
):
    with pytest.raises(ValidationError):
        BareMetalResourceProjection.model_validate(_resource(**overrides))


def test_the_view_model_leaves_delivery_terms_to_its_carrier():
    """Without its pool's backing, a view cannot say which terms it owes, so
    the model alone accepts a view with none of them and states no default."""
    projection = BareMetalResourceProjection.model_validate(
        _unbacked_resource()
    )

    assert projection.host_id is None
    assert projection.physical_host_id is None
    assert projection.available is None
    assert projection.access_methods is None


def _unbacked_resource(**overrides):
    values = {
        key: value
        for key, value in _resource().items()
        if key not in BARE_METAL_VIEW_DELIVERY_TERMS
    }
    values.update(overrides)
    return values


def _trusted(resource=None, *, pool_id="pool-1", enabled=True, capacity_backing=None):
    return TrustedBareMetalResource(
        pool_id=pool_id,
        enabled=enabled,
        view=BareMetalResourceProjection.model_validate(resource or _resource()),
        capacity_backing=capacity_backing,
    )


class TestDeliveryTerms:
    """The carrier holds a view's delivery terms to its pool's backing."""

    def test_a_backed_view_carrying_every_term_is_valid(self):
        assert _trusted(capacity_backing="backed").view.host_id == "executor-machine-1"

    @pytest.mark.parametrize("term", BARE_METAL_VIEW_DELIVERY_TERMS)
    def test_a_backed_view_missing_a_term_is_refused(self, term):
        resource = _resource()
        del resource[term]

        with pytest.raises(ValidationError, match=term):
            _trusted(resource, capacity_backing="backed")

    def test_a_backed_view_reporting_its_machine_unavailable_states_the_term(self):
        trusted = _trusted(_resource(available=False), capacity_backing="backed")

        assert trusted.view.available is False

    def test_a_backed_view_listing_no_access_method_is_refused(self):
        with pytest.raises(ValidationError, match="access_methods"):
            _trusted(_resource(access_methods=[]), capacity_backing="backed")

    def test_an_unbacked_view_with_no_terms_is_valid(self):
        trusted = _trusted(_unbacked_resource(), capacity_backing="unbacked")

        assert trusted.capacity_backing == "unbacked"

    @pytest.mark.parametrize("term", BARE_METAL_VIEW_DELIVERY_TERMS)
    def test_an_unbacked_view_carrying_a_term_is_refused(self, term):
        resource = _unbacked_resource(**{term: _resource()[term]})

        with pytest.raises(ValidationError, match=term):
            _trusted(resource, capacity_backing="unbacked")

    def test_a_pool_whose_backing_did_not_resolve_checks_no_term(self):
        assert _trusted(_unbacked_resource()).capacity_backing is None
        assert _trusted(_resource()).capacity_backing is None


def test_trusted_projection_injects_site_generation_provenance():
    generation = TrustedBareMetalProjection(
        site_id="site-a",
        revision=7,
        digest="sha256-generation",
        resources=[_trusted()],
    )

    assert generation.site_id == "site-a"
    assert generation.resources[0].view.host_id == "executor-machine-1"


def test_authoritative_empty_generation_is_valid():
    generation = TrustedBareMetalProjection(
        site_id="site-a",
        revision=8,
        digest="empty-generation",
        resources=[],
    )

    assert generation.resources == []


def test_resource_identity_is_unique_within_trusted_site():
    with pytest.raises(ValidationError, match="unique"):
        TrustedBareMetalProjection(
            site_id="site-a",
            revision=1,
            digest="duplicate",
            resources=[_trusted(), _trusted(_resource(host_id="other-machine"))],
        )


def test_a_view_naming_another_pool_than_its_container_is_refused():
    with pytest.raises(ValidationError, match="containing pool"):
        _trusted(_resource(pool_id="pool-2"), pool_id="pool-1")


def test_a_view_naming_no_pool_takes_its_containers():
    trusted = _trusted(_resource(pool_id=None), pool_id="pool-1")

    assert trusted.pool_id == "pool-1"
