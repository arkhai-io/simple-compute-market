from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from compute_provisioning_service.services.capacity_inventory import (
    load_capacity_pool_metadata,
    load_capacity_resource_inventory,
)
from compute_provisioning_service.db.models import AnsiblePoolConfig
from market_resource_pools import ResourcePool


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
        gpu_model=None,
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


def test_load_capacity_resource_inventory_includes_gpu_model_when_set():
    host = _host()
    host.gpu_model = "H100"
    session = _session_for(host)

    result = load_capacity_resource_inventory(lambda: session)

    assert result[0]["attributes"]["gpu_model"] == "H100"


def test_load_capacity_resource_inventory_omits_gpu_model_when_unset():
    """A host with no recorded GPU model must not project an empty/null
    gpu_model key -- absence, not a null placeholder."""
    host = _host()
    assert host.gpu_model is None
    session = _session_for(host)

    result = load_capacity_resource_inventory(lambda: session)

    assert "gpu_model" not in result[0]["attributes"]


def test_bare_metal_view_uses_explicit_identities_and_same_generation_availability():
    host = _host()
    session = _session_for(host)
    resource = {
        "resource_id": "physical-resource-1",
        "pool_id": "gpu-pool",
        "resource_type": "compute.bare-metal",
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
        "pool_id": "gpu-pool",
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


# ---------------------------------------------------------------------------
# load_capacity_pool_metadata
# ---------------------------------------------------------------------------

def _pool_session(*, pools, ansible_configs):
    def query(model):
        result = MagicMock()
        if model is ResourcePool:
            result.all.return_value = pools
        elif model is AnsiblePoolConfig:
            result.all.return_value = ansible_configs
        else:  # pragma: no cover - defensive
            raise AssertionError(f"unexpected query target {model!r}")
        return result

    session = MagicMock()
    session.query.side_effect = query
    session.__enter__.return_value = session
    session.__exit__.return_value = False
    return session


def _pool(**overrides):
    defaults = dict(
        id="gpu-pool",
        label="GPU Pool",
        provider="ansible",
        enabled=True,
        policy_tags={"region": "eu"},
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_load_capacity_pool_metadata_projects_allowlisted_pool_fields():
    session = _pool_session(pools=[_pool()], ansible_configs=[])

    result = load_capacity_pool_metadata(lambda: session)

    assert result == {
        "gpu-pool": {
            "label": "GPU Pool",
            "enabled": True,
            "mechanism": "ansible",
            "policy_tags": {"region": "eu"},
        }
    }


def test_load_capacity_pool_metadata_nests_vm_size_defaults_under_versioned_view():
    session = _pool_session(
        pools=[_pool()],
        ansible_configs=[
            SimpleNamespace(
                pool_id="gpu-pool",
                default_vm_ram=65536,
                default_vm_vcpus=16,
                default_vm_disk_size="500G",
            ),
        ],
    )

    result = load_capacity_pool_metadata(lambda: session)

    assert result["gpu-pool"]["pool_views"] == {
        "vm.ansible_pool_defaults.v1": {
            "default_vm_ram": 65536,
            "default_vm_vcpus": 16,
            "default_vm_disk_size": "500G",
        },
    }


def test_load_capacity_pool_metadata_omits_pool_views_when_all_defaults_unset():
    session = _pool_session(
        pools=[_pool()],
        ansible_configs=[
            SimpleNamespace(
                pool_id="gpu-pool",
                default_vm_ram=None,
                default_vm_vcpus=None,
                default_vm_disk_size=None,
            ),
        ],
    )

    result = load_capacity_pool_metadata(lambda: session)

    assert "pool_views" not in result["gpu-pool"]


def test_load_capacity_pool_metadata_omits_pool_views_with_no_ansible_config_row():
    session = _pool_session(pools=[_pool()], ansible_configs=[])

    result = load_capacity_pool_metadata(lambda: session)

    assert "pool_views" not in result["gpu-pool"]


def test_load_capacity_pool_metadata_includes_partial_defaults():
    session = _pool_session(
        pools=[_pool()],
        ansible_configs=[
            SimpleNamespace(
                pool_id="gpu-pool",
                default_vm_ram=65536,
                default_vm_vcpus=None,
                default_vm_disk_size=None,
            ),
        ],
    )

    result = load_capacity_pool_metadata(lambda: session)

    assert result["gpu-pool"]["pool_views"] == {
        "vm.ansible_pool_defaults.v1": {"default_vm_ram": 65536},
    }


def test_load_capacity_pool_metadata_never_projects_provider_config():
    pool = _pool()
    assert not hasattr(pool, "provider_config")
    session = _pool_session(pools=[pool], ansible_configs=[])

    result = load_capacity_pool_metadata(lambda: session)

    assert "provider_config" not in result["gpu-pool"]
    assert "extra_vars" not in result["gpu-pool"]
    assert "playbook_path" not in result["gpu-pool"]


def test_load_capacity_pool_metadata_disabled_pool_reported_as_disabled():
    session = _pool_session(pools=[_pool(enabled=False)], ansible_configs=[])

    result = load_capacity_pool_metadata(lambda: session)

    assert result["gpu-pool"]["enabled"] is False


def test_load_capacity_pool_metadata_handles_several_pools_independently():
    session = _pool_session(
        pools=[_pool(id="gpu-pool"), _pool(id="cpu-pool", label="CPU Pool", provider="k8s")],
        ansible_configs=[
            SimpleNamespace(
                pool_id="gpu-pool", default_vm_ram=65536,
                default_vm_vcpus=None, default_vm_disk_size=None,
            ),
        ],
    )

    result = load_capacity_pool_metadata(lambda: session)

    assert set(result) == {"gpu-pool", "cpu-pool"}
    assert "pool_views" in result["gpu-pool"]
    assert "pool_views" not in result["cpu-pool"]
    assert result["cpu-pool"]["mechanism"] == "k8s"


def test_load_capacity_pool_metadata_ignores_stale_ansible_config_for_non_ansible_pool():
    """A pool whose declared mechanism is no longer 'ansible' must never
    surface the vm.ansible_pool_defaults.v1 view, even if a stale
    ansible_pool_configs row happens to still exist for its pool_id --
    the view name's own semantics ("vm.ansible...") must never be
    published alongside a contradicting mechanism."""
    session = _pool_session(
        pools=[_pool(provider="k8s")],
        ansible_configs=[
            SimpleNamespace(
                pool_id="gpu-pool", default_vm_ram=65536,
                default_vm_vcpus=16, default_vm_disk_size="500G",
            ),
        ],
    )

    result = load_capacity_pool_metadata(lambda: session)

    assert result["gpu-pool"]["mechanism"] == "k8s"
    assert "pool_views" not in result["gpu-pool"]
