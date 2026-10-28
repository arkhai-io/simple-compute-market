"""VM's tables over a real embedded database, built from VM's own models.

The schema is the resource-pool tables, which ``ansible_pool_configs``
references, and VM's: what VM's metadata declares, constraints and indexes
included, and nothing a composing service adds. File-backed SQLite with a
connection per session, so independent sessions contend as they do in a
deployment.
"""

from __future__ import annotations

import pytest
from market_resource_pools.db import Base as PoolsBase
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import sessionmaker

from vm_provisioning_adapter.db import Base as VmBase


def create_vm_schema(engine: Engine) -> None:
    """Create the resource-pool tables, then VM's, which reference them."""

    PoolsBase.metadata.create_all(bind=engine)
    VmBase.metadata.create_all(bind=engine)


@pytest.fixture
def vm_engine(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'vm.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    create_vm_schema(engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def session_factory(vm_engine):
    return sessionmaker(bind=vm_engine)
