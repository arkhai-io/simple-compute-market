"""Hosts present at upgrade gain a declaration derived from their legacy GPUs.

The migration is frozen SQL, and the only derivation of capacity from hosts:
no host write declares capacity.

These tests start from the schema the chain through 20260911_001 leaves, where a
declaration named its host through a ``vm_host`` attribute, and run the whole
chain as a deployment does.
"""

from __future__ import annotations

import json
from pathlib import Path

from market_site import CapacityLedgerService
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from compute_provisioning_service.db.migrations import MIGRATIONS, apply_schema_migrations

_PREVIOUS_SCHEMA = Path(__file__).parent / "fixtures" / "schema_through_20260911_001.sql"
_ENTRY = "20260921_004_legacy_host_capacity_declarations"


def _engine():
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
        connection.execute(text(
            "INSERT INTO resource_pools (id, label, provider, enabled, policy_tags) "
            "VALUES ('default', 'Default Pool', 'ansible', 1, "
            "'{\"deliverable_modes\": [\"vm\"]}')"
        ))
        for name, gpus, model, enabled in (
            ("kvm1", 4, "H200", 1),
            ("kvm2", 2, None, 1),
            ("kvm3", 0, None, 1),
            ("kvm4", 1, "A100", 0),
        ):
            connection.execute(
                text(
                    "INSERT INTO hosts (name, kvm_host, ssh_user, ssh_key_type, "
                    "ssh_key_value, gpu_count, gpu_model, enabled, pool_id, "
                    "created_at, updated_at) VALUES (:name, '10.0.0.1', 'root', "
                    "'path', '/keys/id', :gpus, :model, :enabled, 'default', "
                    "'2026-01-01', '2026-01-01')"
                ),
                {"name": name, "gpus": gpus, "model": model, "enabled": enabled},
            )
        # kvm2 is already declared, the previous way: a listing's resource id
        # with the host named in attributes.
        connection.execute(
            text(
                "INSERT INTO capacity_buckets (capacity_bucket_id, backing_resource_id, "
                "pool_id, resource_type, total_units, capacity, attributes, enabled, "
                "created_at, updated_at) VALUES ('b1', 'listing-kvm2', 'default', "
                "'compute.gpu', 1, '{\"gpu_count\": 1}', :attributes, 1, "
                "'2026-01-01', '2026-01-01')"
            ),
            {"attributes": json.dumps({"vm_host": "kvm2"})},
        )
    return engine


def _resources(engine) -> dict[str, dict]:
    ledger = CapacityLedgerService(
        sessionmaker(bind=engine),
        unit_claim_keys=("units", "gpu_count"),
        mirror_dimension="gpu_count",
    )
    return {row["resource_id"]: row for row in ledger.list_resources()}


def _host_rows(engine) -> list[tuple]:
    with engine.begin() as connection:
        return connection.execute(text("SELECT * FROM hosts ORDER BY host_id")).all()


def test_hosts_with_gpus_and_no_declaration_are_declared():
    engine = _engine()

    apply_schema_migrations(engine)

    resources = _resources(engine)
    assert set(resources) == {"kvm1", "kvm4", "listing-kvm2"}
    assert resources["kvm1"]["capacity"] == {"gpu_count": 4}
    assert resources["kvm1"]["host_id"] == "kvm1"
    assert resources["kvm1"]["attributes"] == {"gpu_model": "H200"}
    assert resources["kvm1"]["value"] == 4
    assert resources["kvm4"]["enabled"] is False
    assert resources["listing-kvm2"]["capacity"] == {"gpu_count": 1}


def test_host_rows_are_not_changed():
    """Run the chain up to this entry, then this entry alone, so the
    comparison isolates what it writes; later entries drop the host's GPU
    columns."""
    engine = _engine()
    position = [migration.id for migration in MIGRATIONS].index(_ENTRY)
    with engine.begin() as connection:
        for migration in MIGRATIONS[position:]:
            connection.execute(
                text("INSERT INTO schema_migrations (id) VALUES (:id)"), {"id": migration.id}
            )
    apply_schema_migrations(engine)
    hosts_before = _host_rows(engine)

    MIGRATIONS[position].apply(engine)

    assert _host_rows(engine) == hosts_before
    with engine.begin() as connection:
        declared = connection.execute(text(
            "SELECT backing_resource_id FROM capacity_buckets"
        )).scalars().all()
    assert {"kvm1", "kvm4"} <= set(declared)


def test_rerunning_changes_nothing():
    engine = _engine()
    apply_schema_migrations(engine)
    before = _resources(engine)
    with engine.begin() as connection:
        events_before = connection.execute(text("SELECT COUNT(*) FROM capacity_events")).scalar_one()

    apply_schema_migrations(engine)

    with engine.begin() as connection:
        events_after = connection.execute(text("SELECT COUNT(*) FROM capacity_events")).scalar_one()
    assert _resources(engine) == before
    assert events_after == events_before

