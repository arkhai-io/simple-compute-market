"""Resource-pool projection inventory, built from capacity declarations alone.

The fixtures below are frozen declaration sets covering a fungible pool and a
specific-resource bare-metal pool, projected with the inventory views
production composes. The projection of each must equal its frozen expectation
exactly: that equality is the contractual regression evidence for the
projection's shape. Each domain's own view rules are tested beside its
projection; this module proves the neutral rules, the pool context each view
is given, and the merge of views and their problems.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from bare_metal_provisioning_adapter.inventory_views import BareMetalPublicationViews
from compute_provisioning import InventoryViews, ResourceViews, compose_inventory_views
from vm_provisioning_adapter.db import AnsiblePoolConfig
from compute_provisioning_service.services.capacity_inventory import (
    load_capacity_pool_metadata,
    load_capacity_resource_inventory,
)
from arkhai_bare_metal.fixtures.publication_view import (
    validate_bare_metal_publication_view,
)
from market_resource_pools import ResourcePool
from market_resource_pools_contracts.backing import BACKED, UNBACKED
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


def _declared_pool(pool_id, *, provider="ansible", backing="backed", modes=("vm",)):
    """A stored pool row with both declarations, as every write requires."""
    return _pool(
        id=pool_id,
        provider=provider,
        policy_tags={
            "advertisable_modes": list(modes),
            "deliverable_modes": list(modes) if backing == "backed" else [],
            "capacity_backing": backing,
        },
    )


def _frozen_pools():
    """The pools the frozen declarations belong to."""
    return [
        _declared_pool("default"),
        _declared_pool("gpu-pool"),
        _declared_pool(
            "whole-host-pool", provider="bare_metal.ansible", modes=("bare_metal",)
        ),
        _declared_pool(
            "broker-pool",
            provider="bare_metal.ansible",
            backing="unbacked",
            modes=("bare_metal",),
        ),
    ]


def _project(declarations, views=VIEWS, pools=None):
    session = _pool_session(pools=_frozen_pools() if pools is None else pools)
    return load_capacity_resource_inventory(declarations, views, lambda: session)


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
    # An enabled publication in a backed pool naming no host has no specific
    # host to sell: it projects without the view, and says why.
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
    """What a problem says is the view's domain's, so the frozen shape carries
    the problem's place and leaves its wording to the domain's own tests."""
    projected = _project(SPECIFIC_RESOURCE_DECLARATIONS)
    (problem,) = projected[1].pop("publication_view_problems")["bare_metal.v2"]

    assert projected == SPECIFIC_RESOURCE_PROJECTION
    assert "host_id" in problem


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


def test_a_declaration_with_no_recorded_pool_is_not_projected(caplog):
    """Not into `default`, nor any other pool: the row is reported and left
    out, and the declarations around it project as they would without it."""
    with caplog.at_level("WARNING"):
        projected = _project(
            [
                _declaration(resource_id="vm-slice-1"),
                _declaration(resource_id="no-pool", pool_id=None),
                _declaration(resource_id="vm-slice-2"),
            ]
        )

    assert projected == _project(
        [_declaration(resource_id="vm-slice-1"), _declaration(resource_id="vm-slice-2")]
    )
    assert "'no-pool' records no pool and is not projected" in caplog.text


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
                backing=BACKED,
                physical_resource_id=resource["physical_resource_id"],
                pool_id=pool["pool_id"],
            )
            validated += 1
    assert validated == 3


# ---------------------------------------------------------------------------
# Pool context and view problems
# ---------------------------------------------------------------------------

def _views_and_problems(declarations):
    pools = resource_pool_projection(_project(declarations))
    return {
        resource["physical_resource_id"]: (
            (resource.get("publication_views") or {}).get("bare_metal.v2"),
            (resource.get("publication_view_problems") or {}).get("bare_metal.v2"),
        )
        for pool in pools
        for resource in pool["resources"]
    }


def test_an_unbacked_pools_host_less_declaration_projects_a_view_without_terms():
    projected = _views_and_problems(
        [_bare_metal_declaration(pool_id="broker-pool", host_id=None)]
    )

    view, problems = projected["physical-resource-1"]
    assert problems is None
    validate_bare_metal_publication_view(
        view, backing=UNBACKED, physical_resource_id="physical-resource-1",
        pool_id="broker-pool",
    )
    assert {"host_id", "physical_host_id", "access_methods", "available"}.isdisjoint(view)


def test_an_unbacked_pools_host_bearing_declaration_carries_no_terms_either():
    projected = _views_and_problems([_bare_metal_declaration(pool_id="broker-pool")])

    view, problems = projected["physical-resource-1"]
    assert problems is None
    assert {"host_id", "physical_host_id", "access_methods", "available"}.isdisjoint(view)


def test_a_malformed_declaration_projects_without_its_view_beside_its_pools_others():
    malformed = _bare_metal_declaration(resource_id="physical-resource-2")
    malformed["attributes"]["allocation_mode"] = "shareable"

    projected = _views_and_problems([_bare_metal_declaration(), malformed])

    view, problems = projected["physical-resource-2"]
    assert view is None and problems
    assert any("allocation_mode" in problem for problem in problems)
    assert projected["physical-resource-1"][0] is not None


def test_a_declaration_whose_pool_has_no_row_projects_no_view():
    (projected,) = _project([_bare_metal_declaration(pool_id="unknown-pool")])

    assert "publication_views" not in projected
    assert "publication_view_problems" not in projected


def test_each_pool_is_read_once_and_every_member_gets_its_context():
    seen = []

    class Recording:
        resource_view_ids = frozenset({"record.v1"})
        pool_view_ids: frozenset[str] = frozenset()
        consumed_attributes: frozenset[str] = frozenset()

        def resource_views(self, declaration, *, pool):
            seen.append((declaration["resource_id"], pool.pool_id, pool.provider,
                         pool.declarations.backing))
            return ResourceViews()

        def pool_views(self, db, *, pool_id, provider):
            return {}

    session = _pool_session(pools=_frozen_pools())
    load_capacity_resource_inventory(
        [
            _declaration(),
            _declaration(resource_id="vm-slice-2"),
            _bare_metal_declaration(pool_id="broker-pool"),
        ],
        compose_inventory_views([("record", Recording())]),
        lambda: session,
    )

    assert session.query.call_count == 1
    assert seen == [
        ("vm-slice-1", "gpu-pool", "ansible", BACKED),
        ("vm-slice-2", "gpu-pool", "ansible", BACKED),
        ("physical-resource-1", "broker-pool", "bare_metal.ansible", UNBACKED),
    ]


def test_a_pool_whose_declarations_do_not_resolve_gives_its_members_no_view():
    pools = [_pool(id="whole-host-pool", provider="bare_metal.ansible", policy_tags={})]

    (projected,) = _project([_bare_metal_declaration()], pools=pools)

    assert "publication_views" not in projected
    assert "publication_view_problems" not in projected


# ---------------------------------------------------------------------------
# A third domain
# ---------------------------------------------------------------------------

class _ThirdDomainViews:
    """A further compute domain's projection, which the service has never seen."""

    resource_view_ids = frozenset({"third.v1"})
    pool_view_ids = frozenset({"third.pool.v1"})
    consumed_attributes = frozenset({"third_config"})

    def resource_views(self, declaration, *, pool):
        config = (declaration.get("attributes") or {}).get("third_config")
        if not config:
            return ResourceViews()
        return ResourceViews(
            views={"third.v1": {"pool_id": pool.pool_id, "flavour": config["flavour"]}}
        )

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
