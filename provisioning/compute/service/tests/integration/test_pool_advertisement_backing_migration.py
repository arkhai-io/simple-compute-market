"""Migration declares advertisement and backing on every existing pool.

A database written before these declarations existed holds pools whose only
mode declaration was their deliverable set. Migration must leave each pool
advertising exactly what it delivered and remaining admissible, so an upgrade
changes nothing observable.

External boundary: SQLAlchemy against in-memory SQLite, migrated through the
real migration entry point, then rewritten into the previous version's shape.
"""

from __future__ import annotations

import logging

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from compute_provisioning_service.db.database import run_migrations
from compute_provisioning_service.db.migrations import (
    SchemaDriftError,
    _migrate_pool_advertisement_and_backing,
)
from market_resource_pools import (
    DEFAULT_POOL_ID,
    ResourcePool,
    declared_deliverable_modes,
    pool_delivers_offering_mode,
    resolve_pool_declarations,
)


def _engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    run_migrations(
        engine,
        default_playbook_path="/playbooks/vm-operations.yaml",
        default_inventory_group="kvm_hosts",
    )
    return engine


def _write_previous_version_pools(engine) -> None:
    """Rewrite every pool into the shape the previous version stored."""
    with Session(engine) as db, db.begin():
        default = db.get(ResourcePool, DEFAULT_POOL_ID)
        default.policy_tags = {"deliverable_modes": ["vm"]}
        db.add_all((
            ResourcePool(
                id="single-mode",
                label="Single mode",
                provider="bare_metal.ansible",
                enabled=True,
                policy_tags={"deliverable_modes": ["bare_metal"], "region": "test"},
            ),
            ResourcePool(
                id="proves-nothing",
                label="Proves nothing",
                provider="ansible",
                enabled=False,
                policy_tags={"deliverable_modes": []},
            ),
            ResourcePool(
                id="opaque",
                label="Opaque prior values",
                provider="ansible",
                enabled=True,
                policy_tags={
                    "deliverable_modes": ["vm"],
                    "advertisable_modes": "everything",
                    "capacity_backing": "unbacked",
                },
            ),
        ))


def _tags(engine) -> dict[str, dict]:
    with Session(engine) as db:
        return {
            pool.id: dict(pool.policy_tags)
            for pool in db.query(ResourcePool).order_by(ResourcePool.id)
        }


def test_fresh_bootstrap_declares_the_default_pool():
    tags = _tags(_engine())[DEFAULT_POOL_ID]

    assert tags["advertisable_modes"] == tags["deliverable_modes"]
    assert tags["capacity_backing"] == "backed"


def test_previous_version_pools_advertise_what_they_delivered_and_stay_backed(caplog):
    engine = _engine()
    _write_previous_version_pools(engine)
    before = _tags(engine)

    caplog.set_level(logging.INFO)
    _migrate_pool_advertisement_and_backing(engine)
    after = _tags(engine)

    assert set(after) == set(before)
    for pool_id, old in before.items():
        new = after[pool_id]
        resolved = resolve_pool_declarations(new)
        # The advertising surface under the previous contract was the
        # deliverable set; admission read nothing else.
        assert resolved.advertisable_modes == declared_deliverable_modes(old)
        assert resolved.backed
        assert declared_deliverable_modes(new) == declared_deliverable_modes(old)
        for mode in ("vm", "bare_metal", "api_credits"):
            assert pool_delivers_offering_mode(new, mode) == pool_delivers_offering_mode(
                old, mode
            )
        # Every other tag survives untouched.
        assert {
            k: v for k, v in new.items()
            if k not in ("advertisable_modes", "capacity_backing")
        } == {
            k: v for k, v in old.items()
            if k not in ("advertisable_modes", "capacity_backing")
        }

    assert after["opaque"]["advertisable_modes"] == ["vm"]
    assert after["opaque"]["capacity_backing"] == "backed"
    assert after["proves-nothing"]["advertisable_modes"] == []
    assert after["single-mode"]["advertisable_modes"] == ["bare_metal"]
    for pool_id, advertisable in (
        ("default", "vm"),
        ("opaque", "vm"),
        ("proves-nothing", "none"),
        ("single-mode", "bare_metal"),
    ):
        assert (
            f"Derived advertisement and backing for pool {pool_id}: "
            f"advertisable={advertisable} backing=backed"
        ) in caplog.text


def test_rerun_is_idempotent():
    engine = _engine()
    _write_previous_version_pools(engine)
    _migrate_pool_advertisement_and_backing(engine)
    first = _tags(engine)

    _migrate_pool_advertisement_and_backing(engine)

    assert _tags(engine) == first


def test_malformed_deliverable_set_is_drift_not_a_guess():
    engine = _engine()
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE resource_pools SET policy_tags=:tags WHERE id=:pool_id"),
            {"tags": '{"deliverable_modes": "vm"}', "pool_id": DEFAULT_POOL_ID},
        )

    with pytest.raises(SchemaDriftError, match="pool 'default' policy_tags"):
        _migrate_pool_advertisement_and_backing(engine)

    assert _tags(engine)[DEFAULT_POOL_ID] == {"deliverable_modes": "vm"}
