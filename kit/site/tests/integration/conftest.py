"""Fixtures the ledger's library integration tests share."""

from __future__ import annotations

from collections.abc import Iterator

import injected_time
import pytest
from injected_time import InjectedTime

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
