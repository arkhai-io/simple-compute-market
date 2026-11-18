"""The relay tables over a real embedded database, built from the family's models.

The schema is the resource-pool tables, which ``pool_relays`` references, the
host registry, whose members' addresses the management-route rule compares, and
the relay tables. File-backed SQLite with a connection per session, so
independent sessions contend as they do in a deployment. A suite with a schema
of its own defines its own ``session_factory``, which takes precedence over
this one.
"""

from __future__ import annotations

from collections.abc import Iterator

import injected_time
import pytest
from injected_time import InjectedTime
from market_resource_pools.db import Base as PoolsBase
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from compute_provisioning.hosts.db import Base as HostsBase
from compute_provisioning.relays.db import Base as RelaysBase


@pytest.fixture
def relay_engine(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'relays.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    PoolsBase.metadata.create_all(bind=engine)
    HostsBase.metadata.create_all(bind=engine)
    RelaysBase.metadata.create_all(bind=engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def session_factory(relay_engine):
    return sessionmaker(bind=relay_engine)


@pytest.fixture
def source() -> Iterator[InjectedTime]:
    """The process time source, injected at the wall instant it is installed;
    a test sets it forward to order events by the second."""
    before = injected_time.installed()
    installed = InjectedTime()
    injected_time.install(installed)
    yield installed
    injected_time.install(before)
