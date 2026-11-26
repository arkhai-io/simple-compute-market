"""The schema steps against a real SQLite file: they build exactly the tables, keys,
unique constraints and indexes the component's table definitions describe, and seed
the sequence counter.

Library integration: the steps applied as a service's migration chain applies them,
then the built database inspected.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Index, Table, UniqueConstraint, inspect, select

from eventing import metadata
from eventing import schema
from tests.fixtures.kinds import Store


def described(table: Table) -> dict[str, Any]:
    return {
        "columns": sorted(column.name for column in table.columns),
        "primary_key": sorted(column.name for column in table.primary_key.columns),
        "unique": sorted(
            (constraint.name, tuple(column.name for column in constraint.columns))
            for constraint in table.constraints if isinstance(constraint, UniqueConstraint)
        ),
        "indexes": sorted(
            (index.name, tuple(column.name for column in index.columns))
            for index in table.indexes if isinstance(index, Index)
        ),
    }


def test_the_steps_build_what_the_table_definitions_describe(store: Store) -> None:
    inspector = inspect(store.engine)

    built = {
        name: {
            "columns": sorted(column["name"] for column in inspector.get_columns(name)),
            "primary_key": sorted(inspector.get_pk_constraint(name)["constrained_columns"]),
            "unique": sorted((u["name"], tuple(u["column_names"]))
                             for u in inspector.get_unique_constraints(name)),
            "indexes": sorted((i["name"], tuple(i["column_names"]))
                              for i in inspector.get_indexes(name)),
        }
        for name in inspector.get_table_names()
    }

    assert built == {table.name: described(table) for table in metadata.sorted_tables}


def test_the_steps_seed_the_sequence_counter_at_zero(store: Store) -> None:
    with store.engine.connect() as connection:
        rows = connection.execute(select(schema.sequence_counter)).all()

    assert [tuple(row) for row in rows] == [(schema.SEQUENCE_COUNTER, 0)]

