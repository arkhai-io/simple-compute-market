"""Every pool the API-credits service holds declares advertisement and backing.

The service stores its own `default` Resource Pool outside pool
administration, so its startup seeds the pool with its declarations, and
refuses to start with a pool that lacks them. No migration writes a pool.

External boundary: SQLAlchemy against file-backed SQLite in a temp directory,
migrated by the service's migration chain and initialised by the service's
startup database step; no application.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from market_resource_pools_contracts.backing import BACKED
from market_resource_pools import DEFAULT_POOL_ID, ResourcePool, read_site_declarations
from market_site.projections import resource_pool_projection
from market_resource_pools_contracts import resolve_pool_declarations
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from apicredits_service.db.database import (
    create_db_engine,
    create_session_factory,
    initialise_database,
    load_pool_directory,
    migrate_database,
)


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'credits.db'}", is_sqlite=True)
    migrate_database(engine)
    yield engine
    engine.dispose()


class TestPoolAdvertisementAndBacking:
    """Every pool this service holds declares what it advertises and that it
    is backed, and the service refuses to start with a pool that does not."""

    def test_startup_seeds_a_declared_default_pool(self, engine):
        initialise_database(engine)

        with Session(engine) as session:
            tags = session.get(ResourcePool, DEFAULT_POOL_ID).policy_tags
        resolved = resolve_pool_declarations(tags)
        assert resolved.advertisable_modes == frozenset({"api_credits"})
        assert resolved.backing is BACKED

    def test_a_stored_pool_without_declarations_stops_startup(self, engine):
        initialise_database(engine)
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE resource_pools SET policy_tags=:tags"),
                {"tags": json.dumps({"deliverable_modes": ["api_credits"]})},
            )

        with pytest.raises(RuntimeError, match="pool 'default'"):
            initialise_database(engine)


def test_the_resource_pool_projection_carries_the_system_pools_declarations(engine):
    # A storefront binds a credit listing with the backing its quota
    # resource's pool declares, read from this projection.
    initialise_database(engine)

    rows = resource_pool_projection(
        [{"resource_id": "quota-1", "pool_id": DEFAULT_POOL_ID, "capacity": {"units": 5}}],
        pool_metadata=load_pool_directory(create_session_factory(engine)),
    )
    reading = read_site_declarations(rows)

    pool = reading.resolved[DEFAULT_POOL_ID]
    assert pool.backing is BACKED
    assert pool.advertises("api_credits") and pool.enabled
