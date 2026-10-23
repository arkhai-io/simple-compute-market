"""The migration command's result depends on the database alone.

Two copies of one database are migrated by the real
``compute-provisioning-migrate`` entry point under two configurations that
differ in every setting that could decide a site's pools or a job's host: the
VM and bare-metal playbooks, a default host, an inventory group, and the pool
and seed documents. The database holds no host and no pool, and a job naming no
host, so a migration that created a pool from configuration or gave a job a
configured host would leave the copies different. Both end with the same
schema and the same rows.

External boundary: file-backed SQLite in a temp directory. Each configuration
is set through the service's environment layer and loaded by the service's own
loader into the settings object the entry point reads.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from compute_provisioning_service import config as config_module
from compute_provisioning_service.config import settings
from compute_provisioning_service.db import migrate
from compute_provisioning_service.db.migrations import MIGRATIONS

_POOL_DOCUMENT = """
pools:
  - id: documented
    label: Documented
    provider: vm.ansible
    policy_tags:
      deliverable_modes: [vm]
      advertisable_modes: [vm]
      capacity_backing: backed
    provider_config: {}
"""


def _source_database(path: Path) -> None:
    """No host and no pool; one VM job from before job envelopes whose
    parameters name no host and no target."""
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE ansible_jobs (id VARCHAR PRIMARY KEY, status VARCHAR NOT NULL, "
            "params JSON NOT NULL, result JSON, logs TEXT, error TEXT, process_id VARCHAR, "
            "retry_count INTEGER NOT NULL DEFAULT 0, max_retries INTEGER NOT NULL DEFAULT 3, "
            "next_retry_at DATETIME, created_at DATETIME NOT NULL, "
            "updated_at DATETIME NOT NULL)"
        ))
        connection.execute(text(
            "INSERT INTO ansible_jobs (id, status, params, created_at, updated_at) VALUES "
            "('job-untargeted', 'queued', '{\"vm_action\": \"create\"}', "
            "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"
        ))
    engine.dispose()


def _migrate_under(monkeypatch: pytest.MonkeyPatch, database: Path, **configuration: str) -> None:
    """Run the migration command with ``configuration`` in the service's
    environment layer, loaded as the service loads it."""
    monkeypatch.setenv("PROVISIONING_DATABASE_URL", f"sqlite:///{database}")
    for name, value in configuration.items():
        monkeypatch.setenv(f"PROVISIONING_{name.upper()}", value)
    monkeypatch.setattr(
        settings, "_source", config_module._load_bootstrap(os.environ).settings
    )
    migrate.main()


def _contents(database: Path) -> tuple[list, dict]:
    """Every schema object's DDL, and every table's rows in a stable order.

    The migration record is compared by ID: when each copy recorded a
    migration is the one value that differs by run, not by configuration.
    """
    engine = create_engine(f"sqlite:///{database}")
    try:
        with engine.connect() as connection:
            schema = [tuple(entry) for entry in connection.execute(text(
                "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
            ))]
            rows = {
                name: sorted(
                    repr(tuple(row))
                    for row in connection.execute(text(
                        "SELECT id FROM schema_migrations" if name == "schema_migrations"
                        else f'SELECT * FROM "{name}"'
                    ))
                )
                for kind, name, _ in schema
                if kind == "table"
            }
    finally:
        engine.dispose()
    return schema, rows


def test_two_configurations_migrate_one_database_to_the_same_schema_and_rows(
    tmp_path, monkeypatch,
):
    first, second = tmp_path / "first.db", tmp_path / "second.db"
    _source_database(first)
    shutil.copyfile(first, second)
    pool_document = tmp_path / "pools.yaml"
    pool_document.write_text(_POOL_DOCUMENT, encoding="utf-8")

    _migrate_under(
        monkeypatch, first,
        vm_playbook_path="/opt/first/vm.yaml",
        bare_metal_playbook_path="/opt/first/node-access.yaml",
        default_host_id="kvm1",
        default_pool_inventory_group="first_hosts",
        pool_definitions_path="",
        pool_seed_path="seed/pools.yaml",
    )
    _migrate_under(
        monkeypatch, second,
        vm_playbook_path="/opt/second/vm.yaml",
        bare_metal_playbook_path="/opt/second/node-access.yaml",
        default_host_id="kvm-elsewhere",
        default_pool_inventory_group="second_hosts",
        pool_definitions_path=str(pool_document),
        pool_seed_path="",
    )

    assert _contents(first) == _contents(second)

    engine = create_engine(f"sqlite:///{first}")
    try:
        with engine.connect() as connection:
            pools = connection.execute(text("SELECT id FROM resource_pools")).all()
            hosts = dict(connection.execute(text(
                "SELECT id, host_id FROM ansible_jobs"
            )).all())
    finally:
        engine.dispose()
    # Neither the playbooks nor either document creates a pool.
    assert pools == []
    # A job naming no host gets none, whatever default host is configured.
    assert hosts == {"job-untargeted": None}


def test_the_migration_command_migrates_with_the_retired_playbook_setting_stated(
    tmp_path, monkeypatch,
):
    database = tmp_path / "provisioning.db"

    _migrate_under(monkeypatch, database, playbook_path="/opt/retired/vm.yaml")

    engine = create_engine(f"sqlite:///{database}")
    try:
        with engine.connect() as connection:
            applied = {row[0] for row in connection.execute(text(
                "SELECT id FROM schema_migrations"
            ))}
    finally:
        engine.dispose()
    assert applied == {migration.id for migration in MIGRATIONS}
