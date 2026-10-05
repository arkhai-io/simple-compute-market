"""Resource-pool projection inventory, built from capacity declarations alone.

The fixtures below are frozen declaration sets covering a fungible pool and a
specific-resource bare-metal pool, projected with the inventory views
production composes. The projection of each must equal its frozen expectation
exactly: that equality is the contractual regression evidence for the
projection's shape. Each domain's own view rules are tested beside its
projection; this module proves the neutral rules and the merge.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from bare_metal_provisioning_adapter.inventory_views import BareMetalPublicationViews
from compute_provisioning import InventoryViews, compose_inventory_views
from compute_provisioning_service.db.models import AnsiblePoolConfig
from compute_provisioning_service.services.capacity_inventory import (
    load_capacity_pool_metadata,
    load_capacity_resource_inventory,
)
from arkhai_bare_metal.fixtures.publication_view import (
    validate_bare_metal_publication_view,
)
from market_resource_pools import ResourcePool
from market_site.projections import resource_pool_projection
from vm_provisioning_adapter.inventory_views import AnsiblePoolDefaultsViews

#: The views production composes, one projection per adapter bundle.
VIEWS = compose_inventory_views(
    [
        ("vm", AnsiblePoolDefaultsViews(provider="ansible")),
        ("bare-metal", BareMetalPublicationViews()),
    ]
)
NO_VIEWS = InventoryViews()


def _project(declarations, views=VIEWS):
    return load_capacity_resource_inventory(declarations, views)


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
    assert _project(FUNGIBLE_DECLARATIONS) == FUNGIBLE_PROJECTION


def test_a_specific_resource_pool_projects_exactly_its_frozen_expectation():
    assert _project(SPECIFIC_RESOURCE_DECLARATIONS) == SPECIFIC_RESOURCE_PROJECTION


# ---------------------------------------------------------------------------
# Neutral rules
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("host_id", [None, "compute-kvm1-001", "not-yet-registered"])
def test_whether_a_host_is_named_does_not_change_the_entry(host_id):
    (projected,) = _project([_declaration(host_id=host_id)])
    (reference,) = _project([_declaration(host_id=None)])

    assert projected == reference


def test_no_entry_carries_host_connection_identity():
    """Registration refuses a host_id attribute, but a stored row may predate
    that. Nothing the neutral projection writes names a host or an address."""
    declarations = [
        _declaration(attributes={"gpu_model": "H200"}),
        _bare_metal_declaration(),
    ]

    for projected in _project(declarations):
        assert "host_id" not in projected
        assert "host_id" not in projected["attributes"]
        assert "public_host" not in projected["attributes"]


def test_enablement_comes_from_the_declaration_alone():
    (enabled,) = _project([_declaration(enabled=True)])
    (disabled,) = _project([_declaration(enabled=False)])

    assert enabled["enabled"] is True
    assert disabled["enabled"] is False


def test_an_undeclared_attribute_is_absent_rather_than_null():
    (projected,) = _project([_declaration(attributes={})])

    assert projected["attributes"] == {}


def test_unreported_availability_is_not_projected_as_zero():
    """A present ``available`` is read downstream as live availability, so a
    declaration that reports none must project none."""
    declaration = _declaration()
    del declaration["available"]

    (projected,) = _project([declaration])

    assert "available" not in projected


def test_a_declaration_with_no_recorded_pool_belongs_to_the_default_pool():
    (projected,) = _project([_declaration(pool_id=None)])

    assert projected["pool_id"] == "default"


def test_without_contributed_views_every_attribute_projects_and_no_view_does():
    (projected,) = _project([_bare_metal_declaration()], NO_VIEWS)

    assert "bare_metal_publication" in projected["attributes"]
    assert "publication_views" not in projected


def test_every_bare_metal_view_meets_its_consumers_contract():
    """Each view the site projects is one a bare-metal storefront accepts: it
    names the resource and the pool entry that contain it, as the site's
    resource-pool projection groups them."""
    declarations = [
        *SPECIFIC_RESOURCE_DECLARATIONS,
        _bare_metal_declaration(resource_id="physical-resource-3", enabled=False),
        _bare_metal_declaration(
            resource_id="physical-resource-4",
            available={"gpu_count": 0, "ram_gb": 0},
        ),
    ]

    pools = resource_pool_projection(_project(declarations))

    validated = 0
    for pool in pools:
        for resource in pool["resources"]:
            view = (resource.get("publication_views") or {}).get("bare_metal.v2")
            if view is None:
                continue
            validate_bare_metal_publication_view(
                view,
                physical_resource_id=resource["physical_resource_id"],
                pool_id=pool["pool_id"],
            )
            validated += 1
    assert validated == 3


# ---------------------------------------------------------------------------
# A third domain
# ---------------------------------------------------------------------------

class _ThirdDomainViews:
    """A further compute domain's projection, which the service has never seen."""

    resource_view_ids = frozenset({"third.v1"})
    pool_view_ids = frozenset({"third.pool.v1"})
    consumed_attributes = frozenset({"third_config"})

    def resource_views(self, declaration, *, pool_id):
        config = (declaration.get("attributes") or {}).get("third_config")
        if not config:
            return {}
        return {"third.v1": {"pool_id": pool_id, "flavour": config["flavour"]}}

    def pool_views(self, db, *, pool_id, provider):
        return {"third.pool.v1": {"provider": provider}} if provider == "third" else {}


