"""The read service's refusal of a query its wire form cannot express, before any read."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import sessionmaker

from eventing import EventService, EventServiceError
from tests.fixtures.kinds import Clock


@pytest.mark.parametrize("query", [{"limit": 0}, {"limit": 501}, {"severity": "urgent"},
                                   {"subject": "job"}, {"subject": "job:"}, {"reference": ":x"}])
def test_an_invalid_query_is_refused(query: dict[str, object]) -> None:
    # A session factory bound to no database: a refused query reads nothing.
    service = EventService(sessionmaker(), clock=Clock())

    with pytest.raises(EventServiceError) as refused:
        service.list_events(**query)  # type: ignore[arg-type]

    assert (refused.value.status_code, refused.value.code) == (422, "invalid_query")
