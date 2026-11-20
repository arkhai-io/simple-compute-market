"""Test bootstrap: environment overrides land before any config import."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator

import injected_time
import pytest
from injected_time import InjectedTime

# Registry fan-out stays local in unit tests; the settings singleton is
# built on first config import, so these must be set here.
os.environ.setdefault("APICREDITS_STOREFRONT_ENABLE_REGISTRY_DISCOVERY", "false")
os.environ.setdefault("APICREDITS_STOREFRONT_DB_PATH", "/tmp/apicredits-storefront-test.db")


@pytest.fixture
def injected_source() -> Iterator[InjectedTime]:
    """The process time source, injected two minutes behind the wall clock.

    The canonical client signs and verifies on the wall clock, so the
    storefront's instant stays inside the signing skew; being behind it, every
    time it stamps is told apart from a wall read.
    """
    before = injected_time.installed()
    source = InjectedTime(start=int(time.time()) - 120)
    injected_time.install(source)
    yield source
    injected_time.install(before)