THIRD_DOMAIN_VIEWS = compose_inventory_views(
    [
        ("vm", AnsiblePoolDefaultsViews(provider="ansible")),
        ("bare-metal", BareMetalPublicationViews()),
        ("third", _ThirdDomainViews()),
    ]
)


def test_a_third_domains_resource_view_is_attached_and_its_attribute_consumed():
    declaration = _declaration(
        attributes={"gpu_model": "H200", "third_config": {"flavour": "plain"}}
    )

    (projected,) = _project([declaration], THIRD_DOMAIN_VIEWS)

    assert projected["publication_views"] == {
        "third.v1": {"pool_id": "gpu-pool", "flavour": "plain"}
    }
    assert projected["attributes"] == {"gpu_model": "H200"}


def test_a_third_domains_pool_view_is_attached():
    session = _pool_session(pools=[_pool(id="third-pool", provider="third")])

    result = load_capacity_pool_metadata(lambda: session, THIRD_DOMAIN_VIEWS)

    assert result["third-pool"]["pool_views"] == {"third.pool.v1": {"provider": "third"}}


# ---------------------------------------------------------------------------
# load_capacity_pool_metadata
# ---------------------------------------------------------------------------

def _pool_session(*, pools, ansible_configs=()):
    configs = {config.pool_id: config for config in ansible_configs}

    def query(model):
        if model is not ResourcePool:  # pragma: no cover - defensive
            raise AssertionError(f"unexpected query target {model!r}")
        result = MagicMock()
        result.all.return_value = pools
        return result

    def get(model, pool_id):
        assert model is AnsiblePoolConfig
        return configs.get(pool_id)

    session = MagicMock()
    session.query.side_effect = query
    session.get.side_effect = get
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
    session = _pool_session(pools=[_pool()])

    result = load_capacity_pool_metadata(lambda: session, VIEWS)

    assert result == {
        "gpu-pool": {
            "label": "GPU Pool",
            "enabled": True,
            "mechanism": "ansible",
            "policy_tags": {"region": "eu"},
        }
    }


def test_load_capacity_pool_metadata_attaches_the_contributed_pool_view():
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

    result = load_capacity_pool_metadata(lambda: session, VIEWS)

    assert result["gpu-pool"]["pool_views"] == {
        "vm.ansible_pool_defaults.v1": {
            "default_vm_ram": 65536,
            "default_vm_vcpus": 16,
            "default_vm_disk_size": "500G",
        },
    }


def test_load_capacity_pool_metadata_never_projects_provider_config():
    pool = _pool()
    assert not hasattr(pool, "provider_config")
    session = _pool_session(pools=[pool])

    result = load_capacity_pool_metadata(lambda: session, VIEWS)

    assert "provider_config" not in result["gpu-pool"]
    assert "extra_vars" not in result["gpu-pool"]
    assert "playbook_path" not in result["gpu-pool"]


def test_load_capacity_pool_metadata_disabled_pool_reported_as_disabled():
    session = _pool_session(pools=[_pool(enabled=False)])

    result = load_capacity_pool_metadata(lambda: session, VIEWS)

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

    result = load_capacity_pool_metadata(lambda: session, VIEWS)

    assert set(result) == {"gpu-pool", "cpu-pool"}
    assert "pool_views" in result["gpu-pool"]
    assert "pool_views" not in result["cpu-pool"]
    assert result["cpu-pool"]["mechanism"] == "k8s"
