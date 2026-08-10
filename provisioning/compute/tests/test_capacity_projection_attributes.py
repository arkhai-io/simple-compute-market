"""The capacity projection preserves each resource's declared attributes.

`load_capacity_resource_inventory` documents capacity resources as authoritative
for Physical Resource identity, with host rows supplying only executor
correlation. It built the projected attributes from the host row alone, so every
attribute a consumer matches on was dropped — `region` above all, which no host
row carries. A storefront asking for a region it had itself published could never
match, and the refusal surfaced as `no_matching_inventory`.
"""

from __future__ import annotations

from types import SimpleNamespace

from compute_provisioning_service.services.capacity_inventory import _project_host


def _host(**overrides):
    base = {
        "name": "kvm1",
        "kvm_host": "10.0.0.1",
        "public_host": None,
        "ssh_user": "op",
        "gpu_count": 4,
        "gpu_model": "RTX 4090",
        "enabled": True,
        "pool_id": "default",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _resource(**overrides):
    base = {
        "resource_id": "compute-kvm1-001",
        "pool_id": "default",
        "resource_type": "compute.gpu",
        "resource_subtype": "rtx4090",
        "enabled": True,
        "attributes": {
            "region": "California, US",
            "gpu_model": "RTX 4090",
            "sla": "90.0",
            "vm_host": "kvm1",
        },
        "capacity": {"gpu_count": 4},
        "available": {"gpu_count": 4},
    }
    base.update(overrides)
    return base


def test_declared_attributes_survive_the_projection() -> None:
    projected = _project_host(_host(), capacity_resource=_resource())

    attributes = projected["attributes"]
    assert attributes["region"] == "California, US"
    assert attributes["gpu_model"] == "RTX 4090"
    assert attributes["sla"] == "90.0"


def test_region_is_projected_even_though_no_host_row_carries_one() -> None:
    """The specific omission: matching requires region, hosts have none."""
    projected = _project_host(_host(), capacity_resource=_resource())

    assert "region" in projected["attributes"]


def test_executor_correlation_still_overrides() -> None:
    """Host identity wins for executor fields — that is what hosts are for."""
    resource = _resource()
    resource["attributes"]["vm_host"] = "stale-alias"

    projected = _project_host(_host(name="kvm1"), capacity_resource=resource)

    assert projected["attributes"]["vm_host"] == "kvm1"
    assert projected["attributes"]["public_host"] == "10.0.0.1"
    assert projected["attributes"]["gpu_count"] == 4


def test_host_gpu_model_is_a_fallback_not_an_override() -> None:
    resource = _resource()
    resource["attributes"]["gpu_model"] = "H200"

    projected = _project_host(_host(gpu_model="RTX 4090"), capacity_resource=resource)

    assert projected["attributes"]["gpu_model"] == "H200"


def test_host_gpu_model_fills_in_when_the_resource_declares_none() -> None:
    resource = _resource()
    del resource["attributes"]["gpu_model"]

    projected = _project_host(_host(gpu_model="RTX 4090"), capacity_resource=resource)

    assert projected["attributes"]["gpu_model"] == "RTX 4090"


def test_a_host_without_a_capacity_resource_still_projects() -> None:
    """Executor inventory with nothing published against it is a valid state."""
    projected = _project_host(_host(), capacity_resource=None)

    assert projected["attributes"]["vm_host"] == "kvm1"
    assert projected["resource_id"] == "kvm1"
    assert "available" not in projected
