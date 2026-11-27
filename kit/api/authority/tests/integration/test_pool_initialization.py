"""Every pool the authority holds declares advertisement and backing.

The authority seeds the profile's Resource Pool outside pool administration,
with the declarations the profile states, and refuses to start with a pool
that lacks them. No migration writes a pool.

External boundary: SQLAlchemy against file-backed SQLite in a temp directory,
migrated by the authority's chain and initialised as a root's startup does.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from market_resource_pools import DEFAULT_POOL_ID, ResourcePool
from market_resource_pools_contracts import read_site_declarations, resolve_pool_declarations
from market_resource_pools_contracts.backing import BACKED
from market_site.projections import resource_pool_projection
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from arkhai_api_authority import (
    create_db_engine,
    create_session_factory,
    initialize,
    load_pool_directory,
    migrate_database,
)

from tests.integration.profiles import CHAIN, PROFILE


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'authority.db'}", is_sqlite=True)
    migrate_database(engine, CHAIN)
    yield engine
    engine.dispose()


class TestPoolAdvertisementAndBacking:
    """Every pool the authority holds declares what it advertises and that it
    is backed, and initialization refuses a pool that does not."""

    def test_the_chain_writes_no_pool(self, engine):
        with Session(engine) as session:
            assert session.query(ResourcePool).all() == []

    def test_initialization_seeds_the_profiles_pool_with_its_declarations(self, engine):
        initialize(engine, PROFILE)
        initialize(engine, PROFILE)

        with Session(engine) as session:
            (pool,) = session.query(ResourcePool).all()
            tags, provider, label = pool.policy_tags, pool.provider, pool.label
        resolved = resolve_pool_declarations(tags)
        assert resolved.advertisable_modes == PROFILE.advertisable_modes == frozenset({"example"})
        assert resolved.backing is BACKED
        assert (provider, label) == (PROFILE.pool_provider, PROFILE.pool_label)

    def test_a_stored_pool_is_kept_as_it_is_on_a_later_start(self, engine):
        initialize(engine, PROFILE)
        with engine.begin() as connection:
            connection.execute(text("UPDATE resource_pools SET label='Renamed' WHERE id='default'"))

        initialize(engine, PROFILE)

        with Session(engine) as session:
            assert session.get(ResourcePool, PROFILE.pool_id).label == "Renamed"

    def test_a_stored_pool_without_declarations_stops_startup(self, engine):
        initialize(engine, PROFILE)
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE resource_pools SET policy_tags=:tags"),
                {"tags": json.dumps({"deliverable_modes": ["example"]})},
            )

        with pytest.raises(RuntimeError, match="pool 'default'"):
            initialize(engine, PROFILE)


def test_the_resource_pool_projection_carries_the_system_pools_declarations(engine):
    # A storefront binds a listing with the backing its quota resource's pool
    # declares, read from this projection.
    initialize(engine, PROFILE)

    rows = resource_pool_projection(
        [{"resource_id": "quota-1", "pool_id": DEFAULT_POOL_ID, "capacity": {"units": 5}}],
        pool_metadata=load_pool_directory(create_session_factory(engine)),
    )
    reading = read_site_declarations(rows)

    pool = reading.resolved[DEFAULT_POOL_ID]
    assert pool.backing is BACKED
    assert pool.advertises("example") and pool.enabled
