"""Jobs stop recording a deal reference; the reservation remains their correlation."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool

from compute_provisioning_service.db.database import run_migrations
from compute_provisioning_service.db.migrations import _migrate_drop_job_deal_correlation


def _engine_with_deal_columns():
    """A current schema, then the two columns as an older database holds them."""
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    run_migrations(engine)
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE ansible_jobs ADD COLUMN escrow_uid VARCHAR"))
        connection.execute(text("ALTER TABLE ansible_jobs ADD COLUMN deal_ref JSON"))
        connection.execute(text(
            "CREATE INDEX ix_ansible_jobs_escrow_uid ON ansible_jobs (escrow_uid)"
        ))
        connection.execute(text(
            "INSERT INTO ansible_jobs (id, status, params, retry_count, max_retries, "
            "escrow_uid, deal_ref, capacity_reservation_id, offering_mode, action_kind, "
            "idempotency_key) "
            "VALUES ('job-1', 'succeeded', '{\"p\": 1}', 0, 3, 'r-1', '{}', 'r-1', 'vm', "
            "'create', 'r-1:create'), "
            "('job-2', 'queued', '{}', 0, 3, '0xbm', '{\"escrow_uid\": \"0xbm\"}', 'r-2', "
            "'bare_metal', 'node_grant_access', 'r-2:grant-access'), "
            "('job-3', 'queued', '{}', 0, 3, NULL, NULL, NULL, 'vm', 'list', NULL)"
        ))
    return engine


def _columns(engine) -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns("ansible_jobs")}


def test_the_deal_correlation_columns_go_and_every_job_keeps_its_identity() -> None:
    engine = _engine_with_deal_columns()

    _migrate_drop_job_deal_correlation(engine)

    assert not {"escrow_uid", "deal_ref"} & _columns(engine)
    indexes = {index["name"] for index in inspect(engine).get_indexes("ansible_jobs")}
    assert "ix_ansible_jobs_escrow_uid" not in indexes
    with engine.connect() as connection:
        rows = connection.execute(text(
            "SELECT id, capacity_reservation_id, action_kind, idempotency_key, params "
            "FROM ansible_jobs ORDER BY id"
        )).all()
    assert [tuple(row[:4]) for row in rows] == [
        ("job-1", "r-1", "create", "r-1:create"),
        ("job-2", "r-2", "node_grant_access", "r-2:grant-access"),
        ("job-3", None, "list", None),
    ]
    # The contract identity is still unique after the rebuild.
    with pytest.raises(Exception):
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO ansible_jobs (id, status, params, retry_count, max_retries, "
                "capacity_reservation_id, action_kind, idempotency_key) "
                "VALUES ('job-4', 'queued', '{}', 0, 3, 'r-1', 'create', 'r-1:create')"
            ))


def test_a_second_run_changes_nothing() -> None:
    engine = _engine_with_deal_columns()
    _migrate_drop_job_deal_correlation(engine)
    columns = _columns(engine)

    _migrate_drop_job_deal_correlation(engine)

    assert _columns(engine) == columns
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM ansible_jobs")).scalar() == 3
