"""The relay tables over a real embedded database, built from the family's models.

File-backed SQLite with a connection per session, so independent sessions
contend as they do in a deployment. A suite with a schema of its own defines
its own ``session_factory``, which takes precedence over this one.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from compute_provisioning.relays.db import Base as RelaysBase


@pytest.fixture
def relay_engine(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'relays.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    RelaysBase.metadata.create_all(bind=engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def session_factory(relay_engine):
    return sessionmaker(bind=relay_engine)
