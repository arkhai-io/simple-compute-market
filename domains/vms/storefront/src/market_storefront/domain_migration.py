"""Transactional conversion of one explicitly selected legacy storefront database.

The converter never infers a domain from payload shape, installed contribution
count, or a missing discriminator.  Its caller supplies the complete legacy
registration assertion and this VM-owned adapter either proves that every row
belongs to that source or leaves the original database untouched.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core_storefront.domain_registry import (
    StorefrontDomainBinding,
    StorefrontListingBinding,
    bind_fulfillment_context,
    build_storefront_derivation_key,
    canonical_source_envelope,
)
from market_core import ContractVersion, DomainIdentity


from core_storefront.sqlite_migrations import (
    migrate_storefront_domain_bindings_schema,
)
class StorefrontDomainMigrationError(RuntimeError):
    """The selected legacy source cannot be converted without guessing."""


@dataclass(frozen=True)
class LegacyStorefrontSelection:
    contribution_id: str
    offering_mode: str
    domain_identity: DomainIdentity
    contract_version: ContractVersion

    def __post_init__(self) -> None:
        if not self.contribution_id or self.contribution_id != self.contribution_id.strip():
            raise ValueError("legacy contribution must be a non-empty trimmed string")
        if not self.offering_mode or self.offering_mode != self.offering_mode.strip():
            raise ValueError("legacy offering mode must be a non-empty trimmed string")

    @property
    def binding(self) -> StorefrontDomainBinding:
        return StorefrontDomainBinding(
            offering_mode=self.offering_mode,
            domain_identity=self.domain_identity,
            contract_version=self.contract_version,
        )


@dataclass(frozen=True)
class StorefrontDomainMigrationResult:
    mode: str
    database: str
    backup: str | None
    listings: int
    threads: int
    fulfillment_contexts: int

    def redacted_lines(self) -> tuple[str, ...]:
        return (
            f"mode={self.mode}",
            f"database={self.database}",
            f"backup={self.backup or '(none)'}",
            f"listing_bindings={self.listings}",
            f"thread_bindings={self.threads}",
            f"fulfillment_contexts={self.fulfillment_contexts}",
        )


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}


def _require_table(conn: sqlite3.Connection, table: str) -> set[str]:
    columns = _table_columns(conn, table)
    if not columns:
        raise StorefrontDomainMigrationError(f"required legacy table {table!r} is absent")
    return columns


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _decode_object(raw: Any, *, field: str, owner: str) -> dict[str, Any]:
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, json.JSONDecodeError) as exc:
        raise StorefrontDomainMigrationError(
            f"{owner} has malformed {field}; migration cannot infer its meaning"
        ) from exc
    if not isinstance(value, dict):
        raise StorefrontDomainMigrationError(f"{owner} {field} must be a JSON object")
    return value


def _assert_vm_selection(selection: LegacyStorefrontSelection) -> None:
    expected = LegacyStorefrontSelection(
        contribution_id="vms",
        offering_mode="vm",
        domain_identity=DomainIdentity("compute.v1"),
        contract_version=ContractVersion(1, 0),
    )
    if selection != expected:
        raise StorefrontDomainMigrationError(
            "this legacy adapter owns only the exact vms/vm/compute.v1/1.0 source; "
            "install the selected contribution's migration adapter instead"
        )


def _prepare_vm_bindings(
    conn: sqlite3.Connection,
    *,
    selection: LegacyStorefrontSelection,
) -> tuple[int, int, int]:
    _assert_vm_selection(selection)
    derived_columns = _require_table(conn, "derived_compute_listings")
    required_derived = {
        "listing_id",
        "site_id",
        "pool_id",
        "resource_id",
        "gpu_count",
        "last_reconciled_at",
    }
    missing = sorted(required_derived - derived_columns)
    if missing:
        raise StorefrontDomainMigrationError(
            "legacy derived_compute_listings lacks required provenance columns: "
            + ", ".join(missing)
        )
    _require_table(conn, "listings")
    _require_table(conn, "negotiation_threads")
    _require_table(conn, "storefront_listing_bindings")

    listing_rows = conn.execute(
        """
        SELECT l.listing_id, l.offer_resource,
               d.site_id, d.pool_id, d.resource_id, d.gpu_count,
               d.last_reconciled_at
        FROM listings l
        LEFT JOIN derived_compute_listings d ON d.listing_id = l.listing_id
        ORDER BY l.listing_id
        """
    ).fetchall()
    prepared: dict[str, StorefrontListingBinding] = {}
    for raw_row in listing_rows:
        listing_id = str(raw_row[0])
        site_id = raw_row[2]
        if not isinstance(site_id, str) or not site_id.strip():
            raise StorefrontDomainMigrationError(
                f"listing {listing_id!r} has no exact trusted site mapping"
            )
        resource = raw_row[4]
        pool = raw_row[3]
        if not isinstance(resource, str) or not resource.strip():
            raise StorefrontDomainMigrationError(
                f"listing {listing_id!r} has no Physical Resource provenance"
            )
        if pool is not None and (not isinstance(pool, str) or not pool.strip()):
            raise StorefrontDomainMigrationError(
                f"listing {listing_id!r} has an invalid pool identifier"
            )
        offer = _decode_object(
            raw_row[1], field="offer_resource", owner=f"listing {listing_id!r}"
        )
        public_mode = offer.get("virtualization_type")
        if public_mode is not None and public_mode != selection.offering_mode:
            raise StorefrontDomainMigrationError(
                f"listing {listing_id!r} declares public mode {public_mode!r}, "
                f"not selected mode {selection.offering_mode!r}"
            )
        source = {
            "kind": "compute.listing_source",
            "schema_version": 1,
            "payload": {
                "site_id": site_id,
                "pool_id": pool,
                "resource_id": resource,
                "gpu_count": int(raw_row[5]),
            },
        }
        source_json = canonical_source_envelope(source)
        binding = StorefrontListingBinding(
            listing_id=listing_id,
            site_id=site_id,
            binding=selection.binding,
            derivation_key=build_storefront_derivation_key(
                site_id=site_id,
                binding=selection.binding,
                source_identity=source,
            ),
            source_envelope_json=source_json,
            last_reconciled_at=str(raw_row[6]),
            pool_id=pool,
            physical_resource_id=resource,
        )
        previous = prepared.get(binding.derivation_key)
        if previous is not None and previous != binding:
            raise StorefrontDomainMigrationError(
                "legacy listing derivation identity is ambiguous between "
                f"{previous.listing_id!r} and {listing_id!r}"
            )
        prepared[binding.derivation_key] = binding

    derived_count = conn.execute(
        "SELECT COUNT(*) FROM derived_compute_listings"
    ).fetchone()[0]
    if int(derived_count) != len(listing_rows):
        raise StorefrontDomainMigrationError(
            "legacy derived mapping contains an orphan or duplicate listing relation"
        )

    for binding in prepared.values():
        values = binding.as_record()
        existing = conn.execute(
            """
            SELECT listing_id, site_id, pool_id, physical_resource_id,
                   offering_mode, domain_identity, contract_major, contract_minor,
                   derivation_key, source_envelope_json, last_reconciled_at
            FROM storefront_listing_bindings WHERE listing_id=?
            """,
            (binding.listing_id,),
        ).fetchone()
        candidate = (
            values["listing_id"], values["site_id"], values["pool_id"],
            values["physical_resource_id"], values["offering_mode"],
            values["domain_identity"], values["contract_major"],
            values["contract_minor"], values["derivation_key"],
            values["source_envelope_json"], values["last_reconciled_at"],
        )
        if existing is not None and tuple(existing) != candidate:
            raise StorefrontDomainMigrationError(
                f"listing {binding.listing_id!r} already has a different immutable binding"
            )
        conn.execute(
            """
            INSERT OR IGNORE INTO storefront_listing_bindings(
              listing_id, site_id, pool_id, physical_resource_id, offering_mode,
              domain_identity, contract_major, contract_minor, derivation_key,
              source_envelope_json, last_reconciled_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            candidate,
        )

    thread_rows = conn.execute(
        "SELECT negotiation_id, our_listing_id FROM negotiation_threads "
        "ORDER BY negotiation_id"
    ).fetchall()
    for negotiation_id, listing_id in thread_rows:
        if listing_id is None:
            raise StorefrontDomainMigrationError(
                f"negotiation {negotiation_id!r} has no authoritative seller listing"
            )
        listing_binding = next(
            (b for b in prepared.values() if b.listing_id == str(listing_id)), None
        )
        if listing_binding is None:
            raise StorefrontDomainMigrationError(
                f"negotiation {negotiation_id!r} refers to unmapped listing {listing_id!r}"
            )
        values = listing_binding.binding.as_record()
        cursor = conn.execute(
            """
            UPDATE negotiation_threads
            SET domain_listing_id=?, site_id=?, offering_mode=?, domain_identity=?,
                contract_major=?, contract_minor=?
            WHERE negotiation_id=? AND domain_identity IS NULL
            """,
            (
                listing_binding.listing_id,
                listing_binding.site_id,
                values["offering_mode"], values["domain_identity"],
                values["contract_major"], values["contract_minor"], negotiation_id,
            ),
        )
        stored = conn.execute(
            """
            SELECT domain_listing_id, site_id, offering_mode, domain_identity,
                   contract_major, contract_minor
            FROM negotiation_threads WHERE negotiation_id=?
            """,
            (negotiation_id,),
        ).fetchone()
        expected = (
            listing_binding.listing_id, listing_binding.site_id,
            values["offering_mode"], values["domain_identity"],
            values["contract_major"], values["contract_minor"],
        )
        if stored is None or tuple(stored) != expected:
            raise StorefrontDomainMigrationError(
                f"negotiation {negotiation_id!r} disagrees with its listing binding"
            )
        del cursor

    contexts = 0
    escrow_columns = _table_columns(conn, "escrows")
    if {"negotiation_id", "fulfillment_context"} <= escrow_columns:
        for escrow_uid, negotiation_id, raw_context in conn.execute(
            "SELECT escrow_uid, negotiation_id, fulfillment_context FROM escrows "
            "WHERE fulfillment_context IS NOT NULL"
        ).fetchall():
            row = conn.execute(
                """
                SELECT site_id, offering_mode, domain_identity,
                       contract_major, contract_minor
                FROM negotiation_threads WHERE negotiation_id=?
                """,
                (negotiation_id,),
            ).fetchone()
            if row is None or row[2] is None:
                raise StorefrontDomainMigrationError(
                    f"escrow {escrow_uid!r} has no accepted thread binding"
                )
            thread_binding = StorefrontDomainBinding(
                offering_mode=str(row[1]),
                domain_identity=DomainIdentity(str(row[2])),
                contract_version=ContractVersion(int(row[3]), int(row[4])),
            )
            context = _decode_object(
                raw_context,
                field="fulfillment_context",
                owner=f"escrow {escrow_uid!r}",
            )
            bound = bind_fulfillment_context(
                context,
                binding=thread_binding,
                site_id=str(row[0]),
            )
            conn.execute(
                "UPDATE escrows SET fulfillment_context=? WHERE escrow_uid=?",
                (_canonical_json(bound), escrow_uid),
            )
            contexts += 1

    for action in ("INSERT", "UPDATE", "DELETE"):
        conn.execute(
            f"""
            CREATE TRIGGER IF NOT EXISTS derived_compute_listings_retired_{action.lower()}
            BEFORE {action} ON derived_compute_listings
            BEGIN
              SELECT RAISE(ABORT, 'derived_compute_listings is retired; use common binding');
            END
            """
        )
    return len(prepared), len(thread_rows), contexts


