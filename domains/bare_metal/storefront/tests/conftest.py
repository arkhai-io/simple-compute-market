"""Fixtures every bare-metal storefront test may take."""

from __future__ import annotations

import time
from collections.abc import Iterator

import injected_time
import pytest
from injected_time import InjectedTime


@pytest.fixture
def injected_source() -> Iterator[InjectedTime]:
    """The process time source, injected two minutes behind the wall clock.

    The canonical client signs and verifies on the wall clock, so the
    storefront's instant stays inside the signing skew; being behind it, every
    time it stamps is told apart from a wall read. A test moves it forward
    rather than waiting.
    """
    before = injected_time.installed()
    source = InjectedTime(start=int(time.time()) - 120)
    injected_time.install(source)
    yield source
    injected_time.install(before)
