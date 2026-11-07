"""Stored declaration attributes lose the keys naming declaration fields.

Registration refuses an attribute named after a declaration field. These
tests start from the schema the chain before that rule leaves, seed rows the
earlier code could have written, and run the whole chain as a deployment
does.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from compute_provisioning_service.db.migrations import (
    SchemaDriftError,
    apply_schema_migrations,
)

_PREVIOUS_SCHEMA = Path(__file__).parent / "fixtures" / "schema_through_20260911_001.sql"


def _engine(attributes_by_resource: dict[str, str]):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    raw = engine.raw_connection()
    try:
        raw.driver_connection.executescript(_PREVIOUS_SCHEMA.read_text())
    finally:
        raw.close()
    with engine.begin() as connection:
        for index, (resource_id, attributes) in enumerate(attributes_by_resource.items()):
            connection.execute(
                text(
                    "INSERT INTO capacity_buckets (capacity_bucket_id, "
                    "backing_resource_id, pool_id, resource_type, total_units, "
                    "capacity, attributes, enabled, created_at, updated_at) VALUES "
                    "(:bucket, :resource, 'default', 'compute.gpu', 1, "
                    "'{\"gpu_count\": 1}', :attributes, 1, '2026-01-01', '2026-01-01')"
                ),
                {"bucket": f"b{index}", "resource": resource_id, "attributes": attributes},
            )
    return engine


def _rows(engine) -> dict[str, tuple]:
    with engine.begin() as connection:
        return {
            row[0]: (json.loads(row[1]), row[2])
            for row in connection.execute(text(
                "SELECT backing_resource_id, attributes, host_id FROM capacity_buckets"
            ))
        }


def test_declaration_fields_are_removed_and_nothing_else_is():
    engine = _engine({
        "stale": json.dumps({
            "pool_id": "pool-from-an-old-push",
            "host_id": "kvm9",
            "resource_subtype": "h200",
            "gpu_model": "H200",
            "placement": {"host_id": "nested-is-content"},
        }),
        "clean": json.dumps({"gpu_model": "A100"}),
    })

    apply_schema_migrations(engine)

    rows = _rows(engine)
    assert rows["stale"] == (
        {"gpu_model": "H200", "placement": {"host_id": "nested-is-content"}},
        None,
    ), "a removed host_id is not promoted into the column"
    assert rows["clean"] == ({"gpu_model": "A100"}, None)


def test_rerunning_changes_nothing():
    engine = _engine({"stale": json.dumps({"resource_type": "x", "region": "eu"})})
    apply_schema_migrations(engine)
    before = _rows(engine)

    apply_schema_migrations(engine)

    assert _rows(engine) == before == {"stale": ({"region": "eu"}, None)}


def test_a_malformed_attributes_document_changes_nothing():
    """Earlier entries also read attributes, so the chain first runs cleanly
    through them; the rows are then put in the state this entry meets."""
    engine = _engine({"stale": json.dumps({"region": "eu"})})
    apply_schema_migrations(engine)
    with engine.begin() as connection:
        connection.execute(text(
            "DELETE FROM schema_migrations "
            "WHERE id = '20260921_003_capacity_declaration_attributes'"
        ))
        connection.execute(text(
            "UPDATE capacity_buckets SET attributes = :attributes"
        ), {"attributes": json.dumps({"pool_id": "p", "region": "eu"})})
        connection.execute(text(
            "INSERT INTO capacity_buckets (capacity_bucket_id, backing_resource_id, "
            "pool_id, resource_type, total_units, capacity, attributes, enabled, "
            "created_at, updated_at) VALUES ('broken', 'broken', 'default', "
            "'compute.gpu', 1, '{\"gpu_count\": 1}', '{not json', 1, "
            "'2026-01-01', '2026-01-01')"
        ))
        before = connection.execute(text(
            "SELECT backing_resource_id, attributes FROM capacity_buckets "
            "ORDER BY backing_resource_id"
        )).all()

    with pytest.raises(SchemaDriftError, match="broken"):
        apply_schema_migrations(engine)

    with engine.begin() as connection:
        after = connection.execute(text(
            "SELECT backing_resource_id, attributes FROM capacity_buckets "
            "ORDER BY backing_resource_id"
        )).all()
        recorded = connection.execute(text(
            "SELECT COUNT(*) FROM schema_migrations "
            "WHERE id = '20260921_003_capacity_declaration_attributes'"
        )).scalar_one()
    assert after == before
    assert recorded == 0