def _sqlite_backup(source: Path, destination: Path) -> None:
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    dst = sqlite3.connect(destination)
    try:
        src.backup(dst)
        dst.commit()
    finally:
        dst.close()
        src.close()
    os.chmod(destination, 0o600)
    with destination.open("rb") as handle:
        os.fsync(handle.fileno())

def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def migrate_storefront_domains(
    database: str | Path,
    *,
    selection: LegacyStorefrontSelection,
    check: bool,
    write: bool,
    backup: bool,
) -> StorefrontDomainMigrationResult:
    """Preview or atomically replace one quiesced legacy storefront database."""

    if check == write:
        raise StorefrontDomainMigrationError("select exactly one of --check or --write")
    if write and not backup:
        raise StorefrontDomainMigrationError("--write requires --backup")
    db_path = Path(database).expanduser().resolve()
    if not db_path.is_file():
        raise StorefrontDomainMigrationError(f"storefront database does not exist: {db_path}")

    fd, temp_name = tempfile.mkstemp(
        prefix=f".{db_path.name}.storefront-domains-", suffix=".tmp", dir=db_path.parent
    )
    os.close(fd)
    temp_path = Path(temp_name)
    backup_path: Path | None = None
    try:
        _sqlite_backup(db_path, temp_path)
        conn = sqlite3.connect(temp_path, isolation_level=None)
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            migrate_storefront_domain_bindings_schema(conn)
            conn.execute("BEGIN IMMEDIATE")
            counts = _prepare_vm_bindings(conn, selection=selection)
            conn.commit()
            integrity = conn.execute("PRAGMA integrity_check").fetchone()
            if integrity != ("ok",):
                raise StorefrontDomainMigrationError("migrated database failed integrity_check")
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        if write:
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            backup_path = db_path.with_name(f"{db_path.name}.pre-domains-{stamp}.bak")
            if backup_path.exists():
                raise StorefrontDomainMigrationError(
                    f"refusing to replace existing backup {backup_path}"
                )
            _sqlite_backup(db_path, backup_path)
            original_mode = db_path.stat().st_mode & 0o777
            os.chmod(temp_path, original_mode & 0o600 or 0o600)
            os.replace(temp_path, db_path)
            _fsync_directory(db_path.parent)
        return StorefrontDomainMigrationResult(
            mode="write" if write else "check",
            database=str(db_path),
            backup=str(backup_path) if backup_path is not None else None,
            listings=counts[0],
            threads=counts[1],
            fulfillment_contexts=counts[2],
        )
    except (sqlite3.Error, OSError, ValueError, TypeError) as exc:
        if isinstance(exc, StorefrontDomainMigrationError):
            raise
        raise StorefrontDomainMigrationError(str(exc)) from exc
    finally:
        temp_path.unlink(missing_ok=True)
