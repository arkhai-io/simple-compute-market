"""The pool facts the site authority's port reads, from stored pools.

Library integration: ``ResourcePoolFacts`` over a real SQLite database holding
the table its baseline migration builds, read in the caller's session.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from market_resource_pools import ResourcePool, ResourcePoolFacts, StoredPoolFacts
from market_resource_pools.migrations import BASELINE

REQUIREMENT = {"bare_metal.ansible": True, "api.quota": False}


@pytest.fixture
def db(tmp_path) -> Iterator[Session]:
    engine = create_engine(f"sqlite:///{tmp_path / 'pools.db'}")
    with engine.begin() as connection:
        BASELINE.apply(connection)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _pool(db: Session, pool_id="metal", *, provider="bare_metal.ansible",
          enabled=True, policy_tags=None) -> None:
    db.add(
        ResourcePool(
            id=pool_id,
            label=pool_id,
            provider=provider,
            enabled=enabled,
            policy_tags={"deliverable_modes": ["vm", "bare_metal"]}
            if policy_tags is None
            else policy_tags,
        )
    )
    db.commit()


def test_a_pool_whose_provider_needs_a_host(db):
    _pool(db)

    facts = ResourcePoolFacts(REQUIREMENT).pool_facts(db, "metal")

    assert facts == StoredPoolFacts(
        exists=True,
        enabled=True,
        deliverable_modes=frozenset({"vm", "bare_metal"}),
        needs_host=True,
    )


def test_a_disabled_pool_keeps_its_declared_modes(db):
    _pool(db, enabled=False)

    facts = ResourcePoolFacts(REQUIREMENT).pool_facts(db, "metal")

    assert (facts.exists, facts.enabled) == (True, False)
    assert facts.deliverable_modes == frozenset({"vm", "bare_metal"})


def test_a_provider_the_requirement_says_needs_no_host(db):
    _pool(db, provider="api.quota")

    assert ResourcePoolFacts(REQUIREMENT).pool_facts(db, "metal").needs_host is False


def test_with_no_requirement_no_pool_needs_a_host(db):
    _pool(db)

    assert ResourcePoolFacts().pool_facts(db, "metal").needs_host is False


def test_a_provider_the_requirement_does_not_name_needs_a_host(db):
    _pool(db, provider="unregistered")

    assert ResourcePoolFacts(REQUIREMENT).pool_facts(db, "metal").needs_host is True


def test_a_pool_declaring_no_deliverable_mode_reports_an_empty_set(db):
    _pool(db, policy_tags={})

    facts = ResourcePoolFacts(REQUIREMENT).pool_facts(db, "metal")

    assert facts.deliverable_modes == frozenset()


@pytest.mark.parametrize(
    ("requirement", "needs_host"), [(REQUIREMENT, True), ({}, True), (None, False)]
)
def test_a_missing_pool(db, requirement, needs_host):
    facts = ResourcePoolFacts(requirement).pool_facts(db, "absent")

    assert facts == StoredPoolFacts(
        exists=False,
        enabled=False,
        deliverable_modes=None,
        needs_host=needs_host,
    )


def test_an_unreadable_deliverable_declaration_reads_as_unreadable(db):
    # Every pool write refuses this declaration, so the row is written past
    # the service, as a stored row from outside its validation would be.
    _pool(db, policy_tags={"deliverable_modes": "vm"})

    facts = ResourcePoolFacts(REQUIREMENT).pool_facts(db, "metal")

    assert facts.exists is True
    assert facts.deliverable_modes is None


def test_the_read_sees_the_callers_own_uncommitted_write(db):
    _pool(db)
    pool = db.get(ResourcePool, "metal")
    pool.enabled = False
    pool.policy_tags = {"deliverable_modes": ["vm"]}
    db.flush()

    facts = ResourcePoolFacts(REQUIREMENT).pool_facts(db, "metal")

    assert facts.enabled is False
    assert facts.deliverable_modes == frozenset({"vm"})
    db.rollback()
    assert ResourcePoolFacts(REQUIREMENT).pool_facts(db, "metal").enabled is True
