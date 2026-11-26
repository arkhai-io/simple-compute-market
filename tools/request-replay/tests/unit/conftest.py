from __future__ import annotations

import pytest

from tests.support import MemoryStore


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()
