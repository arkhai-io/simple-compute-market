from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from compute_provisioning_service.services.capacity_inventory import (
    load_capacity_resource_inventory,
)


def _session_for(host):
    query = MagicMock()
    query.order_by.return_value.all.return_value = [host]
    session = MagicMock()
    session.query.return_value = query
    session.__enter__.return_value = session
    session.__exit__.return_value = False
    return session


def _host():
    return SimpleNamespace(
        name="compute-kvm1-001",
        pool_id="gpu-pool",
        gpu_count=8,
        public_host="203.0.113.10",
        kvm_host="10.0.0.10",
        enabled=True,
    )


def test_load_capacity_resource_inventory_projects_allowlisted_host_fields():
    host = _host()
    session = _session_for(host)

    result = load_capacity_resource_inventory(lambda: session)

    assert result == [
        {
            "resource_id": "compute-kvm1-001",
            "pool_id": "gpu-pool",
            "resource_type": "compute.gpu",
            "resource_subtype": None,
            "capacity": {"gpu_count": 8},
            "attributes": {
                "vm_host": "compute-kvm1-001",
                "public_host": "203.0.113.10",
                "gpu_count": 8,
            },
            "enabled": True,
        }
    ]


def test_bare_metal_view_uses_explicit_identities_and_same_generation_availability():
    host = _host()
    session = _session_for(host)
    resource = {
        "resource_id": "physical-resource-1",
        "pool_id": "gpu-pool",
        "resource_type": "bare_metal",
        "capacity": {"gpu_count": 8, "ram_gb": 512},
        "available": {"gpu_count": 8, "ram_gb": 512},
        "enabled": True,
        "attributes": {
            "bare_metal_publication": {
                "enabled": True,
                "physical_host_id": "physical-host-1",
                "machine_id": "compute-kvm1-001",
                "allocation_mode": "exclusive",
                "access_methods": ["ssh"],
                "capabilities": {"gpu_model": "H200", "ram_gb": 512},
                "provider_config": {"ignored": "not projected"},
            },
        },
    }

    result = load_capacity_resource_inventory(
        lambda: session,
        capacity_resources=[resource],
    )

    view = result[0]["publication_views"]["bare_metal.v1"]
    assert view == {
        "physical_resource_id": "physical-resource-1",
        "physical_host_id": "physical-host-1",
        "machine_id": "compute-kvm1-001",
        "available": True,
        "allocation_mode": "exclusive",
        "access_methods": ["ssh"],
        "capacity": {"gpu_count": 8, "ram_gb": 512},
        "capabilities": {"gpu_model": "H200", "ram_gb": 512},
    }
    assert "provider_config" not in view
    assert "public_host" not in view


def test_bare_metal_view_becomes_unavailable_when_any_dimension_is_held():
    host = _host()
    session = _session_for(host)
    resource = {
        "resource_id": "physical-resource-1",
        "pool_id": "gpu-pool",
        "capacity": {"gpu_count": 8, "ram_gb": 512},
        "available": {"gpu_count": 7, "ram_gb": 512},
        "enabled": True,
        "attributes": {
            "bare_metal_publication": {
                "enabled": True,
                "physical_host_id": "physical-host-1",
                "machine_id": "compute-kvm1-001",
                "allocation_mode": "exclusive",
                "access_methods": ["ssh"],
            },
        },
    }

    result = load_capacity_resource_inventory(
        lambda: session,
        capacity_resources=[resource],
    )

    assert result[0]["publication_views"]["bare_metal.v1"]["available"] is False


@pytest.mark.parametrize(
    "publication_config",
    [
        {
            "enabled": True,
            "physical_host_id": "physical-host-1",
            "allocation_mode": "exclusive",
            "access_methods": ["ssh"],
        },
        {
            "enabled": True,
            "physical_host_id": "physical-host-1",
            "machine_id": "compute-kvm1-001",
            "allocation_mode": "exclusive",
            "access_methods": ["ssh"],
            "capabilities": {"service_url": "https://private.invalid"},
        },
    ],
)
def test_invalid_or_private_bare_metal_view_fails_closed(publication_config):
    host = _host()
    session = _session_for(host)
    resource = {
        "resource_id": "physical-resource-1",
        "pool_id": "gpu-pool",
        "capacity": {"gpu_count": 8},
        "available": {"gpu_count": 8},
        "attributes": {"bare_metal_publication": publication_config},
    }

    with pytest.raises(ValueError):
        load_capacity_resource_inventory(
            lambda: session,
            capacity_resources=[resource],
        )
