from __future__ import annotations

import pytest
from request_replay.ddl import statements

from market_authenticated_requests import REPLAY_TABLE, replay_table_statements


@pytest.mark.parametrize("dialect", ["sqlite", "postgresql"])
def test_the_kit_publishes_the_component_statements_for_its_table(dialect: str) -> None:
    assert replay_table_statements(dialect) == statements(dialect, table=REPLAY_TABLE)
