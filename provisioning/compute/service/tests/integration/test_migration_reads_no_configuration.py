"""The migration command's result depends on the database alone.

Two copies of one database, from before resource pools and job envelopes, are
migrated by the real ``compute-provisioning-migrate`` entry point under two
configurations that differ in every operational setting migration once read:
the VM playbook, the default host, the inventory group, and the pool and seed
documents. Both copies end with the same schema and the same rows.

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
from compute_provisioning_service.db.models import ResourcePool
from vm_provisioning_adapter.db import AnsiblePoolConfig

from .test_database import _create_pre_pool_hosts

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
    """Hosts placed in `default`, its VM configuration, and two jobs whose
    host the job-envelope migration decides."""
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as connection:
        _create_pre_pool_hosts(connection, ("kvm1",))
        connection.execute(text(
            "CREATE TABLE ansible_jobs (id VARCHAR PRIMARY KEY, status VARCHAR NOT NULL, "
            "params JSON NOT NULL, result JSON, logs TEXT, error TEXT, process_id VARCHAR, "
            "retry_count INTEGER NOT NULL DEFAULT 0, max_retries INTEGER NOT NULL DEFAULT 3, "
            "next_retry_at DATETIME, created_at DATETIME NOT NULL, "
            "updated_at DATETIME NOT NULL)"
        ))
        connection.execute(text(
            "INSERT INTO ansible_jobs (id, status, params, created_at, updated_at) VALUES "
            "('job-vm', 'queued', '{\"vm_action\": \"create\", \"vm_target\": \"guest-1\"}', "
            "'2026-01-01 00:00:00', '2026-01-01 00:00:00'), "
            "('job-bm', 'queued', '{\"offering_mode\": \"bare_metal\", "
            "\"executor_target\": \"bm-node-1\", \"executor_action\": \"node_grant_access\"}', "
            "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"
        ))
    ResourcePool.__table__.create(bind=engine)
    AnsiblePoolConfig.__table__.create(bind=engine)
    with engine.begin() as connection:
        connection.execute(text(
            "ALTER TABLE ansible_pool_configs ADD COLUMN inventory_group VARCHAR"
        ))
        connection.execute(text(
            "INSERT INTO resource_pools (id, label, provider, enabled, policy_tags, "
            "created_at, updated_at) VALUES ('default', 'Default Pool', 'ansible', 1, '{}', "
            "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"
        ))
        connection.execute(text(
            "INSERT INTO ansible_pool_configs (pool_id, playbook_path, inventory_group, "
            "extra_vars) VALUES ('default', '/opt/stored/vm.yaml', 'stored_hosts', '{}')"
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
        default_host_id="kvm1",
        default_pool_inventory_group="first_hosts",
        pool_definitions_path=str(pool_document),
        pool_seed_path="",
    )
    _migrate_under(
        monkeypatch, second,
        vm_playbook_path="/opt/second/vm.yaml",
        default_host_id="kvm-elsewhere",
        default_pool_inventory_group="second_hosts",
        pool_definitions_path=str(tmp_path / "absent.yaml"),
        pool_seed_path="seed/pools.yaml",
    )

    assert _contents(first) == _contents(second)

    engine = create_engine(f"sqlite:///{first}")
    try:
        with engine.connect() as connection:
            pools = connection.execute(text(
                "SELECT p.id, p.provider, c.playbook_path FROM resource_pools p "
                "JOIN ansible_pool_configs c ON c.pool_id = p.id"
            )).all()
            hosts = dict(connection.execute(text(
                "SELECT id, host_id FROM ansible_jobs ORDER BY id"
            )).all())
    finally:
        engine.dispose()
    # The stored pool keeps its own playbook; no document's pool is created.
    assert [tuple(row) for row in pools] == [("default", "vm.ansible", "/opt/stored/vm.yaml")]
    # No configured default host stands in for a VM job's missing host.
    assert hosts == {"job-bm": "bm-node-1", "job-vm": None}
