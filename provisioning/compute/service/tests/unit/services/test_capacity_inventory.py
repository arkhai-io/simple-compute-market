"""Resource-pool projection inventory, built from capacity declarations alone.

The fixtures below are frozen declaration sets covering a fungible pool and a
specific-resource bare-metal pool. The projection of each must equal its frozen
expectation exactly: that equality is the contractual regression evidence for
the projection's shape.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from compute_provisioning_service.db.models import AnsiblePoolConfig
from compute_provisioning_service.services.capacity_inventory import (
    load_capacity_pool_metadata,
    load_capacity_resource_inventory,
)
from market_resource_pools import ResourcePool


def _declaration(**overrides):
    declaration = {
        "resource_id": "vm-slice-1",
        "pool_id": "gpu-pool",
        "resource_type": "compute.gpu",
        "resource_subtype": "h200",
        "host_id": "compute-kvm1-001",
        "capacity": {"gpu_count": 2, "ram_gb": 256},
        "available": {"gpu_count": 1, "ram_gb": 256},
        "attributes": {"gpu_model": "H200", "region": "us-west"},
        "enabled": True,
    }
    declaration.update(overrides)
    return declaration


def _bare_metal_declaration(**overrides):
    declaration = {
        "resource_id": "physical-resource-1",
        "pool_id": "whole-host-pool",
        "resource_type": "compute.bare-metal",
        "resource_subtype": None,
        "host_id": "bm-host-1",
        "capacity": {"gpu_count": 8, "ram_gb": 512},
        "available": {"gpu_count": 8, "ram_gb": 512},
        "attributes": {
            "physical_host_id": "physical-host-1",
            "allocation_mode": "exclusive",
            "bare_metal_publication": {
                "enabled": True,
                "access_methods": ["ssh"],
                "capabilities": {"gpu_model": "H200", "ram_gb": 512},
                "provider_config": {"ignored": "not projected"},
            },
        },
        "enabled": True,
    }
    declaration.update(overrides)
    return declaration


# ---------------------------------------------------------------------------
# Frozen fixtures
# ---------------------------------------------------------------------------

FUNGIBLE_DECLARATIONS = [
    _declaration(),
    # Names no host at all.
    _declaration(
        resource_id="vm-slice-2",
        host_id=None,
        available={"gpu_count": 2, "ram_gb": 256},
    ),
    # Names a host no registry need know about.
    _declaration(resource_id="vm-slice-3", host_id="not-yet-registered", enabled=False),
]

FUNGIBLE_PROJECTION = [
    {
        "resource_id": "vm-slice-1",
        "pool_id": "gpu-pool",
        "resource_type": "compute.gpu",
        "resource_subtype": "h200",
        "capacity": {"gpu_count": 2, "ram_gb": 256},
        "available": {"gpu_count": 1, "ram_gb": 256},
        "attributes": {"gpu_model": "H200", "region": "us-west"},
        "enabled": True,
    },
    {
        "resource_id": "vm-slice-2",
        "pool_id": "gpu-pool",
        "resource_type": "compute.gpu",
        "resource_subtype": "h200",
        "capacity": {"gpu_count": 2, "ram_gb": 256},
        "available": {"gpu_count": 2, "ram_gb": 256},
        "attributes": {"gpu_model": "H200", "region": "us-west"},
        "enabled": True,
    },
    {
        "resource_id": "vm-slice-3",
        "pool_id": "gpu-pool",
        "resource_type": "compute.gpu",
        "resource_subtype": "h200",
        "capacity": {"gpu_count": 2, "ram_gb": 256},
        "available": {"gpu_count": 1, "ram_gb": 256},
        "attributes": {"gpu_model": "H200", "region": "us-west"},
        "enabled": False,
    },
]

SPECIFIC_RESOURCE_DECLARATIONS = [
    _bare_metal_declaration(),
    # An enabled publication naming no host has no specific host to sell.
    _bare_metal_declaration(resource_id="physical-resource-2", host_id=None),
]

SPECIFIC_RESOURCE_PROJECTION = [
    {
        "resource_id": "physical-resource-1",
        "pool_id": "whole-host-pool",
        "resource_type": "compute.bare-metal",
        "resource_subtype": None,
        "capacity": {"gpu_count": 8, "ram_gb": 512},
        "available": {"gpu_count": 8, "ram_gb": 512},
        "attributes": {
            "physical_host_id": "physical-host-1",
            "allocation_mode": "exclusive",
        },
        "enabled": True,
        "publication_views": {
            "bare_metal.v2": {
                "physical_resource_id": "physical-resource-1",
                "pool_id": "whole-host-pool",
                "physical_host_id": "physical-host-1",
                "host_id": "bm-host-1",
                "available": True,
                "allocation_mode": "exclusive",
                "access_methods": ["ssh"],
                "capacity": {"gpu_count": 8, "ram_gb": 512},
                "capabilities": {"gpu_model": "H200", "ram_gb": 512},
            },
        },
    },
    {
        "resource_id": "physical-resource-2",
        "pool_id": "whole-host-pool",
        "resource_type": "compute.bare-metal",
        "resource_subtype": None,
        "capacity": {"gpu_count": 8, "ram_gb": 512},
        "available": {"gpu_count": 8, "ram_gb": 512},
        "attributes": {
            "physical_host_id": "physical-host-1",
            "allocation_mode": "exclusive",
        },
        "enabled": True,
    },
]


def test_a_fungible_pool_projects_exactly_its_frozen_expectation():
    assert load_capacity_resource_inventory(FUNGIBLE_DECLARATIONS) == FUNGIBLE_PROJECTION


def test_a_specific_resource_pool_projects_exactly_its_frozen_expectation():
    assert (
        load_capacity_resource_inventory(SPECIFIC_RESOURCE_DECLARATIONS)
        == SPECIFIC_RESOURCE_PROJECTION
    )


# ---------------------------------------------------------------------------
# Individual rules
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("host_id", [None, "compute-kvm1-001", "not-yet-registered"])
def test_whether_a_host_is_named_does_not_change_the_entry(host_id):
    (projected,) = load_capacity_resource_inventory([_declaration(host_id=host_id)])
    (reference,) = load_capacity_resource_inventory([_declaration(host_id=None)])

    assert projected == reference


def test_no_entry_carries_host_connection_identity():
    """Registration refuses a host_id attribute, but a stored row may predate
    that. Nothing the projection writes names a host or an address."""
    declarations = [
        _declaration(attributes={"gpu_model": "H200"}),
        _bare_metal_declaration(),
    ]

    for projected in load_capacity_resource_inventory(declarations):
        assert "host_id" not in projected
        assert "host_id" not in projected["attributes"]
        assert "public_host" not in projected["attributes"]


def test_enablement_comes_from_the_declaration_alone():
    (enabled,) = load_capacity_resource_inventory([_declaration(enabled=True)])
    (disabled,) = load_capacity_resource_inventory([_declaration(enabled=False)])

    assert enabled["enabled"] is True
    assert disabled["enabled"] is False


def test_an_undeclared_attribute_is_absent_rather_than_null():
    (projected,) = load_capacity_resource_inventory([_declaration(attributes={})])

    assert projected["attributes"] == {}


def test_unreported_availability_is_not_projected_as_zero():
    """A present ``available`` is read downstream as live availability, so a
    declaration that reports none must project none."""
    declaration = _declaration()
    del declaration["available"]

    (projected,) = load_capacity_resource_inventory([declaration])

    assert "available" not in projected


def test_a_declaration_with_no_recorded_pool_belongs_to_the_default_pool():
    (projected,) = load_capacity_resource_inventory([_declaration(pool_id=None)])

    assert projected["pool_id"] == "default"


def test_the_bare_metal_view_becomes_unavailable_when_any_dimension_is_held():
    declaration = _bare_metal_declaration(available={"gpu_count": 7, "ram_gb": 512})

    (projected,) = load_capacity_resource_inventory([declaration])

    view = projected["publication_views"]["bare_metal.v2"]
    assert view["capacity"] == projected["capacity"]
    assert view["available"] is False


def test_the_bare_metal_view_is_unavailable_for_a_disabled_declaration():
    (projected,) = load_capacity_resource_inventory(
        [_bare_metal_declaration(enabled=False)]
    )

    assert projected["publication_views"]["bare_metal.v2"]["available"] is False


def test_a_publication_that_is_not_enabled_projects_no_view():
    declaration = _bare_metal_declaration()
    declaration["attributes"]["bare_metal_publication"]["enabled"] = False

    (projected,) = load_capacity_resource_inventory([declaration])

    assert "publication_views" not in projected
    assert "bare_metal_publication" not in projected["attributes"]


def test_a_publication_exposing_a_private_capability_fails_closed():
    declaration = _bare_metal_declaration()
    declaration["attributes"]["bare_metal_publication"]["capabilities"] = {
        "service_url": "https://private.invalid",
    }

    with pytest.raises(ValueError):
        load_capacity_resource_inventory([declaration])


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
