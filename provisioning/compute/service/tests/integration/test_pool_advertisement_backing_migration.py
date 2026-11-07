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
from market_resource_pools_contracts.backing import BACKED
from market_resource_pools import DEFAULT_POOL_ID, ResourcePool
from market_resource_pools_contracts import (
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
    run_migrations(engine)
    return engine


def _add_default_pool(engine, policy_tags: dict) -> None:
    """Store the ``default`` pool an older database holds."""
    with Session(engine) as db, db.begin():
        db.add(ResourcePool(
            id=DEFAULT_POOL_ID,
            label="Default Pool",
            provider="ansible",
            enabled=True,
            policy_tags=policy_tags,
        ))


def _write_previous_version_pools(engine) -> None:
    """Store pools in the shape the previous version stored."""
    _add_default_pool(engine, {"deliverable_modes": ["vm"]})
    with Session(engine) as db, db.begin():
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
        assert resolved.backing is BACKED
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
    _add_default_pool(engine, {"deliverable_modes": "vm"})

    with pytest.raises(SchemaDriftError, match="pool 'default' policy_tags"):
        _migrate_pool_advertisement_and_backing(engine)

    assert _tags(engine)[DEFAULT_POOL_ID] == {"deliverable_modes": "vm"}
