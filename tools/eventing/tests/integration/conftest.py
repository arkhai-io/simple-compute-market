from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from eventing import Recorder, Source
from tests.fixtures.kinds import Clock, Store, catalogue, open_store


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    yield from open_store(tmp_path / "events.db")


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def recorder(clock: Clock) -> Recorder:
    return Recorder(catalogue(), source=Source(service="jobs", instance="a"), clock=clock)
