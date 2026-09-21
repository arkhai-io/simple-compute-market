"""Capacity declarations derived from legacy host capacity."""

from __future__ import annotations

import pytest
from market_site import CapacityDeclaration, CapacityLedgerService
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from compute_provisioning_service.db.database import create_session_factory, run_migrations
from compute_provisioning_service.db.models import DEFAULT_POOL_ID, Host, ResourcePool
from compute_provisioning_service.services.capacity_derivation import (
    LegacyHostCapacity,
    LegacyHostCapacityDerivation,
    plan_derived_declarations,
)


def _host(host_id: str = "kvm1", **overrides) -> LegacyHostCapacity:
    facts = {
        "host_id": host_id,
        "pool_id": DEFAULT_POOL_ID,
        "gpu_count": 4,
        "gpu_model": "H200",
        "enabled": True,
    }
    facts.update(overrides)
    return LegacyHostCapacity(**facts)


# ----------------------------------------------------------------------
# Planning
# ----------------------------------------------------------------------


def test_a_host_with_legacy_capacity_plans_the_documented_declaration():
    plan = plan_derived_declarations(
        [_host(pool_id="gpu-pool", enabled=False)],
        declared_host_ids=set(),
        existing_resource_ids=set(),
    )

    assert plan.skipped == ()
    assert plan.declarations == (
        CapacityDeclaration(
            resource_id="kvm1",
            host_id="kvm1",
            pool_id="gpu-pool",
            resource_type="compute.gpu",
            capacity={"gpu_count": 4},
            attributes={"gpu_model": "H200"},
            enabled=False,
        ),
    )


def test_a_host_without_a_recorded_model_gets_no_model_attribute():
    (declaration,) = plan_derived_declarations(
        [_host(gpu_model=None)], declared_host_ids=set(), existing_resource_ids=set()
    ).declarations

    assert declaration.attributes == {}


@pytest.mark.parametrize("gpu_count", [0, -1])
def test_a_host_without_gpus_is_not_derived(gpu_count):
    plan = plan_derived_declarations(
        [_host(gpu_count=gpu_count)], declared_host_ids=set(), existing_resource_ids=set()
    )

    assert plan.declarations == plan.skipped == ()


def test_a_host_a_declaration_already_names_is_not_derived():
    plan = plan_derived_declarations(
        [_host()], declared_host_ids={"kvm1"}, existing_resource_ids={"listing-1"}
    )

    assert plan.declarations == plan.skipped == ()


def test_a_host_whose_id_another_declaration_uses_is_skipped_and_reported():
    plan = plan_derived_declarations(
        [_host()], declared_host_ids=set(), existing_resource_ids={"kvm1"}
    )

    assert plan.declarations == ()
    ((host_id, reason),) = plan.skipped
    assert host_id == "kvm1"
    assert "resource id" in reason


# ----------------------------------------------------------------------
# Deriving into the ledger
# ----------------------------------------------------------------------


@pytest.fixture
def stores():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    run_migrations(
        engine,
        default_playbook_path="/configured/playbook.yaml",
        default_inventory_group="kvm_hosts",
    )
    # The service's own factory, which does not autoflush: deriving must
    # see hosts its caller has added but not flushed.
    session_factory = create_session_factory(engine)
    ledger = CapacityLedgerService(
        session_factory,
        unit_claim_keys=("units", "gpu_count"),
        mirror_dimension="gpu_count",
    )
    with session_factory() as db, db.begin():
        db.add(ResourcePool(
            id="gpu-pool", label="GPU pool", provider="ansible", enabled=True,
            policy_tags={"deliverable_modes": ["vm"]},
        ))
        for host_id, gpus, pool in (("kvm1", 4, "gpu-pool"), ("kvm2", 0, DEFAULT_POOL_ID)):
            db.add(Host(
                host_id=host_id, ssh_host="10.0.0.1", ssh_user="root",
                ssh_key_value="/key", gpu_count=gpus, gpu_model="H200",
                pool_id=pool, enabled=True,
            ))
    return session_factory, ledger


def _derive(stores, host_ids=None) -> list[str]:
    session_factory, ledger = stores
    with session_factory() as db, db.begin():
        return LegacyHostCapacityDerivation(ledger).derive_in_session(db, host_ids)


def _resources(ledger: CapacityLedgerService) -> dict[str, dict]:
    return {row["resource_id"]: row for row in ledger.list_resources()}


def test_deriving_declares_capacity_for_hosts_with_gpus_only(stores):
    _, ledger = stores

    assert _derive(stores) == ["kvm1"]

    resource = _resources(ledger)["kvm1"]
    assert resource["host_id"] == "kvm1"
    assert resource["pool_id"] == "gpu-pool"
    assert resource["capacity"] == {"gpu_count": 4}
    assert resource["attributes"] == {"gpu_model": "H200"}


def test_deriving_again_changes_nothing(stores):
    _, ledger = stores
    _derive(stores)
    _, version = ledger.events_after(0)

    assert _derive(stores) == []
    assert ledger.events_after(0)[1] == version


def test_a_declaration_under_another_resource_id_keeps_the_host_declared(stores):
    """The e2e shape: the listing's id is the resource id and the host is
    named by ``host_id``. Deriving must see it and add nothing."""
    _, ledger = stores
    ledger.register_resource(
        resource_id="listing-1", pool_id="gpu-pool", host_id="kvm1",
        capacity={"gpu_count": 1},
    )

    assert _derive(stores) == []
    assert set(_resources(ledger)) == {"listing-1"}


def test_an_operator_declaration_that_disagrees_is_kept_as_declared(stores):
    _, ledger = stores
    ledger.register_resource(
        resource_id="kvm1", pool_id="gpu-pool", host_id="kvm1",
        capacity={"gpu_count": 2, "ram_gb": 256},
    )

    assert _derive(stores) == []
    assert _resources(ledger)["kvm1"]["capacity"] == {"gpu_count": 2, "ram_gb": 256}


def test_a_host_whose_id_is_taken_is_left_and_the_declaration_kept(stores, caplog):
    _, ledger = stores
    ledger.register_resource(
        resource_id="kvm1", pool_id=DEFAULT_POOL_ID, capacity={"units": 9},
    )

    assert _derive(stores) == []
    assert _resources(ledger)["kvm1"]["capacity"] == {"units": 9}
    assert "kvm1 not derived" in caplog.text


def test_deriving_is_limited_to_the_hosts_named(stores):
    assert _derive(stores, ["kvm2"]) == []
    assert _derive(stores, []) == []
    assert _derive(stores, ["kvm1"]) == ["kvm1"]


def test_hosts_added_but_not_flushed_are_derived(stores):
    """The caller upserts hosts and derives in one transaction; its pending
    rows must be visible to the derivation."""
    session_factory, ledger = stores
    with session_factory() as db, db.begin():
        db.add(Host(
            host_id="kvm3", ssh_host="10.0.0.3", ssh_user="root",
            ssh_key_value="/key", gpu_count=2, pool_id=DEFAULT_POOL_ID,
            enabled=True,
        ))
        derived = LegacyHostCapacityDerivation(ledger).derive_in_session(db, ["kvm3"])

    assert derived == ["kvm3"]
    assert _resources(ledger)["kvm3"]["capacity"] == {"gpu_count": 2}
