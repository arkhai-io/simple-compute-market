from __future__ import annotations

import pytest
from pydantic import ValidationError

from arkhai_bare_metal import (
    BareMetalResourceProjection,
    TrustedBareMetalProjection,
)


def _resource(**overrides):
    values = {
        "physical_resource_id": "resource-1",
        "physical_host_id": "host-physical-1",
        "machine_id": "executor-machine-1",
        "available": True,
        "allocation_mode": "exclusive",
        "access_methods": ["ssh"],
        "capacity": {"gpu_count": 8, "ram_gb": 512},
        "capabilities": {"gpu_model": "H200", "ram_gb": 512},
    }
    values.update(overrides)
    return values


def test_resource_projection_preserves_distinct_identities_and_public_data():
    projection = BareMetalResourceProjection.model_validate(_resource())

    assert projection.physical_resource_id == "resource-1"
    assert projection.physical_host_id == "host-physical-1"
    assert projection.machine_id == "executor-machine-1"
    assert projection.available is True
    assert projection.access_methods == ["ssh"]
    assert projection.capacity == {"gpu_count": 8, "ram_gb": 512}
    assert projection.capabilities == {"gpu_model": "H200", "ram_gb": 512}


@pytest.mark.parametrize(
    "overrides",
    [
        {"physical_resource_id": ""},
        {"physical_host_id": ""},
        {"machine_id": ""},
        {"allocation_mode": "shareable"},
        {"access_methods": []},
        {"capabilities": {"service_url": "https://private.invalid"}},
        {"capabilities": {"nested": {"password": "secret"}}},
        {"capacity": {"ram_gb": 256}, "capabilities": {"ram_gb": 512}},
        {"provider_config": {"inventory": "private"}},
    ],
)
def test_resource_projection_rejects_incomplete_private_or_conflicting_data(
    overrides,
):
    with pytest.raises(ValidationError):
        BareMetalResourceProjection.model_validate(_resource(**overrides))


def test_trusted_projection_injects_site_generation_provenance():
    generation = TrustedBareMetalProjection(
        site_id="site-a",
        revision=7,
        digest="sha256-generation",
        complete=True,
        resources=[_resource()],
    )

    assert generation.site_id == "site-a"
    assert generation.resources[0].machine_id == "executor-machine-1"


def test_authoritative_empty_generation_is_distinct_from_unavailable_generation():
    authoritative_empty = TrustedBareMetalProjection(
        site_id="site-a",
        revision=8,
        digest="empty-generation",
        complete=True,
        resources=[],
    )
    unavailable = TrustedBareMetalProjection(
        site_id="site-a",
        revision=0,
        digest="unavailable",
        complete=False,
        resources=[],
    )

    assert authoritative_empty.complete is True
    assert unavailable.complete is False


def test_incomplete_generation_cannot_expose_resources():
    with pytest.raises(ValidationError, match="incomplete generations"):
        TrustedBareMetalProjection(
            site_id="site-a",
            revision=1,
            digest="partial",
            complete=False,
            resources=[_resource()],
        )


def test_resource_identity_is_unique_within_trusted_site():
    with pytest.raises(ValidationError, match="unique"):
        TrustedBareMetalProjection(
            site_id="site-a",
            revision=1,
            digest="duplicate",
            complete=True,
            resources=[_resource(), _resource(machine_id="other-machine")],
        )
