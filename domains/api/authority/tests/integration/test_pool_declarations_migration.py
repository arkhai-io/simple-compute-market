"""Every pool the authority holds declares advertisement and backing.

The authority seeds the profile's Resource Pool outside pool administration,
with the declarations the profile states, migrates a database written before
they existed, and refuses to start with a pool that lacks them.

External boundary: SQLAlchemy against in-memory SQLite through the real
migration and initialization entry points.
"""

from __future__ import annotations

import json
import logging

import pytest
from market_resource_pools_contracts.backing import BACKED
from market_resource_pools import DEFAULT_POOL_ID, ResourcePool, read_site_declarations
from market_site.projections import resource_pool_projection
from market_resource_pools_contracts import resolve_pool_declarations
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from arkhai_api_authority import create_session_factory, initialize, load_pool_directory, run_migrations
from arkhai_api_authority.migrations import _migrate_pool_advertisement_and_backing

from tests.integration.profiles import PROFILE


def _sqlite_memory_engine():
    return create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )



class TestPoolAdvertisementAndBacking:
    """Every pool the authority holds declares what it advertises and that it
    is backed, and initialization refuses a pool that does not."""

    def test_fresh_bootstrap_seeds_the_profiles_pool_with_its_declarations(self):
        engine = _sqlite_memory_engine()
        run_migrations(engine)
        initialize(engine, PROFILE)

        with Session(engine) as session:
            pool = session.get(ResourcePool, PROFILE.pool_id)
            tags, provider, label = pool.policy_tags, pool.provider, pool.label
        resolved = resolve_pool_declarations(tags)
        assert resolved.advertisable_modes == PROFILE.advertisable_modes == frozenset({"example"})
        assert resolved.backing is BACKED
        assert (provider, label) == (PROFILE.pool_provider, PROFILE.pool_label)

    def test_a_stored_pool_is_kept_as_it_is_on_a_later_start(self):
        engine = _sqlite_memory_engine()
        run_migrations(engine)
        initialize(engine, PROFILE)
        with engine.begin() as connection:
            connection.execute(text("UPDATE resource_pools SET label='Renamed' WHERE id='default'"))

        initialize(engine, PROFILE)

        with Session(engine) as session:
            assert session.get(ResourcePool, PROFILE.pool_id).label == "Renamed"

    def test_previous_version_pool_is_migrated_and_opaque_values_clobbered(
        self, caplog,
    ):
        engine = _sqlite_memory_engine()
        run_migrations(engine)
        initialize(engine, PROFILE)
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE resource_pools SET policy_tags=:tags"),
                {"tags": json.dumps({
                    "deliverable_modes": ["example"],
                    "capacity_backing": "unbacked",
                })},
            )

        caplog.set_level(logging.INFO)
        _migrate_pool_advertisement_and_backing(engine)

        with engine.begin() as connection:
            stored = json.loads(connection.execute(
                text("SELECT policy_tags FROM resource_pools WHERE id='default'")
            ).scalar())
        assert stored == {
            "deliverable_modes": ["example"],
            "advertisable_modes": ["example"],
            "capacity_backing": "backed",
        }
        assert (
            "Derived advertisement and backing for pool default: "
            "advertisable=example backing=backed"
        ) in caplog.text

    def test_a_stored_pool_without_declarations_stops_startup(self):
        engine = _sqlite_memory_engine()
        run_migrations(engine)
        initialize(engine, PROFILE)
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE resource_pools SET policy_tags=:tags"),
                {"tags": json.dumps({"deliverable_modes": ["example"]})},
            )

        with pytest.raises(RuntimeError, match="pool 'default'"):
            initialize(engine, PROFILE)


def test_the_resource_pool_projection_carries_the_system_pools_declarations():
    # A storefront binds a credit listing with the backing its quota
    # resource's pool declares, read from this projection.
    engine = _sqlite_memory_engine()
    run_migrations(engine)
    initialize(engine, PROFILE)

    rows = resource_pool_projection(
        [{"resource_id": "quota-1", "pool_id": DEFAULT_POOL_ID, "capacity": {"units": 5}}],
        pool_metadata=load_pool_directory(create_session_factory(engine)),
    )
    reading = read_site_declarations(rows)

    pool = reading.resolved[DEFAULT_POOL_ID]
    assert pool.backing is BACKED
    assert pool.advertises("example") and pool.enabled
