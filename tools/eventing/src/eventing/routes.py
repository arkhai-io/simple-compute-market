"""Routes: SQL conditions selecting which events reach which destinations.

A route's condition is SQL over one event: the envelope's scalar fields and every
declared attribute as the columns of a one-row table `event`, and the event's
references as the table `related` (`event_id`, `type`, `id`). sqlglot parses the
condition and evaluates it with its own executor, so no database is involved.

A route is validated over sqlglot's syntax tree when it is built, which is at a
service's startup: the condition may hold only comparisons, `AND`, `OR`, `NOT`,
`IN`, `LIKE`, `IS NULL`, literals and subqueries over `related`; every column must
be one the envelope has or a declared kind declares; and every destination it names
must be enabled. Anything else is refused naming the route. An attribute an event
does not carry reads as NULL, so a comparison with it selects nothing.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError
from sqlglot.executor import execute

from eventing.envelope import Envelope
from eventing.kinds import Catalogue

EVENT_TABLE = "event"
RELATED_TABLE = "related"
RELATED_COLUMNS: dict[str, type] = {"event_id": str, "type": str, "id": str}

_SQL_TYPES = {str: "VARCHAR", int: "BIGINT", float: "DOUBLE", bool: "BOOLEAN"}

_PREDICATES: tuple[type[exp.Expression], ...] = (
    exp.And, exp.Or, exp.Not, exp.Paren, exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT,
    exp.LTE, exp.In, exp.Like, exp.Is, exp.Exists, exp.Boolean, exp.Column,
)
"""What a condition may be at its top."""

_ALLOWED: tuple[type[exp.Expression], ...] = (
    *_PREDICATES, exp.Null, exp.Literal, exp.Neg, exp.Identifier, exp.Subquery,
    exp.Select, exp.From, exp.Where, exp.Table,
)
"""Every node a condition may hold; a subquery's own nodes are among them."""


class RouteRefused(ValueError):
    """A route that cannot be used, naming it and why."""

    def __init__(self, route: str, reason: str) -> None:
        super().__init__(f"route {route} {reason}")
        self.route = route
        self.reason = reason


@dataclass(frozen=True)
class Route:
    """A named condition and the destinations the events it selects go to."""

    name: str
    where: str
    destinations: tuple[str, ...]


class Routes:
    """A deployment's routes, validated against the catalogue and the enabled
    destinations, and the selection they make for each event."""

    def __init__(self, routes: Iterable[Route], catalogue: Catalogue, enabled: Collection[str]) -> None:
        self._columns = catalogue.columns()
        self._schema = {
            EVENT_TABLE: {name: _SQL_TYPES[t] for name, t in self._columns.items()},
            RELATED_TABLE: {name: _SQL_TYPES[t] for name, t in RELATED_COLUMNS.items()},
        }
        self._compiled: list[tuple[Route, exp.Select]] = []
        for route in routes:
            condition = _parse(route)
            _check_nodes(route, condition)
            _check_columns(route, condition, self._columns)
            disabled = sorted(set(route.destinations) - set(enabled))
            if disabled:
                raise RouteRefused(route.name, f"names destinations not enabled: {', '.join(disabled)}")
            self._compiled.append((route, exp.select("1").from_(EVENT_TABLE).where(condition)))

    def matching(self, envelope: Envelope) -> tuple[str, ...]:
        """The names of the routes selecting `envelope`, in the order they were given."""
        tables = self._tables(envelope)
        return tuple(
            route.name
            for route, query in self._compiled
            if execute(query, schema=self._schema, tables=tables).rows
        )

    def select(self, envelope: Envelope) -> frozenset[str]:
        """Every destination a route selecting `envelope` names."""
        chosen = set(self.matching(envelope))
        return frozenset(
            destination
            for route, _ in self._compiled
            if route.name in chosen
            for destination in route.destinations
        )

    def _tables(self, envelope: Envelope) -> dict[str, list[dict[str, Any]]]:
        row: dict[str, Any] = dict.fromkeys(self._columns)
        row.update(
            (name, value) for name, value in envelope.attributes.items() if name in self._columns
        )
        row.update(envelope.scalar_fields())
        return {
            EVENT_TABLE: [row],
            RELATED_TABLE: [
                {"event_id": envelope.id, "type": reference.type, "id": reference.id}
                for reference in envelope.related
            ],
        }


def _parse(route: Route) -> exp.Expression:
    try:
        statements = sqlglot.parse(route.where)
    except ParseError as error:
        raise RouteRefused(route.name, f"does not parse: {error}") from error
    if len(statements) != 1:
        raise RouteRefused(route.name, "holds more than one statement")
    condition = statements[0]
    if condition is None:
        raise RouteRefused(route.name, "is empty")
    if not isinstance(condition, _PREDICATES):
        raise RouteRefused(route.name, f"is not a condition: it holds {condition.key.upper()}")
    return condition


def _check_nodes(route: Route, condition: exp.Expression) -> None:
    for node in condition.walk():
        if not isinstance(node, _ALLOWED):
            raise RouteRefused(route.name, f"holds {node.key.upper()}, which a route may not")
        if isinstance(node, exp.Table) and node.name != RELATED_TABLE:
            raise RouteRefused(route.name, f"reads table {node.name}; a subquery reads only related")


def _check_columns(route: Route, condition: exp.Expression, columns: Mapping[str, type]) -> None:
    for column in condition.find_all(exp.Column):
        inside_subquery = column.find_ancestor(exp.Select) is not None
        table, name = column.table, column.name
        if table == EVENT_TABLE or (not table and not inside_subquery):
            known = name in columns
        elif table == RELATED_TABLE and inside_subquery:
            known = name in RELATED_COLUMNS
        elif not table:
            known = name in RELATED_COLUMNS or name in columns
        else:
            raise RouteRefused(route.name, f"names column {table}.{name} of no table it may read")
        if not known:
            raise RouteRefused(route.name, f"names column {column.sql()}, which no declared kind has")
