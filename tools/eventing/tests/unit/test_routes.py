"""Routes: the conditions a route may hold, the columns it may name, and the events it
selects."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from eventing import ENVELOPE_VERSION, Envelope, Reference, Route, RouteRefused, Routes, Source
from tests.fixtures.kinds import catalogue

ENABLED = {"ops-push", "ops-email"}


def event(kind: str = "jobs.finished", *, attributes: dict[str, Any] | None = None,
          related: tuple[Reference, ...] = (), severity: str = "info",
          event_id: str = "01JDX9R6Q7Z3K2W8P4M5N6B7C8") -> Envelope:
    return Envelope(
        envelope_version=ENVELOPE_VERSION, id=event_id, kind=kind, kind_version=1,
        data_schema=f"urn:event:{kind}:1", source=Source(service="jobs", instance="a"),
        sequence=7, occurred_at=datetime(2026, 11, 25, 17, 42, tzinfo=timezone.utc),
        severity=severity, subject=Reference(type="job", id="j-1"), related=related,  # type: ignore[arg-type]
        attributes=attributes or {}, summary="s", details={},
    )


def routes(*conditions: str, destinations: tuple[str, ...] = ("ops-push",)) -> Routes:
    return Routes([Route(f"r{i}", where, destinations) for i, where in enumerate(conditions)],
                  catalogue(), ENABLED)


def selects(condition: str, envelope: Envelope) -> bool:
    return bool(routes(condition).select(envelope))


def test_a_route_selects_long_jobs_and_not_short_ones() -> None:
    long_jobs = routes("kind = 'jobs.finished' AND duration_seconds >= 1800")

    assert long_jobs.select(event(attributes={"duration_seconds": 2832})) == {"ops-push"}
    assert long_jobs.select(event(attributes={"duration_seconds": 40})) == frozenset()


def test_a_route_selects_every_event_naming_a_reference_whatever_its_kind() -> None:
    by_depot = routes("id IN (SELECT event_id FROM related WHERE type = 'depot' AND id = 'd-02')")
    depot = (Reference(type="depot", id="d-02"),)

    assert by_depot.select(event(related=depot)) == {"ops-push"}
    assert by_depot.select(event("orders.shipment_delayed", related=depot)) == {"ops-push"}
    assert by_depot.select(event(related=(Reference(type="depot", id="d-03"),))) == frozenset()
    assert by_depot.select(event()) == frozenset()


@pytest.mark.parametrize(("condition", "expected"), [
    ("kind LIKE 'jobs.%'", True),
    ("kind LIKE 'orders.%'", False),
    ("status IN ('failed', 'cancelled')", True),
    ("status IN ('succeeded')", False),
    ("carrier IS NULL", True),
    ("NOT carrier IS NULL", False),
    ("carrier IS NOT NULL", False),
    ("NOT (status = 'succeeded')", True),
    ("TRUE", True),
    ("severity_rank >= 1", True),
    ("EXISTS (SELECT 1 FROM related WHERE related.event_id = event.id AND related.type = 'depot')", True),
    ("EXISTS (SELECT 1 FROM related WHERE related.event_id = event.id AND related.type = 'order')", False),
    ("id IN (SELECT event_id FROM related WHERE type = 'depot')", True),
    ("duration_seconds > -1", True),
])
def test_each_form_a_route_may_hold_is_evaluated(condition: str, expected: bool) -> None:
    failed = event(attributes={"status": "failed", "duration_seconds": 10}, severity="warning",
                   related=(Reference(type="depot", id="d-02"),))

    assert selects(condition, failed) is expected


def test_an_attribute_the_event_does_not_carry_selects_nothing() -> None:
    assert not selects("duration_seconds >= 1800", event("notes.added"))


def test_a_route_names_every_destination_of_every_route_selecting_the_event() -> None:
    both = Routes([Route("a", "TRUE", ("ops-push",)), Route("b", "kind = 'jobs.finished'", ("ops-email",)),
                   Route("c", "FALSE", ("ops-email",))], catalogue(), ENABLED)

    assert both.matching(event()) == ("a", "b")
    assert both.select(event()) == {"ops-push", "ops-email"}


def test_a_route_naming_an_unknown_column_is_refused_naming_route_and_column() -> None:
    with pytest.raises(RouteRefused) as refused:
        Routes([Route("long-jobs", "kind = 'jobs.finished' AND duraton_seconds > 5", ("ops-push",))],
               catalogue(), ENABLED)

    assert refused.value.route == "long-jobs"
    assert "duraton_seconds" in str(refused.value)


@pytest.mark.parametrize("condition", [
    "id IN (SELECT event_id FROM related WHERE kind_of = 'x')",
    "EXISTS (SELECT 1 FROM related WHERE related.kind = 'x')",
    "event.missing = 1",
])
def test_an_unknown_column_in_a_subquery_or_qualified_is_refused(condition: str) -> None:
    with pytest.raises(RouteRefused, match="names column"):
        routes(condition)


@pytest.mark.parametrize("condition", ["related.type = 'depot'", "orders.kind = 'x'"])
def test_a_column_qualified_by_a_table_the_condition_may_not_read_is_refused(condition: str) -> None:
    with pytest.raises(RouteRefused, match="of no table it may read"):
        routes(condition)


@pytest.mark.parametrize("condition", ["DROP TABLE events", "DELETE FROM related",
                                       "SELECT * FROM event"])
def test_a_route_holding_a_statement_is_refused_naming_the_route(condition: str) -> None:
    with pytest.raises(RouteRefused, match="is not a condition") as refused:
        Routes([Route("bad", condition, ("ops-push",))], catalogue(), ENABLED)

    assert refused.value.route == "bad"


@pytest.mark.parametrize(("condition", "reason"), [
    ("kind = 'x'; DROP TABLE events", "more than one statement"),
    ("lower(kind) = 'x'", "holds LOWER"),
    ("duration_seconds + 1 > 5", "holds ADD"),
    ("duration_seconds BETWEEN 1 AND 5", "holds BETWEEN"),
    ("id IN (SELECT event_id FROM events)", "reads table events"),
    ("id IN (SELECT event_id FROM related r)", "holds TABLEALIAS"),
    ("id IN (SELECT event_id FROM related LIMIT 1)", "holds LIMIT"),
    ("kind = ", "does not parse"),
    ("", "is empty"),
    ("  ;", "is empty"),
])
def test_a_condition_holding_anything_else_is_refused(condition: str, reason: str) -> None:
    with pytest.raises(RouteRefused, match=reason):
        routes(condition)


def test_a_route_naming_a_destination_not_enabled_is_refused() -> None:
    with pytest.raises(RouteRefused, match="not enabled: ops-pager") as refused:
        Routes([Route("held", "severity = 'action_required'", ("ops-push", "ops-pager"))],
               catalogue(), ENABLED)

    assert refused.value.route == "held"
