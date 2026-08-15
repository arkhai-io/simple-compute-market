import json
import sqlite3
from pathlib import Path

import pytest

from market_core import ContractVersion, DomainIdentity
from market_storefront.domain_migration import (
    LegacyStorefrontSelection,
    StorefrontDomainMigrationError,
    migrate_storefront_domains,
)


_SELECTION = LegacyStorefrontSelection(
    contribution_id="vms",
    offering_mode="vm",
    domain_identity=DomainIdentity("compute.v1"),
    contract_version=ContractVersion(1, 0),
)


def _legacy_database(path: Path, *, public_mode: str | None = "vm") -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE listings (
              listing_id TEXT PRIMARY KEY,
              offer_resource TEXT
            );
            CREATE TABLE negotiation_threads (
              negotiation_id TEXT PRIMARY KEY,
              our_listing_id TEXT
            );
            CREATE TABLE derived_compute_listings (
              listing_id TEXT PRIMARY KEY,
              site_id TEXT,
              pool_id TEXT,
              resource_id TEXT NOT NULL,
              gpu_count INTEGER NOT NULL,
              status TEXT NOT NULL,
              derivation_key TEXT NOT NULL,
              last_reconciled_at TEXT NOT NULL
            );
            CREATE TABLE escrows (
              escrow_uid TEXT PRIMARY KEY,
              negotiation_id TEXT,
              fulfillment_context TEXT
            );
            """
        )
        offer = {"resource_id": "host-1", "operator_secret": "never-print-me"}
        if public_mode is not None:
            offer["virtualization_type"] = public_mode
        conn.execute(
            "INSERT INTO listings VALUES (?, ?)",
            ("listing-1", json.dumps(offer)),
        )
        conn.execute(
            "INSERT INTO derived_compute_listings VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "listing-1", "site-a", "pool-a", "host-1", 2, "open",
                "legacy-key", "2026-08-15T00:00:00Z",
            ),
        )
        conn.execute(
            "INSERT INTO negotiation_threads VALUES (?, ?)",
            ("thread-1", "listing-1"),
        )
        conn.execute(
            "INSERT INTO escrows VALUES (?, ?, ?)",
            (
                "escrow-1",
                "thread-1",
                json.dumps({"capacity_reservation_id": "reservation-1"}),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def test_check_is_redacted_and_does_not_mutate_source(tmp_path):
    database = tmp_path / "storefront.db"
    _legacy_database(database)

    result = migrate_storefront_domains(
        database, selection=_SELECTION, check=True, write=False, backup=False
    )

    assert result.listings == 1
    assert result.threads == 1
    assert result.fulfillment_contexts == 1
    assert "never-print-me" not in "\n".join(result.redacted_lines())
    conn = sqlite3.connect(database)
    try:
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE name='storefront_listing_bindings'"
        ).fetchone() is None
    finally:
        conn.close()


def test_write_atomically_binds_rows_and_retires_legacy_authority(tmp_path):
    database = tmp_path / "storefront.db"
    _legacy_database(database)

    result = migrate_storefront_domains(
        database, selection=_SELECTION, check=False, write=True, backup=True
    )

    assert result.backup is not None
    assert Path(result.backup).is_file()
    conn = sqlite3.connect(database)
    try:
        binding = conn.execute(
            """
            SELECT site_id, offering_mode, domain_identity, contract_major,
                   contract_minor, pool_id, physical_resource_id
            FROM storefront_listing_bindings WHERE listing_id='listing-1'
            """
        ).fetchone()
        assert binding == ("site-a", "vm", "compute.v1", 1, 0, "pool-a", "host-1")
        thread = conn.execute(
            """
            SELECT domain_listing_id, site_id, offering_mode, domain_identity,
                   contract_major, contract_minor
            FROM negotiation_threads WHERE negotiation_id='thread-1'
            """
        ).fetchone()
        assert thread == ("listing-1", "site-a", "vm", "compute.v1", 1, 0)
        context = json.loads(conn.execute(
            "SELECT fulfillment_context FROM escrows WHERE escrow_uid='escrow-1'"
        ).fetchone()[0])
        assert context["storefront_domain_binding"] == {
            "offering_mode": "vm",
            "domain_identity": "compute.v1",
            "contract_major": 1,
            "contract_minor": 0,
            "site_id": "site-a",
        }
        with pytest.raises(sqlite3.IntegrityError, match="retired"):
            conn.execute(
                "UPDATE derived_compute_listings SET site_id='site-b' "
                "WHERE listing_id='listing-1'"
            )
    finally:
        conn.close()


def test_mismatch_aborts_without_backup_or_partial_state(tmp_path):
    database = tmp_path / "storefront.db"
    _legacy_database(database, public_mode="bare_metal")

    with pytest.raises(StorefrontDomainMigrationError, match="public mode"):
        migrate_storefront_domains(
            database, selection=_SELECTION, check=False, write=True, backup=True
        )

    assert not tuple(tmp_path.glob("*.bak"))
    conn = sqlite3.connect(database)
    try:
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE name='storefront_listing_bindings'"
        ).fetchone() is None
    finally:
        conn.close()
