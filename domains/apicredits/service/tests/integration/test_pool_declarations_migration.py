"""Every pool the API-credits service holds declares advertisement and backing.

The service stores its own `default` Resource Pool outside pool
administration, so it seeds the declarations itself, migrates a database
written before they existed, and refuses to start with a pool that lacks them.

External boundary: SQLAlchemy against in-memory SQLite through the service's
real migration entry point.
"""

from __future__ import annotations

import json
import logging

import pytest
from market_resource_pools import (
    DEFAULT_POOL_ID,
    ResourcePool,
    resolve_pool_declarations,
)
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from db.database import run_migrations
from db.migrations import _migrate_pool_advertisement_and_backing


def _sqlite_memory_engine():
    return create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )



class TestPoolAdvertisementAndBacking:
    """Every pool this service holds declares what it advertises and that it
    is backed, and the service refuses to start with a pool that does not."""

    def test_fresh_bootstrap_seeds_a_declared_default_pool(self):
        engine = _sqlite_memory_engine()
        run_migrations(engine)

        with Session(engine) as session:
            tags = session.get(ResourcePool, DEFAULT_POOL_ID).policy_tags
        resolved = resolve_pool_declarations(tags)
        assert resolved.advertisable_modes == frozenset({"api_credits"})
        assert resolved.backed

    def test_previous_version_pool_is_migrated_and_opaque_values_clobbered(
        self, caplog,
    ):
        engine = _sqlite_memory_engine()
        run_migrations(engine)
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE resource_pools SET policy_tags=:tags"),
                {"tags": json.dumps({
                    "deliverable_modes": ["api_credits"],
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
            "deliverable_modes": ["api_credits"],
            "advertisable_modes": ["api_credits"],
            "capacity_backing": "backed",
        }
        assert (
            "Derived advertisement and backing for pool default: "
            "advertisable=api_credits backing=backed"
        ) in caplog.text

    def test_a_stored_pool_without_declarations_stops_startup(self):
        engine = _sqlite_memory_engine()
        run_migrations(engine)
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE resource_pools SET policy_tags=:tags"),
                {"tags": json.dumps({"deliverable_modes": ["api_credits"]})},
            )

        with pytest.raises(RuntimeError, match="pool 'default'"):
            run_migrations(engine)
