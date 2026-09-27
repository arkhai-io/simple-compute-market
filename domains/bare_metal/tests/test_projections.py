from __future__ import annotations

import pytest
from pydantic import ValidationError

from arkhai_bare_metal import (
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
        {"access_methods": []},
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


def _trusted(resource=None, *, pool_id="pool-1", enabled=True):
    return TrustedBareMetalResource(
        pool_id=pool_id,
        enabled=enabled,
        view=BareMetalResourceProjection.model_validate(resource or _resource()),
    )


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
