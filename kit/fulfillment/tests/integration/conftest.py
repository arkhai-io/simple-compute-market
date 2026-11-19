"""Fixtures the aggregate's library integration tests share."""

from __future__ import annotations

from collections.abc import Iterator

import injected_time
import pytest
from injected_time import InjectedTime
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from market_fulfillment.migrations import BASELINE

#: The instant the injected source starts at.
INSTANT = 1794821400


@pytest.fixture
def source() -> Iterator[InjectedTime]:
    """The process time source, injected at ``INSTANT``; a test sets it forward."""
    before = injected_time.installed()
    installed = InjectedTime(start=INSTANT)
    injected_time.install(installed)
    yield installed
    injected_time.install(before)


@pytest.fixture
def sessions(tmp_path) -> sessionmaker[Session]:
    """Sessions on a file database holding the schema the aggregate's migration builds."""
    engine = create_engine(f"sqlite:///{tmp_path / 'fulfillment.db'}")
    with engine.begin() as connection:
        BASELINE.apply(connection)
    return sessionmaker(bind=engine)
