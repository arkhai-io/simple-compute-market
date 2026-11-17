"""A pool's reported times are the process time source's instants.

Library integration: the pool service over a real embedded SQLite database, with
the process source injected, so the times a pool's view reports are the source's
and never the database's clock.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

import injected_time
import pytest
from injected_time import InjectedTime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from market_resource_pools import ResourcePoolService
from market_resource_pools.db import Base
from market_resource_pools_contracts import PoolCreate, PoolResponse, PoolUpdate

#: The instant a pool is created at.
CREATED = 1794821400


class _NoConfigHandler:
    """A provider whose configuration is empty, so the pool is the only state."""

    provider = "test"

    def validate_config(self, config):
        return dict(config)

    def validate_config_problems(self, config):
        return dict(config), []

    def read_config(self, db, pool_id):
        return {}

    def read_config_for_execution(self, db, pool_id):
        return {}

    def replace_config(self, db, pool_id, config) -> None:
        return None


@pytest.fixture
def source() -> Iterator[InjectedTime]:
    """The process time source, injected at ``CREATED``; a test sets it forward."""
    before = injected_time.installed()
    installed = InjectedTime(start=CREATED)
    injected_time.install(installed)
    yield installed
    injected_time.install(before)


@pytest.fixture
def svc() -> ResourcePoolService:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return ResourcePoolService(
        session_factory=sessionmaker(bind=engine),
        handlers={"test": _NoConfigHandler()},
    )


def _instant(value: datetime) -> int:
    """A reported time as Unix seconds: SQLite returns it naive, in UTC."""
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return int(aware.timestamp())


def test_a_pool_s_view_reports_the_process_source_s_instants(
    svc: ResourcePoolService, source: InjectedTime
) -> None:
    created = PoolResponse.model_validate(
        svc.create_pool(
            PoolCreate(
                id="pool-1",
                label="Pool 1",
                provider="test",
                policy_tags={"advertisable_modes": [], "capacity_backing": "backed"},
                provider_config={},
            )
        )
    )
    assert _instant(created.created_at) == CREATED
    assert _instant(created.updated_at) == CREATED

    source.set(CREATED + 60)
    updated = PoolResponse.model_validate(svc.update_pool("pool-1", PoolUpdate(label="Pool One")))
    assert _instant(updated.created_at) == CREATED
    assert _instant(updated.updated_at) == CREATED + 60
