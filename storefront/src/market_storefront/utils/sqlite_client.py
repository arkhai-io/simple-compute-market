from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import time
import uuid
from datetime import datetime
from typing import Any

from .config import settings
from .host_csv_importer import upsert_hosts_from_csv
from .resource_csv_importer import upsert_resources_from_csv, upsert_resources_from_csv_content

logger = logging.getLogger(__name__)


def _normalize_to_dict(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None
    return None


def synthesize_accepted_escrows_from_demand(
    demand_resource: Any,
) -> list[dict[str, Any]] | None:
    """Build an ``accepted_escrows`` list from a legacy ``demand_resource``
    payload (``{token: {contract_address, ...}, amount}``), one entry per
    configured chain.

    Used by:
      * the one-shot schema-init backfill (pre-cutover rows still carrying
        ``demand_resource`` in SQLite),
      * action_executor's MAKE_OFFER entry point (policy layer still emits
        ``demand``; storefront converts at the boundary before persisting).

    Returns ``None`` when the demand can't be mapped to any chain (no
    token, missing contract_address, or every chain's alkahest config
    fails to resolve the erc20 escrow obligation address).
    """
    from market_storefront.utils.config import CHAINS

    normalized = _normalize_to_dict(demand_resource)
    if not normalized:
        return None
    token = normalized.get("token")
    if not isinstance(token, dict):
        return None
    contract_address = token.get("contract_address")
    if not isinstance(contract_address, str) or not contract_address:
        return None

    amount = normalized.get("amount")
    # ``price_per_hour`` is uint256-domain (base units) — emit as a
    # decimal-digit string on the stored/wire JSON to stay safe past
    # JS's 2^53 and SQLite int64 ceilings. Python callers parse it back
    # with ``int(...)``.
    if isinstance(amount, bool):
        price_per_hour: str | None = None
    elif isinstance(amount, int):
        price_per_hour = str(amount)
    elif isinstance(amount, str):
        s = amount.strip()
        price_per_hour = s if s.isdigit() else None
    else:
        price_per_hour = None

    from service.clients.alkahest import get_erc20_escrow_obligation_nontierable

    entries: list[dict[str, Any]] = []
    for name, cc in CHAINS.items():
        try:
            escrow_address = get_erc20_escrow_obligation_nontierable(
                name,
                config_path=cc.alkahest_address_config_path,
            )
        except Exception as exc:
            logger.debug(
                "Skipping accepted_escrows synthesis for chain %r: %s", name, exc,
            )
            continue
        entries.append({
            "chain_name": name,
            "escrow_address": escrow_address.lower(),
            "fields": {"token": contract_address},
            "price_per_hour": price_per_hour,
        })
    return entries or None


def _publication_row_to_dict(row: tuple) -> dict[str, Any]:
    """Decode a publications row tuple into a dict, parsing payload_json."""
    listing_id, registry_url, payload_json, published_at, \
        registry_assigned_id, status, last_error = row
    try:
        payload = json.loads(payload_json) if payload_json else None
    except Exception:
        payload = None
    return {
        "listing_id": listing_id,
        "registry_url": registry_url,
        "payload": payload,
        "payload_json": payload_json,
        "published_at": published_at,
        "registry_assigned_id": registry_assigned_id,
        "status": status,
        "last_error": last_error,
    }


class SQLiteClient:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._ensure_parent_dir()
        self._ensure_tables_sync()

    def _ensure_parent_dir(self) -> None:
        # Resolve to absolute so log messages name the actual on-disk location,
        # not something relative to a cwd the caller may not have set.
        abs_path = os.path.abspath(self.db_path)
        parent = os.path.dirname(abs_path) or "."
        try:
            os.makedirs(parent, exist_ok=True)
        except OSError as exc:
            raise RuntimeError(
                f"Cannot create SQLite parent directory {parent!r} "
                f"(resolved from db_path={self.db_path!r}): {exc}"
            ) from exc
        logger.info("SQLite db path resolved to %s", abs_path)

    def _ensure_tables_sync(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.cursor()
            # ---------------------------------------------------------
            # Legacy schema migration: rename `orders` → `listings`
            # plus its columns to match the listings vocabulary used on
            # the wire. Idempotent: skipped when the new table already
            # exists.
            # ---------------------------------------------------------
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='orders'"
            )
            has_legacy_orders = cur.fetchone() is not None
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='listings'"
            )
            has_listings = cur.fetchone() is not None
            if has_legacy_orders and not has_listings:
                cur.execute("ALTER TABLE orders RENAME TO listings")
                for old_col, new_col in (
                    ("order_id", "listing_id"),
                    ("order_maker", "seller"),
                    ("order_taker", "buyer"),
                    ("maker_attestation", "seller_attestation"),
                    ("taker_attestation", "buyer_attestation"),
                ):
                    try:
                        cur.execute(f"ALTER TABLE listings RENAME COLUMN {old_col} TO {new_col}")
                    except sqlite3.OperationalError:
                        pass
                for old_idx in (
                    "idx_orders_status",
                    "idx_orders_created_at",
                    "idx_orders_updated_at",
                ):
                    try:
                        cur.execute(f"DROP INDEX IF EXISTS {old_idx}")
                    except sqlite3.OperationalError:
                        pass

            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='negotiation_threads'"
            )
            if cur.fetchone() is not None:
                for old_col, new_col in (
                    ("our_order_id", "our_listing_id"),
                    ("their_order_id", "their_listing_id"),
                ):
                    try:
                        cur.execute(f"ALTER TABLE negotiation_threads RENAME COLUMN {old_col} TO {new_col}")
                    except sqlite3.OperationalError:
                        pass
                for old_idx in (
                    "idx_negotiation_threads_our_order_id",
                    "idx_negotiation_threads_their_order_id",
                ):
                    try:
                        cur.execute(f"DROP INDEX IF EXISTS {old_idx}")
                    except sqlite3.OperationalError:
                        pass

            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='credentials'"
            )
            if cur.fetchone() is not None:
                try:
                    cur.execute("ALTER TABLE credentials RENAME COLUMN order_id TO listing_id")
                except sqlite3.OperationalError:
                    pass

            # stage_events: column rename order_id → listing_id (e2e tests
            # query GET /api/v1/system/events?listing_id=... and the WHERE
            # clause crashes if the legacy column name is still on disk).
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='stage_events'"
            )
            if cur.fetchone() is not None:
                try:
                    cur.execute("ALTER TABLE stage_events RENAME COLUMN order_id TO listing_id")
                except sqlite3.OperationalError:
                    pass
                for old_idx in (
                    "idx_credentials_order_id",
                    "idx_credentials_order_granted",
                ):
                    try:
                        cur.execute(f"DROP INDEX IF EXISTS {old_idx}")
                    except sqlite3.OperationalError:
                        pass

            # Drop legacy policy / decision tables (procedural-policy refactor).
            # Idempotent: noop once the tables are gone.
            for legacy_table in (
                "decision_outcomes",
                "decisions",
                "policy_composites",
                "policies",
            ):
                try:
                    cur.execute(f"DROP TABLE IF EXISTS {legacy_table}")
                except sqlite3.OperationalError:
                    pass
            for legacy_idx in (
                "idx_decisions_event_id",
                "idx_decisions_event_type",
                "idx_decisions_timestamp",
                "idx_decisions_agent_id",
            ):
                try:
                    cur.execute(f"DROP INDEX IF EXISTS {legacy_idx}")
                except sqlite3.OperationalError:
                    pass

            # Negotiation threads table. ``buyer`` / ``matched_offer_id``
            # capture the buyer↔seller pairing — they were previously stored
            # on the listings row (one buyer per listing), but multi-escrow
            # deals make the thread the natural place for that association.
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS negotiation_threads (
                  negotiation_id TEXT PRIMARY KEY,
                  our_listing_id TEXT,
                  their_listing_id TEXT,
                  our_agent_id TEXT,
                  their_agent_id TEXT,
                  status TEXT DEFAULT 'active',
                  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                  terminal_state TEXT,
                  -- Buyer's duration ask, captured at /negotiate/new and validated
                  -- against the listing's max_duration_seconds (NULL there means
                  -- unlimited). Stays for the lifetime of the thread; the agreed
                  -- value below is just an echo when the negotiation succeeds.
                  requested_duration_seconds INTEGER,
                  -- Buyer's escrow shape proposal — opaque JSON blob captured at
                  -- /negotiate/new (validated against the listing's acceptance
                  -- set). Persisted because settlement-time verification
                  -- reconstructs the expected on-chain obligation_data from
                  -- this; reading from the thread instead of re-deriving from
                  -- the listing means the negotiated artifact is the literal
                  -- source of truth.
                  buyer_escrow_proposal TEXT,
                  -- Committed agreement artifact: populated when terminal_state='success'.
                  -- Captures the negotiation's output as queryable state so settlement
                  -- can run (or be retried) as a separate step without replaying rounds.
                  agreed_price INTEGER,
                  agreed_duration_seconds INTEGER,
                  agreed_at TEXT,
                  -- Buyer↔listing pairing (moved off listings for multi-escrow).
                  buyer TEXT,
                  matched_offer_id TEXT
                )
                """
            )
            # Add columns if they don't exist (for existing databases)
            try:
                cur.execute("ALTER TABLE negotiation_threads ADD COLUMN our_listing_id TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists
            try:
                cur.execute("ALTER TABLE negotiation_threads ADD COLUMN their_listing_id TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                cur.execute("ALTER TABLE negotiation_threads ADD COLUMN our_agent_id TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                cur.execute("ALTER TABLE negotiation_threads ADD COLUMN their_agent_id TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                cur.execute("ALTER TABLE negotiation_threads ADD COLUMN status TEXT DEFAULT 'active'")
            except sqlite3.OperationalError:
                pass
            try:
                cur.execute("ALTER TABLE negotiation_threads ADD COLUMN created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))")
            except sqlite3.OperationalError:
                pass
            try:
                cur.execute("ALTER TABLE negotiation_threads ADD COLUMN updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))")
            except sqlite3.OperationalError:
                pass
            try:
                cur.execute("ALTER TABLE negotiation_threads ADD COLUMN terminal_state TEXT")
            except sqlite3.OperationalError:
                pass
            # Committed-agreement columns (see CREATE TABLE above for semantics).
            try:
                cur.execute("ALTER TABLE negotiation_threads ADD COLUMN agreed_price INTEGER")
            except sqlite3.OperationalError:
                pass
            try:
                cur.execute("ALTER TABLE negotiation_threads ADD COLUMN agreed_duration_seconds INTEGER")
            except sqlite3.OperationalError:
                pass
            try:
                cur.execute("ALTER TABLE negotiation_threads ADD COLUMN requested_duration_seconds INTEGER")
            except sqlite3.OperationalError:
                pass
            try:
                cur.execute("ALTER TABLE negotiation_threads ADD COLUMN buyer_escrow_proposal TEXT")
            except sqlite3.OperationalError:
                pass
            # Migrate: rename pre-cutover column buyer_escrow_terms_proposal →
            # buyer_escrow_proposal. The shape of the persisted JSON also
            # changed (drops escrow_kind / arbiter_kind / token,
            # adds chain_name / escrow_address / fields). We copy the
            # blob unchanged — settlement that reads it back must handle
            # both old and new shapes during the rollover, then we drop
            # the old column. Safe to re-run.
            existing_neg_cols = {
                r[1] for r in cur.execute("PRAGMA table_info(negotiation_threads)")
            }
            if (
                "buyer_escrow_terms_proposal" in existing_neg_cols
                and "buyer_escrow_proposal" in existing_neg_cols
            ):
                cur.execute(
                    "UPDATE negotiation_threads SET buyer_escrow_proposal = "
                    "buyer_escrow_terms_proposal "
                    "WHERE buyer_escrow_proposal IS NULL"
                )
                try:
                    cur.execute(
                        "ALTER TABLE negotiation_threads DROP COLUMN buyer_escrow_terms_proposal"
                    )
                except sqlite3.OperationalError:
                    pass
            try:
                cur.execute("ALTER TABLE negotiation_threads ADD COLUMN agreed_at TEXT")
            except sqlite3.OperationalError:
                pass
            existing_neg_cols = {
                r[1] for r in cur.execute("PRAGMA table_info(negotiation_threads)")
            }
            if "agreed_duration_hours" in existing_neg_cols:
                cur.execute(
                    "UPDATE negotiation_threads SET agreed_duration_seconds = "
                    "CAST(agreed_duration_hours * 3600 AS INTEGER) "
                    "WHERE agreed_duration_seconds IS NULL AND agreed_duration_hours IS NOT NULL"
                )
                try:
                    cur.execute(
                        "ALTER TABLE negotiation_threads DROP COLUMN agreed_duration_hours"
                    )
                except sqlite3.OperationalError:
                    pass
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS negotiation_local_state (
                  negotiation_id TEXT NOT NULL,
                  owner_id TEXT NOT NULL,
                  our_initial_price INTEGER,
                  our_strategy TEXT,
                  PRIMARY KEY(negotiation_id, owner_id),
                  FOREIGN KEY(negotiation_id) REFERENCES negotiation_threads(negotiation_id)
                )
                """
            )
            # Negotiation messages table
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS negotiation_messages (
                  message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                  negotiation_id TEXT NOT NULL,
                  round INTEGER NOT NULL,
                  sender TEXT NOT NULL,
                  our_price INTEGER,
                  their_price INTEGER,
                  proposed_price INTEGER,
                  action_taken TEXT NOT NULL,
                  message_type TEXT NOT NULL,
                  timestamp TEXT NOT NULL,
                  FOREIGN KEY(negotiation_id) REFERENCES negotiation_threads(negotiation_id),
                  UNIQUE(negotiation_id, round)
                )
                """
            )
            # Migrate listings table: add columns that may be missing from older DBs
            try:
                cur.execute("ALTER TABLE listings ADD COLUMN oracle_address TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists
            # Listings table (local source of truth for the seller's own
            # advertisements). Multi-escrow deal records live on the
            # ``escrows`` table joined via the winning ``negotiation_id``;
            # the buyer/match association lives on ``negotiation_threads``.
            # accepted_escrows is a JSON array of {chain_name, escrow_address,
            # fields, price_per_hour} — the canonical pricing+escrow
            # advertisement. The legacy ``demand_resource`` and per-deal
            # ``escrow_uid``/``buyer``/``matched_offer_id``/
            # ``seller_attestation``/``buyer_attestation`` columns are
            # backfilled+dropped by ``_migrate_escrows_and_listings`` above.
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS listings (
                  listing_id TEXT PRIMARY KEY,
                  status TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  offer_resource TEXT NOT NULL,
                  fulfillment_resource TEXT,
                  max_duration_seconds INTEGER,
                  seller TEXT NOT NULL,
                  oracle_address TEXT,
                  paused INTEGER NOT NULL DEFAULT 0,
                  accepted_escrows TEXT
                )
                """
            )
            # Migrate: add accepted_escrows column if missing (existing
            # databases). Backfill in a separate pass so we don't fail when
            # the column has already been added by an earlier process.
            try:
                cur.execute("ALTER TABLE listings ADD COLUMN accepted_escrows TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists
            # One-shot backfill: synthesize accepted_escrows from the legacy
            # demand_resource column for any pre-cutover rows. No-op when the
            # column has already been dropped. Skips rows the synthesis can't
            # resolve (e.g. anvil without an override JSON).
            existing_listing_cols = {
                r[1] for r in cur.execute("PRAGMA table_info(listings)")
            }
            if "demand_resource" in existing_listing_cols:
                self._backfill_accepted_escrows(cur)
                # Post-backfill, drop the demand_resource column. Requires
                # SQLite 3.35+ (Mar 2021); silently skipped on older builds.
                try:
                    cur.execute("ALTER TABLE listings DROP COLUMN demand_resource")
                except sqlite3.OperationalError:
                    pass
            # Migrate: add paused column if missing (existing databases).
            try:
                cur.execute("ALTER TABLE listings ADD COLUMN paused INTEGER NOT NULL DEFAULT 0")
            except sqlite3.OperationalError:
                pass  # Column already exists
            # Migrate: add max_duration_seconds; backfill from legacy
            # duration_hours if it's still around. NULL = unlimited.
            try:
                cur.execute("ALTER TABLE listings ADD COLUMN max_duration_seconds INTEGER")
            except sqlite3.OperationalError:
                pass
            existing_cols = {r[1] for r in cur.execute("PRAGMA table_info(listings)")}
            if "duration_hours" in existing_cols:
                cur.execute(
                    "UPDATE listings SET max_duration_seconds = "
                    "CAST(duration_hours * 3600 AS INTEGER) "
                    "WHERE max_duration_seconds IS NULL AND duration_hours IS NOT NULL"
                )
                try:
                    cur.execute("ALTER TABLE listings DROP COLUMN duration_hours")
                except sqlite3.OperationalError:
                    pass
            # Resources table (local source of truth across all resource types).
            # min_price/token/max_duration_seconds are per-offering: each row
            # carries the price + max-duration ceiling the operator wants per
            # published listing for that resource. NULLs fall back to
            # [seller.pricing] defaults at publish time.
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS resources (
                  pk INTEGER PRIMARY KEY AUTOINCREMENT,
                  resource_id TEXT NOT NULL UNIQUE,
                  resource_type TEXT NOT NULL,
                  resource_subtype TEXT,
                  unit TEXT,
                  value NUMERIC,
                  state TEXT,
                  attributes TEXT,
                  min_price TEXT,
                  token TEXT,
                  max_duration_seconds INTEGER,
                  created_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')),
                  updated_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'))
                )
                """
            )
            # Idempotent migration for existing databases that pre-date these
            # columns. ALTER TABLE ADD COLUMN raises OperationalError if the
            # column already exists.
            for col_ddl in (
                "ALTER TABLE resources ADD COLUMN min_price TEXT",
                "ALTER TABLE resources ADD COLUMN token TEXT",
                "ALTER TABLE resources ADD COLUMN max_duration_seconds INTEGER",
            ):
                try:
                    cur.execute(col_ddl)
                except sqlite3.OperationalError:
                    pass
            # Keep resources.updated_at fresh whenever rows are updated.
            cur.execute(
                """
                CREATE TRIGGER IF NOT EXISTS trg_resources_updated_at
                AFTER UPDATE ON resources
                FOR EACH ROW
                WHEN NEW.updated_at = OLD.updated_at
                BEGIN
                  UPDATE resources
                  SET updated_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')
                  WHERE pk = NEW.pk;
                END
                """
            )
            # Hosts table (one row per physical host the seller owns).
            # Mirrors provisioning-service's hosts inventory + adds marketing
            # metadata (cpu_type, motherboard, host capacity totals, network)
            # that the provisioning-service doesn't track. Compute slice
            # resources reference a host by name via attributes.vm_host.
            #
            # Capacity invariants are checked at publish time, not enforced
            # by SQLite — sum of active resources' gpu_count/vcpu_count/
            # ram_gb/disk_gb per host must not exceed the host totals.
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS hosts (
                  name TEXT PRIMARY KEY,
                  cpu_type TEXT,
                  host_cpu_cores INTEGER,
                  host_ram_gb INTEGER,
                  host_disk_gb INTEGER,
                  host_disk_type TEXT,
                  motherboard TEXT,
                  total_gpu_count INTEGER,
                  gpu_model TEXT,
                  gpu_interconnect TEXT,
                  nic_speed_gbps INTEGER,
                  internet_download_mbps INTEGER,
                  internet_upload_mbps INTEGER,
                  static_ip INTEGER,
                  open_ports_count INTEGER,
                  region TEXT,
                  datacenter_grade INTEGER,
                  attributes TEXT,
                  enabled INTEGER NOT NULL DEFAULT 1,
                  created_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')),
                  updated_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'))
                )
                """
            )
            cur.execute(
                """
                CREATE TRIGGER IF NOT EXISTS trg_hosts_updated_at
                AFTER UPDATE ON hosts
                FOR EACH ROW
                WHEN NEW.updated_at = OLD.updated_at
                BEGIN
                  UPDATE hosts
                  SET updated_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')
                  WHERE name = NEW.name;
                END
                """
            )
            # Resource transition events (append-only, idempotent)
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS resource_transition_events (
                  pk INTEGER PRIMARY KEY AUTOINCREMENT,
                  event_id TEXT NOT NULL UNIQUE,
                  resource_id TEXT NOT NULL,
                  event_type TEXT NOT NULL,
                  set_value NUMERIC,
                  set_state TEXT,
                  set_attribute_json TEXT,
                  idempotency_key TEXT NOT NULL UNIQUE,
                  occurred_at TIMESTAMPTZ NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')),
                  FOREIGN KEY(resource_id) REFERENCES resources(resource_id)
                )
                """
            )
            # Credentials table (off-chain only, never exposed on-chain)
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS credentials (
                  id TEXT PRIMARY KEY,
                  listing_id TEXT NOT NULL,
                  role TEXT NOT NULL,
                  granted_to TEXT NOT NULL,
                  password TEXT,
                  ssh_commands TEXT,
                  ssh_key_path_host TEXT,
                  key_type TEXT,
                  created_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_credentials_listing_id ON credentials(listing_id)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_credentials_listing_granted ON credentials(listing_id, granted_to)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_negotiation_messages_negotiation_id ON negotiation_messages(negotiation_id)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_negotiation_messages_round ON negotiation_messages(negotiation_id, round)"
            )
            # Indexes for negotiation tracking
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_negotiation_threads_our_listing_id ON negotiation_threads(our_listing_id)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_negotiation_threads_their_listing_id ON negotiation_threads(their_listing_id)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_negotiation_threads_our_agent_id ON negotiation_threads(our_agent_id)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_negotiation_threads_their_agent_id ON negotiation_threads(their_agent_id)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_negotiation_threads_status ON negotiation_threads(status)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_listings_status ON listings(status)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_listings_created_at ON listings(created_at)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_listings_updated_at ON listings(updated_at)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_resources_resource_id ON resources(resource_id)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_resources_type_subtype ON resources(resource_type, resource_subtype)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_resources_state ON resources(state)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_resources_updated_at ON resources(updated_at)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_resource_transition_events_resource_time ON resource_transition_events(resource_id, occurred_at)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_resource_transition_events_type_time ON resource_transition_events(event_type, occurred_at)"
            )
            # Stage events — structured log of stage-boundary transitions,
            # queryable via CLI. Each row is the functional output of one
            # stage transition (discovery, negotiation, settlement, etc.).
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS stage_events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  ts TEXT NOT NULL,
                  stage TEXT NOT NULL,
                  event TEXT NOT NULL,
                  negotiation_id TEXT,
                  listing_id TEXT,
                  escrow_uid TEXT,
                  data TEXT NOT NULL
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_stage_events_ts ON stage_events(ts)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_stage_events_stage ON stage_events(stage)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_stage_events_negotiation_id ON stage_events(negotiation_id)"
            )
            # Escrows — per-attached-escrow lifecycle record. One row per
            # on-chain escrow lockup attached to a deal; multi-escrow deals
            # (primary payment + bond + penalty, etc.) get one row each. The
            # primary escrow drives provisioning (provisioning_job_id,
            # tenant_credentials, connection_details only populated there);
            # non-primary rows are lifecycle-tracked but don't trigger
            # fulfillment.
            #
            # ``escrow_uid`` (PK) is the buyer's escrow attestation UID;
            # ``fulfillment_uid`` is the seller's fulfillment attestation UID
            # — the matching obligation pair on chain.
            #
            # Evolved from the legacy ``settlement_jobs`` table (one row per
            # deal, single attestation_uid column). The helper below renames
            # the old table + widens columns + backfills from the listings
            # row when present.
            self._migrate_escrows_and_listings(cur)
            # ``escrow_uid`` is the EAS attestation UID of the buyer's escrow
            # obligation — i.e. it IS the buyer's attestation; no separate
            # column needed. ``fulfillment_uid`` is the seller's
            # fulfillment attestation, paired with the escrow at settle time.
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS escrows (
                  escrow_uid TEXT PRIMARY KEY,
                  negotiation_id TEXT NOT NULL,
                  status TEXT NOT NULL,
                  chain_name TEXT,
                  escrow_address TEXT,
                  is_primary INTEGER NOT NULL DEFAULT 1,
                  fulfillment_uid TEXT,
                  provisioning_job_id TEXT,
                  connection_details TEXT,
                  tenant_credentials TEXT,
                  reason TEXT,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_escrows_status ON escrows(status)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_escrows_negotiation ON escrows(negotiation_id)"
            )
            # Publications — record of which registries received which
            # payload for which listing. Updates and deletes consult this
            # to know what's where; per-registry payload mode (milestone b)
            # uses this as the durable record of fan-out shape divergence.
            # status: 'published' | 'failed' | 'unpublished'.
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS publications (
                  listing_id TEXT NOT NULL,
                  registry_url TEXT NOT NULL,
                  payload_json TEXT NOT NULL,
                  published_at INTEGER NOT NULL,
                  registry_assigned_id TEXT,
                  status TEXT NOT NULL,
                  last_error TEXT,
                  PRIMARY KEY (listing_id, registry_url)
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_publications_registry ON publications(registry_url)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_publications_status ON publications(status)"
            )
            conn.commit()
        finally:
            conn.close()

    def _serialize_resource(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value)
        except Exception:
            return str(value)

    def _deserialize_accepted_escrows(self, value: Any) -> list[dict[str, Any]] | None:
        """Return the ``accepted_escrows`` column as a Python list.

        The column is a JSON-serialised list of AcceptedEscrow entries
        (``{chain_name, escrow_address, fields, price_per_hour}``).
        Returns ``None`` when the column is NULL — callers that need to
        synthesise an entry from the legacy ``demand_resource`` field
        do so themselves.
        """
        if value is None:
            return None
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, list) else None
            except Exception:
                return None
        return None

    def _backfill_accepted_escrows(self, cur: sqlite3.Cursor) -> None:
        """One-shot in-place backfill of ``accepted_escrows`` from the
        legacy ``demand_resource`` column. Runs during schema init; only
        touches rows where ``accepted_escrows`` is NULL so it's safe to
        re-run. Skips rows whose demand_resource can't be mapped (no
        token, missing chain config, etc.) — those rows lose their
        pricing advertisement after the column is dropped.
        """
        rows = cur.execute(
            "SELECT listing_id, demand_resource FROM listings "
            "WHERE accepted_escrows IS NULL AND demand_resource IS NOT NULL"
        ).fetchall()
        for listing_id, demand_resource in rows:
            synthesized = synthesize_accepted_escrows_from_demand(demand_resource)
            if not synthesized:
                continue
            cur.execute(
                "UPDATE listings SET accepted_escrows=? WHERE listing_id=?",
                (json.dumps(synthesized), listing_id),
            )

    def _migrate_escrows_and_listings(self, cur: sqlite3.Cursor) -> None:
        """One-shot migration: ``settlement_jobs`` → ``escrows`` (multi-escrow
        per deal), with the per-deal columns moving off ``listings`` to either
        ``escrows`` (attestation UIDs) or ``negotiation_threads`` (buyer
        pairing).

        Idempotent: every step is guarded on table/column existence so it's
        safe to re-run on a partially-migrated DB.
        """
        def _table_exists(name: str) -> bool:
            return cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (name,),
            ).fetchone() is not None

        def _cols(table: str) -> set[str]:
            return {r[1] for r in cur.execute(f"PRAGMA table_info({table})")}

        # 1. Rename settlement_jobs → escrows if the old name still on disk.
        if _table_exists("settlement_jobs") and not _table_exists("escrows"):
            cur.execute("ALTER TABLE settlement_jobs RENAME TO escrows")
            for old_idx in ("idx_settlement_jobs_status", "idx_settlement_jobs_negotiation"):
                try:
                    cur.execute(f"DROP INDEX IF EXISTS {old_idx}")
                except sqlite3.OperationalError:
                    pass

        # 2. Add new escrows columns (idempotent). escrow_uid (PK) is the
        # buyer's escrow attestation UID — no separate buyer-side column.
        if _table_exists("escrows"):
            for col_ddl in (
                "ALTER TABLE escrows ADD COLUMN chain_name TEXT",
                "ALTER TABLE escrows ADD COLUMN escrow_address TEXT",
                "ALTER TABLE escrows ADD COLUMN is_primary INTEGER NOT NULL DEFAULT 1",
                "ALTER TABLE escrows ADD COLUMN fulfillment_uid TEXT",
            ):
                try:
                    cur.execute(col_ddl)
                except sqlite3.OperationalError:
                    pass

        # 3. Add buyer + matched_offer_id to negotiation_threads (idempotent).
        if _table_exists("negotiation_threads"):
            for col_ddl in (
                "ALTER TABLE negotiation_threads ADD COLUMN buyer TEXT",
                "ALTER TABLE negotiation_threads ADD COLUMN matched_offer_id TEXT",
            ):
                try:
                    cur.execute(col_ddl)
                except sqlite3.OperationalError:
                    pass

        # 4. Backfill from legacy columns. Only runs when the pre-cutover
        # columns are still on disk; produces no-ops otherwise.
        listing_cols = _cols("listings") if _table_exists("listings") else set()
        escrow_cols = _cols("escrows") if _table_exists("escrows") else set()

        # 4a. escrows.fulfillment_uid ← escrows.attestation_uid
        # (legacy column stored the seller's fulfillment UID).
        if "attestation_uid" in escrow_cols:
            cur.execute(
                "UPDATE escrows SET fulfillment_uid = attestation_uid "
                "WHERE fulfillment_uid IS NULL AND attestation_uid IS NOT NULL"
            )

        # 4b. listings.buyer_attestation was always identical to escrow_uid on
        # the storefront side (the column was a denormalized duplicate), so no
        # backfill is needed — the escrow row's PK is the buyer's attestation.

        # 4c. escrows.{chain_name,escrow_address} ← listings.accepted_escrows[0]
        # (joined via negotiation_threads). JSON parse Python-side.
        if (
            "accepted_escrows" in listing_cols
            and _table_exists("escrows")
            and _table_exists("negotiation_threads")
        ):
            rows = cur.execute(
                """
                SELECT escrows.escrow_uid, l.accepted_escrows
                FROM escrows
                JOIN negotiation_threads nt
                  ON nt.negotiation_id = escrows.negotiation_id
                JOIN listings l
                  ON l.listing_id = nt.our_listing_id
                WHERE escrows.chain_name IS NULL OR escrows.escrow_address IS NULL
                """
            ).fetchall()
            for escrow_uid, ae_blob in rows:
                if not ae_blob:
                    continue
                try:
                    ae_list = json.loads(ae_blob) if isinstance(ae_blob, str) else ae_blob
                except (ValueError, TypeError):
                    continue
                if not isinstance(ae_list, list) or not ae_list:
                    continue
                first = ae_list[0]
                if not isinstance(first, dict):
                    continue
                cur.execute(
                    "UPDATE escrows SET chain_name = ?, escrow_address = ? "
                    "WHERE escrow_uid = ?",
                    (first.get("chain_name"), first.get("escrow_address"), escrow_uid),
                )

        # 4d. negotiation_threads.{buyer,matched_offer_id} ← listings.{buyer,matched_offer_id}
        if "buyer" in listing_cols and _table_exists("negotiation_threads"):
            cur.execute(
                """
                UPDATE negotiation_threads
                SET buyer = (
                    SELECT l.buyer FROM listings l
                    WHERE l.listing_id = negotiation_threads.our_listing_id
                    LIMIT 1
                )
                WHERE buyer IS NULL
                """
            )
        if "matched_offer_id" in listing_cols and _table_exists("negotiation_threads"):
            cur.execute(
                """
                UPDATE negotiation_threads
                SET matched_offer_id = (
                    SELECT l.matched_offer_id FROM listings l
                    WHERE l.listing_id = negotiation_threads.our_listing_id
                    LIMIT 1
                )
                WHERE matched_offer_id IS NULL
                """
            )

        # 5. Drop legacy columns. SQLite 3.35+ supports DROP COLUMN; older
        # builds silently skip — those DBs carry orphan columns forever
        # (harmless, just bloat).
        for table, col in (
            ("escrows", "attestation_uid"),
            ("listings", "escrow_uid"),
            ("listings", "buyer_attestation"),
            ("listings", "seller_attestation"),
            ("listings", "buyer"),
            ("listings", "matched_offer_id"),
        ):
            if not _table_exists(table):
                continue
            try:
                cur.execute(f"ALTER TABLE {table} DROP COLUMN {col}")
            except sqlite3.OperationalError:
                pass

    def _normalize_resource(self, value: Any) -> dict[str, Any] | None:
        if value is None:
            return None
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, dict) else None
            except Exception:
                return None
        return None

    def _resources_equal(self, a: Any, b: Any) -> bool:
        a_dict = self._normalize_resource(a)
        b_dict = self._normalize_resource(b)
        if a_dict is None or b_dict is None:
            return False
        try:
            # Strip None-valued fields so that a buyer's sparse demand
            # (resource_id=None, vm_host=None) can match a seller's enriched
            # offer that has those fields populated.  Every non-null field in
            # `a` must be present and equal in `b`; extra fields in `b` are
            # ignored.
            a_clean = {k: v for k, v in a_dict.items() if v is not None}
            b_clean = {k: v for k, v in b_dict.items() if v is not None}
            if not a_clean:
                return False
            return all(b_clean.get(k) == v for k, v in a_clean.items())
        except Exception:
            return False

    async def upsert_resource(
        self,
        *,
        resource_id: str,
        resource_type: str,
        resource_subtype: str | None = None,
        unit: str | None = None,
        value: int | float | None = None,
        state: str | None = None,
        attributes: dict[str, Any] | None = None,
        min_price: str | None = None,
        token: str | None = None,
        max_duration_seconds: int | None = None,
    ) -> None:
        """Create or update a generic resource snapshot row.

        For ``compute.gpu`` rows that reference a known local host via
        ``attributes.vm_host``, runs a capacity check against the host's
        gpu_count / vcpu_count / ram_gb / disk_gb totals. Raises
        ``CapacityExceededError`` if the new commitment would over-allocate
        the host. Slices without ``vm_host`` or pointing at unknown hosts
        pass through unchecked.
        """
        # Capacity gate — only for active compute.gpu slices.
        if resource_type == "compute.gpu" and (state is None or state != "deleted"):
            from .capacity import check_slice_fits_host
            attrs = attributes or {}
            await check_slice_fits_host(
                sqlite_client=self,
                resource_id=resource_id,
                host_name=attrs.get("vm_host"),
                gpu_count=int(value) if value is not None else None,
                vcpu_count=attrs.get("vcpu_count"),
                ram_gb=attrs.get("ram_gb"),
                disk_gb=attrs.get("disk_gb"),
            )

        def _save() -> None:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                now_iso = datetime.now().isoformat()
                cur.execute(
                    """
                    INSERT INTO resources(
                      resource_id, resource_type, resource_subtype, unit, value, state, attributes,
                      min_price, token, max_duration_seconds, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(resource_id) DO UPDATE SET
                      resource_type=excluded.resource_type,
                      resource_subtype=excluded.resource_subtype,
                      unit=excluded.unit,
                      value=excluded.value,
                      state=excluded.state,
                      attributes=excluded.attributes,
                      min_price=excluded.min_price,
                      token=excluded.token,
                      max_duration_seconds=excluded.max_duration_seconds,
                      updated_at=excluded.updated_at
                    """,
                    (
                        resource_id,
                        resource_type,
                        resource_subtype,
                        unit,
                        value,
                        state,
                        json.dumps(attributes) if attributes is not None else None,
                        min_price,
                        token,
                        max_duration_seconds,
                        now_iso,
                        now_iso,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

        await asyncio.to_thread(_save)

    async def list_resources(
        self,
        *,
        resource_type: str | None = None,
        state: str | None = None,
    ) -> list[dict[str, Any]]:
        """List resource rows from local DB as generic DB-resource dicts."""
        def _load() -> list[dict[str, Any]]:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                clauses: list[str] = []
                params: list[Any] = []
                if resource_type is not None:
                    clauses.append("resource_type = ?")
                    params.append(resource_type)
                if state is not None:
                    clauses.append("state = ?")
                    params.append(state)
                else:
                    # Default listing omits soft-deleted resources.
                    clauses.append("(state IS NULL OR state != 'deleted')")
                where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
                cur.execute(
                    f"""
                    SELECT resource_id, resource_type, resource_subtype, unit, value, state, attributes,
                           min_price, token, max_duration_seconds, created_at, updated_at
                    FROM resources
                    {where_clause}
                    ORDER BY updated_at DESC
                    """,
                    tuple(params),
                )
                rows = cur.fetchall()
                result: list[dict[str, Any]] = []
                for (
                    row_resource_id,
                    row_resource_type,
                    row_resource_subtype,
                    row_unit,
                    row_value,
                    row_state,
                    row_attributes,
                    row_min_price,
                    row_token,
                    row_max_duration_seconds,
                    row_created_at,
                    row_updated_at,
                ) in rows:
                    attrs: dict[str, Any] = {}
                    if isinstance(row_attributes, str) and row_attributes.strip():
                        try:
                            parsed = json.loads(row_attributes)
                            if isinstance(parsed, dict):
                                attrs = parsed
                        except Exception:
                            attrs = {}
                    result.append(
                        {
                            "resource_id": row_resource_id,
                            "resource_type": row_resource_type,
                            "resource_subtype": row_resource_subtype,
                            "unit": row_unit,
                            "value": row_value,
                            "state": row_state,
                            "attributes": attrs,
                            "min_price": row_min_price,
                            "token": row_token,
                            "max_duration_seconds": row_max_duration_seconds,
                            "created_at": row_created_at,
                            "updated_at": row_updated_at,
                        }
                    )
                return result
            finally:
                conn.close()

        return await asyncio.to_thread(_load)

    async def get_resource(self, *, resource_id: str) -> dict[str, Any] | None:
        """Fetch a single resource row by resource_id."""
        def _load_one() -> dict[str, Any] | None:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT resource_id, resource_type, resource_subtype, unit, value, state, attributes,
                           min_price, token, max_duration_seconds, created_at, updated_at
                    FROM resources
                    WHERE resource_id = ?
                    LIMIT 1
                    """,
                    (resource_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None

                (
                    row_resource_id,
                    row_resource_type,
                    row_resource_subtype,
                    row_unit,
                    row_value,
                    row_state,
                    row_attributes,
                    row_min_price,
                    row_token,
                    row_max_duration_seconds,
                    row_created_at,
                    row_updated_at,
                ) = row
                attrs: dict[str, Any] = {}
                if isinstance(row_attributes, str) and row_attributes.strip():
                    try:
                        parsed = json.loads(row_attributes)
                        if isinstance(parsed, dict):
                            attrs = parsed
                    except Exception:
                        attrs = {}

                return {
                    "resource_id": row_resource_id,
                    "resource_type": row_resource_type,
                    "resource_subtype": row_resource_subtype,
                    "unit": row_unit,
                    "value": row_value,
                    "state": row_state,
                    "attributes": attrs,
                    "min_price": row_min_price,
                    "token": row_token,
                    "max_duration_seconds": row_max_duration_seconds,
                    "created_at": row_created_at,
                    "updated_at": row_updated_at,
                }
            finally:
                conn.close()

        return await asyncio.to_thread(_load_one)

    async def delete_resource(
        self,
        *,
        resource_id: str,
        idempotency_key: str | None = None,
        event_type: str = "delete_resource",
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Delete a resource by transitioning it to state='deleted'."""
        set_attribute: dict[str, Any] | None = None
        if reason:
            set_attribute = {"$.deleted_reason": reason}
        return await self.apply_resource_set_transition(
            resource_id=resource_id,
            event_type=event_type,
            idempotency_key=idempotency_key or f"delete_resource:{resource_id}",
            set_state="deleted",
            set_attribute=set_attribute,
        )

    async def upsert_resources_from_csv(
        self,
        *,
        csv_path: str,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Import resources from CSV file and upsert rows into the resources table."""
        report = await upsert_resources_from_csv(
            csv_path=csv_path,
            sqlite_client=self,
            dry_run=dry_run,
        )
        return report.to_dict()

    async def upsert_resources_from_csv_content(
        self,
        *,
        csv_content: str,
        source_label: str = "<inline>",
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Import resources from a CSV string and upsert rows into the resources table.

        Used when CSV content is delivered via config injection (e.g. the Helm
        ``resources_csv_inline`` value in the per-agent Secret) rather than a
        file path baked into the container image.
        """
        report = await upsert_resources_from_csv_content(
            csv_content=csv_content,
            source_label=source_label,
            sqlite_client=self,
            dry_run=dry_run,
        )
        return report.to_dict()

    async def upsert_hosts_from_csv(
        self,
        *,
        csv_path: str,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Import hosts from CSV and upsert rows into the hosts table."""
        report = await upsert_hosts_from_csv(
            csv_path=csv_path,
            sqlite_client=self,
            dry_run=dry_run,
        )
        return report.to_dict()

    # ------------------------------------------------------------------
    # Hosts CRUD — physical hosts owned by the seller
    # ------------------------------------------------------------------

    _HOST_COLUMNS = (
        "name",
        "cpu_type",
        "host_cpu_cores",
        "host_ram_gb",
        "host_disk_gb",
        "host_disk_type",
        "motherboard",
        "total_gpu_count",
        "gpu_model",
        "gpu_interconnect",
        "nic_speed_gbps",
        "internet_download_mbps",
        "internet_upload_mbps",
        "static_ip",
        "open_ports_count",
        "region",
        "datacenter_grade",
        "attributes",
        "enabled",
    )

    @staticmethod
    def _host_row_to_dict(row: tuple) -> dict[str, Any]:
        d: dict[str, Any] = {}
        for col, val in zip(SQLiteClient._HOST_COLUMNS, row):
            d[col] = val
        # Normalize types: bools come back as 0/1 ints
        for bcol in ("static_ip", "datacenter_grade", "enabled"):
            if d.get(bcol) is not None:
                d[bcol] = bool(d[bcol])
        # JSON-decode attributes if present
        raw_attrs = d.get("attributes")
        if isinstance(raw_attrs, str) and raw_attrs.strip():
            try:
                d["attributes"] = json.loads(raw_attrs)
            except json.JSONDecodeError:
                d["attributes"] = {}
        elif raw_attrs is None:
            d["attributes"] = None
        return d

    async def upsert_host(
        self,
        *,
        name: str,
        cpu_type: str | None = None,
        host_cpu_cores: int | None = None,
        host_ram_gb: int | None = None,
        host_disk_gb: int | None = None,
        host_disk_type: str | None = None,
        motherboard: str | None = None,
        total_gpu_count: int | None = None,
        gpu_model: str | None = None,
        gpu_interconnect: str | None = None,
        nic_speed_gbps: int | None = None,
        internet_download_mbps: int | None = None,
        internet_upload_mbps: int | None = None,
        static_ip: bool | None = None,
        open_ports_count: int | None = None,
        region: str | None = None,
        datacenter_grade: bool | None = None,
        attributes: dict[str, Any] | None = None,
        enabled: bool = True,
    ) -> None:
        """Create or update a host row."""
        def _save() -> None:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO hosts(
                      name, cpu_type, host_cpu_cores, host_ram_gb, host_disk_gb,
                      host_disk_type, motherboard, total_gpu_count, gpu_model,
                      gpu_interconnect, nic_speed_gbps, internet_download_mbps,
                      internet_upload_mbps, static_ip, open_ports_count, region,
                      datacenter_grade, attributes, enabled
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(name) DO UPDATE SET
                      cpu_type=excluded.cpu_type,
                      host_cpu_cores=excluded.host_cpu_cores,
                      host_ram_gb=excluded.host_ram_gb,
                      host_disk_gb=excluded.host_disk_gb,
                      host_disk_type=excluded.host_disk_type,
                      motherboard=excluded.motherboard,
                      total_gpu_count=excluded.total_gpu_count,
                      gpu_model=excluded.gpu_model,
                      gpu_interconnect=excluded.gpu_interconnect,
                      nic_speed_gbps=excluded.nic_speed_gbps,
                      internet_download_mbps=excluded.internet_download_mbps,
                      internet_upload_mbps=excluded.internet_upload_mbps,
                      static_ip=excluded.static_ip,
                      open_ports_count=excluded.open_ports_count,
                      region=excluded.region,
                      datacenter_grade=excluded.datacenter_grade,
                      attributes=excluded.attributes,
                      enabled=excluded.enabled,
                      updated_at=STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')
                    """,
                    (
                        name,
                        cpu_type,
                        host_cpu_cores,
                        host_ram_gb,
                        host_disk_gb,
                        host_disk_type,
                        motherboard,
                        total_gpu_count,
                        gpu_model,
                        gpu_interconnect,
                        nic_speed_gbps,
                        internet_download_mbps,
                        internet_upload_mbps,
                        int(static_ip) if static_ip is not None else None,
                        open_ports_count,
                        region,
                        int(datacenter_grade) if datacenter_grade is not None else None,
                        json.dumps(attributes) if attributes is not None else None,
                        int(bool(enabled)),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

        await asyncio.to_thread(_save)

    async def get_host(self, *, name: str) -> dict[str, Any] | None:
        """Read a single host row by name."""
        cols = ", ".join(self._HOST_COLUMNS)

        def _load() -> dict[str, Any] | None:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute(f"SELECT {cols} FROM hosts WHERE name = ?", (name,))
                row = cur.fetchone()
                if row is None:
                    return None
                return self._host_row_to_dict(row)
            finally:
                conn.close()

        return await asyncio.to_thread(_load)

    async def list_hosts(
        self,
        *,
        enabled_only: bool = True,
    ) -> list[dict[str, Any]]:
        """List host rows. Defaults to enabled hosts only."""
        cols = ", ".join(self._HOST_COLUMNS)

        def _load() -> list[dict[str, Any]]:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                where = "WHERE enabled = 1" if enabled_only else ""
                cur.execute(f"SELECT {cols} FROM hosts {where} ORDER BY name")
                return [self._host_row_to_dict(r) for r in cur.fetchall()]
            finally:
                conn.close()

        return await asyncio.to_thread(_load)

    async def host_capacity_remaining(self, *, name: str) -> dict[str, Any] | None:
        """Compute remaining capacity for a host: host totals minus the sum
        of active (non-deleted) compute slices currently allocated.

        Returns ``None`` if the host doesn't exist. Returns a dict with the
        four capacity dimensions (gpu_count, vcpu_count, ram_gb, disk_gb)
        plus their host limits and the sum of currently-allocated values.
        """
        host = await self.get_host(name=name)
        if host is None:
            return None

        def _sum_allocations() -> dict[str, int]:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT value, attributes
                    FROM resources
                    WHERE resource_type = 'compute.gpu'
                      AND (state IS NULL OR state != 'deleted')
                    """
                )
                totals = {"gpu_count": 0, "vcpu_count": 0, "ram_gb": 0, "disk_gb": 0}
                for row_value, row_attrs in cur.fetchall():
                    attrs = {}
                    if isinstance(row_attrs, str) and row_attrs.strip():
                        try:
                            attrs = json.loads(row_attrs)
                        except json.JSONDecodeError:
                            continue
                    if attrs.get("vm_host") != name:
                        continue
                    if row_value is not None:
                        totals["gpu_count"] += int(row_value)
                    for k in ("vcpu_count", "ram_gb", "disk_gb"):
                        v = attrs.get(k)
                        if v is not None:
                            totals[k] += int(v)
                return totals
            finally:
                conn.close()

        used = await asyncio.to_thread(_sum_allocations)
        return {
            "host_name": name,
            "limits": {
                "gpu_count": host.get("total_gpu_count"),
                "vcpu_count": host.get("host_cpu_cores"),
                "ram_gb": host.get("host_ram_gb"),
                "disk_gb": host.get("host_disk_gb"),
            },
            "used": used,
            "remaining": {
                k: (host_limit - used[k]) if (host_limit := host.get({
                    "gpu_count": "total_gpu_count",
                    "vcpu_count": "host_cpu_cores",
                    "ram_gb": "host_ram_gb",
                    "disk_gb": "host_disk_gb",
                }[k])) is not None else None
                for k in ("gpu_count", "vcpu_count", "ram_gb", "disk_gb")
            },
        }

    def ensure_default_resources(self, resources: list[dict[str, Any]]) -> None:
        """Seed default resources only when the resources table is empty."""
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM resources")
            count = int(cur.fetchone()[0] or 0)
            if count > 0:
                return

            now_iso = datetime.now().isoformat()
            for resource in resources:
                cur.execute(
                    """
                    INSERT INTO resources(
                      resource_id, resource_type, resource_subtype, unit, value, state, attributes, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        resource.get("resource_id"),
                        resource.get("resource_type"),
                        resource.get("resource_subtype"),
                        resource.get("unit"),
                        resource.get("value"),
                        resource.get("state"),
                        json.dumps(resource.get("attributes"))
                        if isinstance(resource.get("attributes"), dict)
                        else None,
                        now_iso,
                        now_iso,
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    async def apply_resource_transition(
        self,
        *,
        resource_id: str,
        event_type: str,
        idempotency_key: str,
        set_value: int | float | None = None,
        set_state: str | None = None,
        set_attribute: dict[str, Any] | None = None,
        event_id: str | None = None,
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        """Insert one transition event and apply one resource snapshot update.

        Supports direct-set semantics only: set_value, set_state, set_attribute.
        """
        if set_value is None and set_state is None and not set_attribute:
            raise ValueError("Transition must include set_value, set_state, or set_attribute")

        resolved_event_id = event_id or str(uuid.uuid4())
        set_attribute_json = json.dumps(set_attribute) if set_attribute else None

        def _apply() -> dict[str, Any]:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO resource_transition_events(
                      event_id, resource_id, event_type, set_value, set_state, set_attribute_json, idempotency_key, occurred_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE(?, STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')))
                    ON CONFLICT(idempotency_key) DO NOTHING
                    """,
                    (
                        resolved_event_id,
                        resource_id,
                        event_type,
                        set_value,
                        set_state,
                        set_attribute_json,
                        idempotency_key,
                        occurred_at,
                    ),
                )

                # Duplicate command retry: already applied.
                if cur.rowcount == 0:
                    conn.rollback()
                    return {
                        "applied": False,
                        "duplicate": True,
                        "resource_id": resource_id,
                        "event_id": resolved_event_id,
                        "idempotency_key": idempotency_key,
                    }

                updates: list[str] = []
                values: list[Any] = []

                if set_value is not None:
                    updates.append("value = ?")
                    values.append(set_value)

                if set_state is not None:
                    updates.append("state = ?")
                    values.append(set_state)

                if set_attribute:
                    attr_expr = "COALESCE(attributes, '{}')"
                    for path, path_value in set_attribute.items():
                        if not isinstance(path, str) or not path.startswith("$."):
                            raise ValueError(f"Invalid JSON path for set_attribute: {path}")
                        attr_expr = f"json_set({attr_expr}, ?, json(?))"
                        values.append(path)
                        values.append(json.dumps(path_value))
                    updates.append(f"attributes = {attr_expr}")

                updates.append("updated_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')")

                cur.execute(
                    f"UPDATE resources SET {', '.join(updates)} WHERE resource_id = ?",
                    (*values, resource_id),
                )
                if cur.rowcount == 0:
                    raise ValueError(f"Resource not found: {resource_id}")

                conn.commit()
                return {
                    "applied": True,
                    "duplicate": False,
                    "resource_id": resource_id,
                    "event_id": resolved_event_id,
                    "idempotency_key": idempotency_key,
                }
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

        return await asyncio.to_thread(_apply)

    async def apply_resource_set_transition(
        self,
        *,
        resource_id: str,
        event_type: str,
        idempotency_key: str,
        set_value: int | float | None = None,
        set_state: str | None = None,
        set_attribute: dict[str, Any] | None = None,
        event_id: str | None = None,
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        """Convenience wrapper for absolute-value transitions."""
        return await self.apply_resource_transition(
            resource_id=resource_id,
            event_type=event_type,
            idempotency_key=idempotency_key,
            set_value=set_value,
            set_state=set_state,
            set_attribute=set_attribute,
            event_id=event_id,
            occurred_at=occurred_at,
        )

    # TODO(refactor): Move compute-specific VM reservation logic to the Compute domain
    # as part of the resource portfolio refactor.
    async def reserve_available_compute_vm(
        self,
        *,
        required_attributes: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Reserve one available compute resource.

        Args:
            required_attributes: Optional exact-match filters (for example:
                {"region": "California, US", "gpu_model": "H200"}).
                Keys are checked first in resource attributes, then in top-level
                resource fields (resource_type/resource_subtype/unit/state/value).
        """
        def _reserve() -> dict[str, Any] | None:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute("BEGIN IMMEDIATE")
                cur.execute(
                    """
                    SELECT resource_id, resource_subtype, unit, state, value, attributes
                    FROM resources
                    WHERE resource_type = 'compute.gpu'
                      AND state = 'available'
                    ORDER BY updated_at ASC
                    """
                )
                rows = cur.fetchall()
                for resource_id, resource_subtype, unit, state, value, attributes_raw in rows:
                    attrs: dict[str, Any]
                    try:
                        attrs = json.loads(attributes_raw) if isinstance(attributes_raw, str) else {}
                    except Exception:
                        attrs = {}

                    if required_attributes:
                        top_level = {
                            "resource_id": resource_id,
                            "resource_type": "compute.gpu",
                            "resource_subtype": resource_subtype,
                            "unit": unit,
                            "state": state,
                            "value": value,
                        }
                        is_match = True
                        for key, expected in required_attributes.items():
                            actual = attrs.get(key, top_level.get(key))
                            if actual != expected:
                                is_match = False
                                break
                        if not is_match:
                            continue

                    vm_host = attrs.get("vm_host")
                    if not isinstance(vm_host, str) or not vm_host.strip():
                        continue

                    now_iso = datetime.now().isoformat()
                    cur.execute(
                        """
                        UPDATE resources
                        SET state = 'reserved',
                            updated_at = ?
                        WHERE resource_id = ?
                          AND state = 'available'
                        """,
                        (now_iso, resource_id),
                    )
                    if cur.rowcount != 1:
                        continue

                    cur.execute(
                        """
                        INSERT INTO resource_transition_events(
                          event_id, resource_id, event_type, set_value, set_state, set_attribute_json, idempotency_key, occurred_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(uuid.uuid4()),
                            resource_id,
                            "reserve_for_provisioning",
                            value,
                            "reserved",
                            None,
                            f"reserve:{resource_id}:{uuid.uuid4()}",
                            now_iso,
                        ),
                    )
                    conn.commit()
                    return {
                        "resource_id": resource_id,
                        "vm_host": vm_host,
                        "resource_subtype": resource_subtype,
                        "unit": unit,
                        "state": "reserved",
                        "value": value,
                        "attributes": attrs,
                    }

                conn.rollback()
                return None
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

        return await asyncio.to_thread(_reserve)

    async def select_available_compute_vm(
        self,
        *,
        required_attributes: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Read-only lookup of one available compute resource — no state change.

        Identical selection logic to ``reserve_available_compute_vm`` but
        performs no UPDATE and emits no transition event. Use this for
        dry-run / evaluate paths (e.g. POST /api/v1/admin/settle/{uid}/evaluate)
        that must not consume a resource slot.

        Args:
            required_attributes: Optional exact-match filters (for example:
                {"region": "California, US", "gpu_model": "H200"}).
        """
        def _select() -> dict[str, Any] | None:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT resource_id, resource_subtype, unit, state, value, attributes
                    FROM resources
                    WHERE resource_type = 'compute.gpu'
                      AND state = 'available'
                    ORDER BY updated_at ASC
                    """
                )
                rows = cur.fetchall()
                for resource_id, resource_subtype, unit, state, value, attributes_raw in rows:
                    attrs: dict[str, Any]
                    try:
                        attrs = json.loads(attributes_raw) if isinstance(attributes_raw, str) else {}
                    except Exception:
                        attrs = {}

                    if required_attributes:
                        top_level = {
                            "resource_id": resource_id,
                            "resource_type": "compute.gpu",
                            "resource_subtype": resource_subtype,
                            "unit": unit,
                            "state": state,
                            "value": value,
                        }
                        is_match = True
                        for key, expected in required_attributes.items():
                            actual = attrs.get(key, top_level.get(key))
                            if actual != expected:
                                is_match = False
                                break
                        if not is_match:
                            continue

                    vm_host = attrs.get("vm_host")
                    if not isinstance(vm_host, str) or not vm_host.strip():
                        continue

                    return {
                        "resource_id": resource_id,
                        "vm_host": vm_host,
                        "resource_subtype": resource_subtype,
                        "unit": unit,
                        "state": "available",
                        "value": value,
                        "attributes": attrs,
                    }

                return None
            finally:
                conn.close()

        return await asyncio.to_thread(_select)

    async def upsert_listing(
        self,
        *,
        listing_id: str,
        status: str,
        created_at: str,
        updated_at: str,
        offer_resource: Any,
        fulfillment_resource: Any | None,
        max_duration_seconds: int | None,
        seller: str,
        oracle_address: str | None = None,
        paused: bool = False,
        accepted_escrows: Any | None = None,
    ) -> None:
        def _save() -> None:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO listings(
                      listing_id,
                      status,
                      created_at,
                      updated_at,
                      offer_resource,
                      fulfillment_resource,
                      max_duration_seconds,
                      seller,
                      oracle_address,
                      paused,
                      accepted_escrows
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(listing_id) DO UPDATE SET
                      status=excluded.status,
                      updated_at=excluded.updated_at,
                      offer_resource=excluded.offer_resource,
                      fulfillment_resource=excluded.fulfillment_resource,
                      max_duration_seconds=excluded.max_duration_seconds,
                      seller=excluded.seller,
                      oracle_address=excluded.oracle_address,
                      paused=excluded.paused,
                      accepted_escrows=excluded.accepted_escrows
                    """,
                    (
                        listing_id,
                        status,
                        created_at,
                        updated_at,
                        self._serialize_resource(offer_resource),
                        self._serialize_resource(fulfillment_resource),
                        max_duration_seconds,
                        seller,
                        oracle_address,
                        1 if paused else 0,
                        self._serialize_resource(accepted_escrows),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

        await asyncio.to_thread(_save)

    async def update_listing(
        self,
        *,
        listing_id: str,
        status: str | None = None,
        updated_at: str | None = None,
        offer_resource: Any | None = None,
        fulfillment_resource: Any | None = None,
        max_duration_seconds: int | None = None,
        seller: str | None = None,
        oracle_address: str | None = None,
        accepted_escrows: Any | None = None,
    ) -> None:
        def _save() -> None:
            updates: list[str] = []
            values: list[Any] = []

            def add(field: str, value: Any, *, serialize: bool = False) -> None:
                if value is None:
                    return
                updates.append(f"{field}=?")
                values.append(self._serialize_resource(value) if serialize else value)

            add("status", status)
            add("updated_at", updated_at or datetime.now().isoformat())
            add("offer_resource", offer_resource, serialize=True)
            add("fulfillment_resource", fulfillment_resource, serialize=True)
            add("max_duration_seconds", max_duration_seconds)
            add("seller", seller)
            add("oracle_address", oracle_address)
            add("accepted_escrows", accepted_escrows, serialize=True)

            if not updates:
                return

            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    f"UPDATE listings SET {', '.join(updates)} WHERE listing_id=?",
                    (*values, listing_id),
                )
                conn.commit()
            finally:
                conn.close()

        await asyncio.to_thread(_save)

    async def load_listing(self, *, listing_id: str) -> dict[str, Any] | None:
        """Return a single order by listing_id, or None if not found."""
        def _load() -> dict[str, Any] | None:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT listing_id, status, created_at, updated_at,
                           offer_resource, fulfillment_resource,
                           max_duration_seconds, seller, oracle_address,
                           COALESCE(paused, 0) AS paused,
                           accepted_escrows
                    FROM listings WHERE listing_id = ?
                    """,
                    (listing_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                keys = [
                    "listing_id", "status", "created_at", "updated_at",
                    "offer_resource", "fulfillment_resource",
                    "max_duration_seconds", "seller", "oracle_address",
                    "paused", "accepted_escrows",
                ]
                d = dict(zip(keys, row))
                d["paused"] = bool(d["paused"])
                d["accepted_escrows"] = self._deserialize_accepted_escrows(
                    d.get("accepted_escrows"),
                )
                return d
            finally:
                conn.close()

        return await asyncio.to_thread(_load)


    async def save_negotiation_message(
        self,
        *,
        negotiation_id: str,
        round: int | None = None,
        sender: str,
        our_price: float | None,
        their_price: float | None,
        proposed_price: float | None,
        action_taken: str,
        message_type: str,
        timestamp: str,
    ) -> int:
        """Save a negotiation message to the database.

        Args:
            negotiation_id: Unique negotiation identifier
            round: Round number (if None, computed atomically as max(round) + 1)
            sender: Agent ID or card URL of the sender
            our_price: Our price in base units
            their_price: Their price in base units
            proposed_price: Proposed counter price
            action_taken: Action taken (ACCEPT_OFFER, REJECT_OFFER, COUNTER_OFFER, EXIT_NEGOTIATION)
            message_type: Type of message (initial_proposal, counter_proposal, etc.)
            timestamp: ISO format timestamp

        Returns:
            The actual round number that was assigned
        """
        def _save() -> int:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                # Ensure thread exists
                cur.execute(
                    """
                    INSERT OR IGNORE INTO negotiation_threads(negotiation_id, created_at, updated_at)
                    VALUES (?, ?, ?)
                    """,
                    (negotiation_id, timestamp, timestamp),
                )

                if round is None:
                    # Compute next round atomically to avoid race conditions
                    cur.execute(
                        """
                        SELECT COALESCE(MAX(round), -1) + 1
                        FROM negotiation_messages
                        WHERE negotiation_id = ?
                        """,
                        (negotiation_id,),
                    )
                    actual_round = cur.fetchone()[0]
                else:
                    actual_round = round

                # Update thread updated_at
                cur.execute(
                    """
                    UPDATE negotiation_threads SET updated_at = ? WHERE negotiation_id = ?
                    """,
                    (timestamp, negotiation_id),
                )
                # Insert message with ON CONFLICT handling to gracefully handle races
                cur.execute(
                    """
                    INSERT INTO negotiation_messages(
                        negotiation_id, round, sender, our_price, their_price,
                        proposed_price, action_taken, message_type, timestamp
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(negotiation_id, round) DO UPDATE SET
                        sender = excluded.sender,
                        our_price = excluded.our_price,
                        their_price = excluded.their_price,
                        proposed_price = excluded.proposed_price,
                        action_taken = excluded.action_taken,
                        message_type = excluded.message_type,
                        timestamp = excluded.timestamp
                    """,
                    (
                        negotiation_id, actual_round, sender, our_price, their_price,
                        proposed_price, action_taken, message_type, timestamp
                    ),
                )
                conn.commit()
                return actual_round
            finally:
                conn.close()

        return await asyncio.to_thread(_save)

    async def load_negotiation_thread(
        self,
        *,
        negotiation_id: str,
    ) -> list[dict[str, Any]]:
        """Load all messages for a negotiation thread, ordered by round."""
        def _load() -> list[dict[str, Any]]:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT round, sender, our_price, their_price, proposed_price,
                           action_taken, message_type, timestamp
                    FROM negotiation_messages
                    WHERE negotiation_id = ?
                    ORDER BY round ASC
                    """,
                    (negotiation_id,),
                )
                rows = cur.fetchall()
                result = []
                for row in rows:
                    result.append({
                        "round": row[0],
                        "sender": row[1],
                        "our_price": row[2],
                        "their_price": row[3],
                        "proposed_price": row[4],
                        "action_taken": row[5],
                        "message_type": row[6],
                        "timestamp": row[7],
                    })
                return result
            finally:
                conn.close()
        
        return await asyncio.to_thread(_load)

    async def update_negotiation_thread_terminal(
        self,
        *,
        negotiation_id: str,
        terminal_state: str | None,
    ) -> None:
        """Update the terminal state of a negotiation thread."""
        def _update() -> None:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    UPDATE negotiation_threads
                    SET terminal_state = ?, status = 'terminated', updated_at = ?
                    WHERE negotiation_id = ?
                    """,
                    (terminal_state, datetime.now().isoformat(), negotiation_id),
                )
                conn.commit()
            finally:
                conn.close()

        await asyncio.to_thread(_update)

    async def commit_agreed_terms(
        self,
        *,
        negotiation_id: str,
        agreed_price: float,
        agreed_duration_seconds: int,
    ) -> None:
        """Record the agreement artifact that comes out of a successful negotiation.

        Called before any settlement step touches the chain. Lets settlement
        run (or be retried) as a separate step by reading these columns,
        without replaying the round-by-round message history.

        ``agreed_price`` is the absolute payment amount in base units of
        the payment token (the column name is retained from before the
        per-hour → absolute refactor; semantically it now holds the
        amount, not a per-hour rate). ``agreed_duration_seconds`` echoes
        the buyer's negotiation-init ask and is used by settlement-time
        arbiter codecs that bind the seller's delivery window.
        """
        def _save() -> None:
            now = datetime.now().isoformat()
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    UPDATE negotiation_threads
                    SET agreed_price = ?,
                        agreed_duration_seconds = ?,
                        agreed_at = ?,
                        updated_at = ?
                    WHERE negotiation_id = ?
                    """,
                    (
                        float(agreed_price),
                        int(agreed_duration_seconds),
                        now,
                        now,
                        negotiation_id,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

        await asyncio.to_thread(_save)

    async def load_negotiation_thread_row(
        self,
        *,
        negotiation_id: str,
    ) -> dict[str, Any] | None:
        """Return the negotiation_threads row as a dict, or None if absent.

        ``buyer_escrow_proposal`` is the persisted JSON blob captured at
        /negotiate/new; deserialized back to a dict for the caller. The
        caller (settlement) re-types it via service.schemas.EscrowProposal.
        """
        def _load() -> dict[str, Any] | None:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT negotiation_id, our_listing_id, their_listing_id,
                           our_agent_id, their_agent_id, status,
                           created_at, updated_at, terminal_state,
                           requested_duration_seconds,
                           buyer_escrow_proposal,
                           agreed_price, agreed_duration_seconds, agreed_at,
                           buyer, matched_offer_id
                    FROM negotiation_threads WHERE negotiation_id = ?
                    """,
                    (negotiation_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                keys = [
                    "negotiation_id", "our_listing_id", "their_listing_id",
                    "our_agent_id", "their_agent_id", "status",
                    "created_at", "updated_at", "terminal_state",
                    "requested_duration_seconds",
                    "buyer_escrow_proposal",
                    "agreed_price", "agreed_duration_seconds", "agreed_at",
                    "buyer", "matched_offer_id",
                ]
                result = dict(zip(keys, row))
                # Deserialize the JSON blob back to a dict for the caller.
                raw_proposal = result.get("buyer_escrow_proposal")
                if isinstance(raw_proposal, str) and raw_proposal:
                    try:
                        result["buyer_escrow_proposal"] = json.loads(raw_proposal)
                    except (ValueError, TypeError):
                        # Preserve as the raw string if it doesn't parse;
                        # the caller can decide whether to error or proceed
                        # without the proposal.
                        pass
                return result
            finally:
                conn.close()

        return await asyncio.to_thread(_load)

    async def set_negotiation_thread_buyer_match(
        self,
        *,
        negotiation_id: str,
        buyer: str | None = None,
        matched_offer_id: str | None = None,
    ) -> None:
        """Write the buyer↔offer association onto the thread.

        Both fields are independent — pass only the ones you want to update.
        Called as the deal moves from negotiation into settlement.
        """
        def _save() -> None:
            updates: list[str] = []
            values: list[Any] = []
            if buyer is not None:
                updates.append("buyer = ?")
                values.append(buyer)
            if matched_offer_id is not None:
                updates.append("matched_offer_id = ?")
                values.append(matched_offer_id)
            if not updates:
                return
            updates.append("updated_at = ?")
            values.append(datetime.now().isoformat())
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute(
                    f"UPDATE negotiation_threads SET {', '.join(updates)} "
                    f"WHERE negotiation_id = ?",
                    (*values, negotiation_id),
                )
                conn.commit()
            finally:
                conn.close()

        await asyncio.to_thread(_save)

    # ------------------------------------------------------------------
    # escrows — per-escrow lifecycle row. One per on-chain escrow lockup
    # attached to a deal; primary row drives provisioning.
    # ------------------------------------------------------------------

    _ESCROW_COLS = (
        "escrow_uid",
        "negotiation_id",
        "status",
        "chain_name",
        "escrow_address",
        "is_primary",
        "fulfillment_uid",
        "provisioning_job_id",
        "connection_details",
        "tenant_credentials",
        "reason",
        "created_at",
        "updated_at",
    )

    def _escrow_row_to_dict(self, row: tuple) -> dict[str, Any]:
        d = dict(zip(self._ESCROW_COLS, row))
        d["is_primary"] = bool(d["is_primary"])
        return d

    async def insert_escrow(
        self,
        *,
        escrow_uid: str,
        negotiation_id: str,
        chain_name: str | None,
        escrow_address: str | None,
        is_primary: bool = True,
        status: str = "provisioning",
    ) -> bool:
        """Insert a new escrows row. Returns True on insert, False on
        PRIMARY KEY conflict (idempotent by escrow_uid)."""
        def _insert() -> bool:
            now = datetime.now().isoformat()
            conn = sqlite3.connect(self.db_path)
            try:
                try:
                    conn.execute(
                        """
                        INSERT INTO escrows
                          (escrow_uid, negotiation_id, status,
                           chain_name, escrow_address, is_primary,
                           created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            escrow_uid, negotiation_id, status,
                            chain_name, escrow_address, 1 if is_primary else 0,
                            now, now,
                        ),
                    )
                    conn.commit()
                    return True
                except sqlite3.IntegrityError:
                    return False
            finally:
                conn.close()

        return await asyncio.to_thread(_insert)

    async def update_escrow(
        self,
        *,
        escrow_uid: str,
        status: str | None = None,
        fulfillment_uid: str | None = None,
        provisioning_job_id: str | None = None,
        connection_details: str | None = None,
        tenant_credentials: str | None = None,
        reason: str | None = None,
    ) -> None:
        """Patch an escrows row. Any None field is skipped."""
        def _update() -> None:
            updates: list[str] = []
            values: list[Any] = []

            def add(col: str, val: Any) -> None:
                if val is None:
                    return
                updates.append(f"{col} = ?")
                values.append(val)

            add("status", status)
            add("fulfillment_uid", fulfillment_uid)
            add("provisioning_job_id", provisioning_job_id)
            add("connection_details", connection_details)
            add("tenant_credentials", tenant_credentials)
            add("reason", reason)
            if not updates:
                return
            updates.append("updated_at = ?")
            values.append(datetime.now().isoformat())

            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute(
                    f"UPDATE escrows SET {', '.join(updates)} WHERE escrow_uid = ?",
                    (*values, escrow_uid),
                )
                conn.commit()
            finally:
                conn.close()

        await asyncio.to_thread(_update)

    async def load_escrow(
        self,
        *,
        escrow_uid: str,
    ) -> dict[str, Any] | None:
        """Return the escrows row as a dict, or None if absent."""
        def _load() -> dict[str, Any] | None:
            conn = sqlite3.connect(self.db_path)
            try:
                row = conn.execute(
                    f"""
                    SELECT {', '.join(self._ESCROW_COLS)}
                    FROM escrows WHERE escrow_uid = ?
                    """,
                    (escrow_uid,),
                ).fetchone()
                return self._escrow_row_to_dict(row) if row else None
            finally:
                conn.close()

        return await asyncio.to_thread(_load)

    async def load_primary_escrow_for_negotiation(
        self,
        *,
        negotiation_id: str,
    ) -> dict[str, Any] | None:
        """Return the primary escrow row for a negotiation, or None."""
        def _load() -> dict[str, Any] | None:
            conn = sqlite3.connect(self.db_path)
            try:
                row = conn.execute(
                    f"""
                    SELECT {', '.join(self._ESCROW_COLS)}
                    FROM escrows
                    WHERE negotiation_id = ? AND is_primary = 1
                    ORDER BY created_at ASC LIMIT 1
                    """,
                    (negotiation_id,),
                ).fetchone()
                return self._escrow_row_to_dict(row) if row else None
            finally:
                conn.close()

        return await asyncio.to_thread(_load)

    async def load_primary_escrow_for_listing(
        self,
        *,
        listing_id: str,
    ) -> dict[str, Any] | None:
        """Return the primary escrow row for the listing's winning thread.

        Joins escrows → negotiation_threads on negotiation_id. Returns the
        oldest is_primary=1 row across all threads matching this listing;
        in practice each listing has at most one winning negotiation, so the
        ordering is just a tiebreaker for corner cases.
        """
        def _load() -> dict[str, Any] | None:
            conn = sqlite3.connect(self.db_path)
            try:
                row = conn.execute(
                    f"""
                    SELECT {', '.join('e.' + c for c in self._ESCROW_COLS)}
                    FROM escrows e
                    JOIN negotiation_threads nt
                      ON nt.negotiation_id = e.negotiation_id
                    WHERE nt.our_listing_id = ? AND e.is_primary = 1
                    ORDER BY e.created_at ASC LIMIT 1
                    """,
                    (listing_id,),
                ).fetchone()
                return self._escrow_row_to_dict(row) if row else None
            finally:
                conn.close()

        return await asyncio.to_thread(_load)

    async def upsert_publication(
        self,
        *,
        listing_id: str,
        registry_url: str,
        payload: dict[str, Any] | str,
        status: str,
        registry_assigned_id: str | None = None,
        last_error: str | None = None,
        published_at: int | None = None,
    ) -> None:
        """Record (or refresh) a publish attempt for one (listing, registry)
        pair. The row carries the exact payload sent — the registry may have
        a different listing_shape than another registry in the fan-out — so
        the caller can read it back later for updates/deletes.

        ``payload`` accepts a dict (json.dumps'd) or a pre-serialised string.
        ``published_at`` defaults to the current epoch second.
        """
        def _upsert() -> None:
            if isinstance(payload, str):
                payload_str = payload
            else:
                payload_str = json.dumps(payload)
            now = published_at if published_at is not None else int(time.time())
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute(
                    """
                    INSERT INTO publications
                      (listing_id, registry_url, payload_json, published_at,
                       registry_assigned_id, status, last_error)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(listing_id, registry_url) DO UPDATE SET
                      payload_json = excluded.payload_json,
                      published_at = excluded.published_at,
                      registry_assigned_id = excluded.registry_assigned_id,
                      status = excluded.status,
                      last_error = excluded.last_error
                    """,
                    (
                        listing_id, registry_url, payload_str, now,
                        registry_assigned_id, status, last_error,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

        await asyncio.to_thread(_upsert)

    async def load_publication(
        self, *, listing_id: str, registry_url: str,
    ) -> dict[str, Any] | None:
        """Return a single publications row as a dict, or None."""
        def _load() -> dict[str, Any] | None:
            conn = sqlite3.connect(self.db_path)
            try:
                row = conn.execute(
                    """
                    SELECT listing_id, registry_url, payload_json, published_at,
                           registry_assigned_id, status, last_error
                    FROM publications
                    WHERE listing_id = ? AND registry_url = ?
                    """,
                    (listing_id, registry_url),
                ).fetchone()
                if not row:
                    return None
                return _publication_row_to_dict(row)
            finally:
                conn.close()

        return await asyncio.to_thread(_load)

    async def load_publications(
        self, *, listing_id: str,
    ) -> list[dict[str, Any]]:
        """Return all publications for one listing (one row per registry)."""
        def _load() -> list[dict[str, Any]]:
            conn = sqlite3.connect(self.db_path)
            try:
                rows = conn.execute(
                    """
                    SELECT listing_id, registry_url, payload_json, published_at,
                           registry_assigned_id, status, last_error
                    FROM publications WHERE listing_id = ?
                    ORDER BY registry_url
                    """,
                    (listing_id,),
                ).fetchall()
                return [_publication_row_to_dict(r) for r in rows]
            finally:
                conn.close()

        return await asyncio.to_thread(_load)

    async def list_publications(
        self, *, registry_url: str | None = None, status: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return publications optionally filtered by registry and/or status."""
        def _list() -> list[dict[str, Any]]:
            clauses: list[str] = []
            params: list[Any] = []
            if registry_url is not None:
                clauses.append("registry_url = ?")
                params.append(registry_url)
            if status is not None:
                clauses.append("status = ?")
                params.append(status)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            conn = sqlite3.connect(self.db_path)
            try:
                rows = conn.execute(
                    f"""
                    SELECT listing_id, registry_url, payload_json, published_at,
                           registry_assigned_id, status, last_error
                    FROM publications {where}
                    ORDER BY listing_id, registry_url
                    """,
                    tuple(params),
                ).fetchall()
                return [_publication_row_to_dict(r) for r in rows]
            finally:
                conn.close()

        return await asyncio.to_thread(_list)

    async def delete_publication(
        self, *, listing_id: str, registry_url: str,
    ) -> None:
        """Hard-delete a publications row (used when a registry-side listing
        is gone for good — distinct from status='unpublished' which keeps
        the row as a tombstone)."""
        def _delete() -> None:
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute(
                    "DELETE FROM publications WHERE listing_id = ? AND registry_url = ?",
                    (listing_id, registry_url),
                )
                conn.commit()
            finally:
                conn.close()

        await asyncio.to_thread(_delete)

    async def delete_negotiation_thread(
        self,
        *,
        negotiation_id: str,
    ) -> None:
        """Delete a negotiation thread and all its messages."""
        def _delete() -> None:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                # Delete messages first (foreign key constraint)
                cur.execute(
                    "DELETE FROM negotiation_messages WHERE negotiation_id = ?",
                    (negotiation_id,),
                )
                # Delete local state
                cur.execute(
                    "DELETE FROM negotiation_local_state WHERE negotiation_id = ?",
                    (negotiation_id,),
                )
                # Delete thread
                cur.execute(
                    "DELETE FROM negotiation_threads WHERE negotiation_id = ?",
                    (negotiation_id,),
                )
                conn.commit()
            finally:
                conn.close()
        
        await asyncio.to_thread(_delete)

    async def create_negotiation_thread(
        self,
        *,
        negotiation_id: str,
        our_listing_id: str,
        their_listing_id: str,
        our_agent_id: str,
        their_agent_id: str,
        owner_id: str,  # The agent creating this record
        status: str = "active",
        our_initial_price: float | None = None,
        our_strategy: str | None = None,
        requested_duration_seconds: int | None = None,
        buyer_escrow_proposal: dict[str, Any] | None = None,
    ) -> None:
        """Create a new negotiation thread with private local state.

        Args:
            negotiation_id: Unique negotiation identifier
            our_listing_id: Our order ID
            their_listing_id: Their order ID
            our_agent_id: Our agent ID (participant A)
            their_agent_id: Their agent ID (participant B)
            owner_id: ID of the agent owning this private state
            status: Initial status (default: 'active')
            our_initial_price: Private initial price
            our_strategy: Private strategy
            requested_duration_seconds: Buyer's duration ask from /negotiate/new.
                Validated against the listing's max_duration_seconds upstream.
            buyer_escrow_proposal: The buyer's accepted escrow proposal,
                persisted as a JSON blob. Settlement reads this back to
                reconstruct the expected on-chain obligation_data. None
                for legacy clients that didn't send a proposal.
        """
        def _create() -> None:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                timestamp = datetime.now().isoformat()
                proposal_blob = (
                    json.dumps(buyer_escrow_proposal)
                    if buyer_escrow_proposal is not None
                    else None
                )

                # Insert public thread info (ignore if exists, it's shared)
                cur.execute(
                    """
                    INSERT OR IGNORE INTO negotiation_threads(
                        negotiation_id, our_listing_id, their_listing_id,
                        our_agent_id, their_agent_id, status,
                        requested_duration_seconds,
                        buyer_escrow_proposal,
                        created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        negotiation_id, our_listing_id, their_listing_id,
                        our_agent_id, their_agent_id, status,
                        requested_duration_seconds,
                        proposal_blob,
                        timestamp, timestamp,
                    ),
                )
                
                # Insert private local state (upsert if needed)
                cur.execute(
                    """
                    INSERT INTO negotiation_local_state(
                        negotiation_id, owner_id, our_initial_price, our_strategy
                    )
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(negotiation_id, owner_id) DO UPDATE SET
                        our_initial_price = excluded.our_initial_price,
                        our_strategy = excluded.our_strategy
                    """,
                    (negotiation_id, owner_id, our_initial_price, our_strategy),
                )
                
                conn.commit()
            finally:
                conn.close()
        await asyncio.to_thread(_create)

    async def get_thread_info(
        self,
        *,
        negotiation_id: str,
        owner_id: str,
    ) -> dict[str, Any] | None:
        """Get negotiation thread metadata joining public thread with private local state.
        
        Args:
            negotiation_id: Unique negotiation identifier
            owner_id: ID of the agent requesting the info
        
        Returns:
            Merged dictionary with public + private info, or None if thread doesn't exist.
        """
        def _get() -> dict[str, Any] | None:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT t.negotiation_id, t.our_listing_id, t.their_listing_id,
                           t.our_agent_id, t.their_agent_id, t.status,
                           l.our_initial_price, l.our_strategy
                    FROM negotiation_threads t
                    LEFT JOIN negotiation_local_state l 
                           ON t.negotiation_id = l.negotiation_id AND l.owner_id = ?
                    WHERE t.negotiation_id = ?
                    """,
                    (owner_id, negotiation_id),
                )
                row = cur.fetchone()
                if row:
                    return {
                        "negotiation_id": row[0],
                        "our_listing_id": row[1],
                        "their_listing_id": row[2],
                        "our_agent_id": row[3],
                        "their_agent_id": row[4],
                        "status": row[5],
                        # Default to None if no local state found for this owner
                        "our_initial_price": row[6],
                        "our_strategy": row[7],
                    }
                return None
            finally:
                conn.close()
        return await asyncio.to_thread(_get)

    async def check_existing_negotiation(
        self,
        *,
        our_listing_id: str | None = None,
        their_listing_id: str | None = None,
        our_agent_id: str | None = None,
        their_agent_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Check if an active negotiation already exists between two orders or agents (bidirectional).
        
        Returns:
            Dictionary with negotiation details if found, None otherwise
        """
        def _check() -> dict[str, Any] | None:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                query = """
                    SELECT negotiation_id, our_listing_id, their_listing_id, our_agent_id, their_agent_id, status
                    FROM negotiation_threads
                    WHERE status = 'active' AND (
                        (our_listing_id = ? AND their_listing_id = ?) OR
                        (our_listing_id = ? AND their_listing_id = ?) OR
                        (our_agent_id = ? AND their_agent_id = ?) OR
                        (our_agent_id = ? AND their_agent_id = ?)
                    )
                """
                params = (
                    our_listing_id, their_listing_id,
                    their_listing_id, our_listing_id,
                    our_agent_id, their_agent_id,
                    their_agent_id, our_agent_id,
                )
                cur.execute(query, params)
                row = cur.fetchone()
                if row:
                    return {
                        "negotiation_id": row[0],
                        "our_listing_id": row[1],
                        "their_listing_id": row[2],
                        "our_agent_id": row[3],
                        "their_agent_id": row[4],
                        "status": row[5],
                    }
                return None
            finally:
                conn.close()
        return await asyncio.to_thread(_check)

    async def get_active_negotiations_for_listing(
        self, *, listing_id: str
    ) -> list[dict[str, Any]]:
        """Get all active negotiations involving an order (as our_listing_id or their_listing_id)."""
        def _load() -> list[dict[str, Any]]:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT negotiation_id, our_listing_id, their_listing_id, our_agent_id, their_agent_id, status
                    FROM negotiation_threads
                    WHERE (our_listing_id = ? OR their_listing_id = ?) AND status = 'active'
                    """,
                    (listing_id, listing_id),
                )
                rows = cur.fetchall()
                result = []
                for row in rows:
                    result.append({
                        "negotiation_id": row[0],
                        "our_listing_id": row[1],
                        "their_listing_id": row[2],
                        "our_agent_id": row[3],
                        "their_agent_id": row[4],
                        "status": row[5],
                    })
                return result
            finally:
                conn.close()
        return await asyncio.to_thread(_load)

    async def cancel_negotiations_for_listing(
        self, *, listing_id: str, except_negotiation_id: str | None = None
    ) -> list[dict]:
        """Cancel all active negotiations for an order, except the specified one.

        Returns:
            List of dicts with keys: negotiation_id, our_listing_id, their_listing_id,
            our_agent_id, their_agent_id — one entry per canceled negotiation.
        """
        def _cancel() -> list[dict]:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()

                # Find all active negotiations involving this order
                cur.execute(
                    """
                    SELECT negotiation_id, our_listing_id, their_listing_id,
                           our_agent_id, their_agent_id
                    FROM negotiation_threads
                    WHERE (our_listing_id = ? OR their_listing_id = ?)
                      AND (status = 'active')
                      AND negotiation_id != COALESCE(?, '')
                    """,
                    (listing_id, listing_id, except_negotiation_id or '')
                )

                rows = cur.fetchall()
                canceled = []
                for row in rows:
                    neg_id, our_oid, their_oid, our_aid, their_aid = row
                    cur.execute(
                        """
                        UPDATE negotiation_threads
                        SET status = 'superseded',
                            terminal_state = 'superseded',
                            updated_at = ?
                        WHERE negotiation_id = ?
                        """,
                        (datetime.now().isoformat(), neg_id)
                    )
                    canceled.append({
                        "negotiation_id": neg_id,
                        "our_listing_id": our_oid,
                        "their_listing_id": their_oid,
                        "our_agent_id": our_aid,
                        "their_agent_id": their_aid,
                    })

                conn.commit()
                return canceled
            finally:
                conn.close()

        return await asyncio.to_thread(_cancel)


    async def store_credential(
        self,
        *,
        listing_id: str,
        role: str,
        granted_to: str,
        password: str | None = None,
        ssh_commands: str | None = None,
        ssh_key_path_host: str | None = None,
        key_type: str | None = None,
    ) -> None:
        """Persist an off-chain credential. INSERT OR IGNORE (idempotent)."""
        def _save() -> None:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT OR IGNORE INTO credentials(
                      id, listing_id, role, granted_to, password,
                      ssh_commands, ssh_key_path_host, key_type, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        listing_id,
                        role,
                        granted_to,
                        password,
                        ssh_commands,
                        ssh_key_path_host,
                        key_type,
                        datetime.now().isoformat(),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

        await asyncio.to_thread(_save)

    async def get_credentials(
        self,
        *,
        listing_id: str,
        granted_to: str,
    ) -> list[dict[str, Any]]:
        """Return credential rows for a given order visible to granted_to."""
        def _load() -> list[dict[str, Any]]:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT id, listing_id, role, granted_to, password,
                           ssh_commands, ssh_key_path_host, key_type, created_at
                    FROM credentials
                    WHERE listing_id = ? AND granted_to = ?
                    ORDER BY created_at ASC
                    """,
                    (listing_id, granted_to),
                )
                rows = cur.fetchall()
                return [
                    {
                        "id": r[0],
                        "listing_id": r[1],
                        "role": r[2],
                        "granted_to": r[3],
                        "password": r[4],
                        "ssh_commands": r[5],
                        "ssh_key_path_host": r[6],
                        "key_type": r[7],
                        "created_at": r[8],
                    }
                    for r in rows
                ]
            finally:
                conn.close()

        return await asyncio.to_thread(_load)

    async def get_listing_id_by_escrow_uid(self, *, escrow_uid: str) -> str | None:
        """Return the listing_id for the given escrow_uid, or None if not found.

        Joins escrows → negotiation_threads to recover the seller's listing
        from the escrow row (escrows.escrow_uid is the on-chain PK).
        """
        def _load() -> str | None:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT nt.our_listing_id
                    FROM escrows e
                    JOIN negotiation_threads nt
                      ON nt.negotiation_id = e.negotiation_id
                    WHERE e.escrow_uid = ?
                    LIMIT 1
                    """,
                    (escrow_uid,),
                )
                row = cur.fetchone()
                return row[0] if row else None
            finally:
                conn.close()

        return await asyncio.to_thread(_load)


    # ------------------------------------------------------------------
    # Orders API helpers
    # ------------------------------------------------------------------

    async def list_listings(
        self,
        *,
        status: str | None = None,
        paused: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Return a paginated list of orders with optional filters."""
        def _list() -> list[dict[str, Any]]:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                clauses: list[str] = []
                params: list[Any] = []
                if status is not None:
                    clauses.append("status = ?")
                    params.append(status)
                if paused is not None:
                    clauses.append("paused = ?")
                    params.append(1 if paused else 0)
                where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
                cur.execute(
                    f"""
                    SELECT listing_id, status, created_at, updated_at,
                           offer_resource, fulfillment_resource,
                           max_duration_seconds, seller, oracle_address,
                           COALESCE(paused, 0) AS paused,
                           accepted_escrows
                    FROM listings {where}
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (*params, limit, offset),
                )
                keys = [
                    "listing_id", "status", "created_at", "updated_at",
                    "offer_resource", "fulfillment_resource",
                    "max_duration_seconds", "seller", "oracle_address",
                    "paused", "accepted_escrows",
                ]
                rows = cur.fetchall()
                result = []
                for row in rows:
                    d = dict(zip(keys, row))
                    d["paused"] = bool(d["paused"])
                    d["accepted_escrows"] = self._deserialize_accepted_escrows(
                        d.get("accepted_escrows"),
                    )
                    result.append(d)
                return result
            finally:
                conn.close()

        return await asyncio.to_thread(_list)

    async def set_listing_paused(self, *, listing_id: str, paused: bool) -> None:
        """Set the paused flag on a local order."""
        def _update() -> None:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    "UPDATE listings SET paused = ?, updated_at = ? WHERE listing_id = ?",
                    (1 if paused else 0, datetime.now().isoformat(), listing_id),
                )
                conn.commit()
            finally:
                conn.close()

        await asyncio.to_thread(_update)

    async def is_listing_paused(self, *, listing_id: str) -> bool:
        """Return True if the order exists and has paused=1."""
        def _check() -> bool:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT COALESCE(paused, 0) FROM listings WHERE listing_id = ? LIMIT 1",
                    (listing_id,),
                )
                row = cur.fetchone()
                return bool(row[0]) if row else False
            finally:
                conn.close()

        return await asyncio.to_thread(_check)

    # ------------------------------------------------------------------
    # Negotiations API helpers
    # ------------------------------------------------------------------

    async def list_negotiations_for_listing(
        self,
        *,
        listing_id: str,
        terminal_state: str | None = None,
        buyer_address: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List negotiation threads for a given seller order."""
        def _list() -> list[dict[str, Any]]:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                clauses: list[str] = ["our_listing_id = ?"]
                params: list[Any] = [listing_id]
                if terminal_state is not None:
                    clauses.append("terminal_state = ?")
                    params.append(terminal_state)
                if buyer_address is not None:
                    # their_agent_id holds the buyer's address or URL
                    clauses.append("their_agent_id LIKE ?")
                    params.append(f"%{buyer_address}%")
                where = "WHERE " + " AND ".join(clauses)
                cur.execute(
                    f"""
                    SELECT negotiation_id, our_listing_id, their_agent_id,
                           status, terminal_state,
                           requested_duration_seconds,
                           agreed_price, agreed_duration_seconds,
                           agreed_at, created_at, updated_at
                    FROM negotiation_threads
                    {where}
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (*params, limit, offset),
                )
                keys = [
                    "negotiation_id", "our_listing_id", "buyer_address",
                    "status", "terminal_state",
                    "requested_duration_seconds",
                    # Column stays ``agreed_price``; wire field is
                    # ``agreed_amount`` (absolute amount in base units).
                    "agreed_amount", "agreed_duration_seconds",
                    "agreed_at", "created_at", "updated_at",
                ]
                return [dict(zip(keys, row)) for row in cur.fetchall()]
            finally:
                conn.close()

        return await asyncio.to_thread(_list)

    async def load_negotiation_detail(
        self,
        *,
        listing_id: str,
        neg_id: str,
    ) -> dict[str, Any] | None:
        """Return full negotiation detail: thread + messages + stage events.

        Returns None if the negotiation doesn't exist or doesn't belong to
        the given listing_id.
        """
        def _load() -> dict[str, Any] | None:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()

                # Thread row
                cur.execute(
                    """
                    SELECT negotiation_id, our_listing_id, their_listing_id,
                           our_agent_id, their_agent_id, status, terminal_state,
                           requested_duration_seconds,
                           agreed_price, agreed_duration_seconds, agreed_at,
                           created_at, updated_at
                    FROM negotiation_threads
                    WHERE negotiation_id = ? AND our_listing_id = ?
                    """,
                    (neg_id, listing_id),
                )
                thread_row = cur.fetchone()
                if not thread_row:
                    return None

                thread_keys = [
                    "negotiation_id", "our_listing_id", "their_listing_id",
                    "our_agent_id", "their_agent_id", "status", "terminal_state",
                    "requested_duration_seconds",
                    # Column is named ``agreed_price`` (kept from before the
                    # per-hour → absolute refactor); the wire field is
                    # ``agreed_amount`` since it holds an absolute amount.
                    "agreed_amount", "agreed_duration_seconds", "agreed_at",
                    "created_at", "updated_at",
                ]
                thread = dict(zip(thread_keys, thread_row))

                # Message log
                cur.execute(
                    """
                    SELECT round, sender, our_price, their_price, proposed_price,
                           action_taken, message_type, timestamp
                    FROM negotiation_messages
                    WHERE negotiation_id = ?
                    ORDER BY round ASC
                    """,
                    (neg_id,),
                )
                msg_keys = [
                    "round", "sender", "our_price", "their_price", "proposed_price",
                    "action_taken", "message_type", "timestamp",
                ]
                messages = [dict(zip(msg_keys, row)) for row in cur.fetchall()]

                # Related stage events
                cur.execute(
                    """
                    SELECT ts, stage, event, data
                    FROM stage_events
                    WHERE negotiation_id = ?
                    ORDER BY ts ASC
                    """,
                    (neg_id,),
                )
                import json as _json
                stage_events = []
                for ts, stage, event, data_str in cur.fetchall():
                    try:
                        data = _json.loads(data_str) if data_str else {}
                    except Exception:
                        data = {"raw": data_str}
                    stage_events.append({
                        "ts": ts, "stage": stage, "event": event, "data": data,
                    })

                # Per-deal escrows (primary first, then by creation order)
                cur.execute(
                    """
                    SELECT escrow_uid, fulfillment_uid, chain_name,
                           escrow_address, is_primary, status
                    FROM escrows
                    WHERE negotiation_id = ?
                    ORDER BY is_primary DESC, created_at ASC
                    """,
                    (neg_id,),
                )
                escrows = [
                    {
                        "escrow_uid": row[0],
                        "fulfillment_uid": row[1],
                        "chain_name": row[2],
                        "escrow_address": row[3],
                        "is_primary": bool(row[4]),
                        "status": row[5],
                    }
                    for row in cur.fetchall()
                ]

                return {
                    **thread,
                    "messages": messages,
                    "stage_events": stage_events,
                    "escrows": escrows,
                    "round_count": len(messages),
                }
            finally:
                conn.close()

        return await asyncio.to_thread(_load)

    # ------------------------------------------------------------------
    # Stage events
    # ------------------------------------------------------------------

    async def list_stage_events(
        self,
        *,
        after_id: int = 0,
        limit: int = 100,
        stage: str | None = None,
        listing_id: str | None = None,
        negotiation_id: str | None = None,
    ) -> list[dict]:
        """Query stage_events rows with optional filters.

        Parameters
        ----------
        after_id:
            Return only rows with id > after_id (for SSE cursor-based tailing).
        limit:
            Maximum rows to return (capped at 500).
        stage:
            Filter by stage column (e.g. 'discovery', 'negotiation').
        listing_id:
            Filter by listing_id column.
        negotiation_id:
            Filter by negotiation_id column.
        """
        import json as _json

        limit = min(limit, 500)

        def _query() -> list[dict]:
            conn = sqlite3.connect(self.db_path, timeout=2)
            try:
                conditions = ["id > ?"]
                params: list = [after_id]
                if stage is not None:
                    conditions.append("stage = ?")
                    params.append(stage)
                if listing_id is not None:
                    conditions.append("listing_id = ?")
                    params.append(listing_id)
                if negotiation_id is not None:
                    conditions.append("negotiation_id = ?")
                    params.append(negotiation_id)
                where = " AND ".join(conditions)
                params.append(limit)
                cur = conn.execute(
                    f"SELECT id, ts, stage, event, negotiation_id, listing_id, escrow_uid, data "
                    f"FROM stage_events WHERE {where} ORDER BY id ASC LIMIT ?",
                    params,
                )
                rows = []
                for row in cur.fetchall():
                    row_id, ts, stg, evt, neg_id, lst_id, escrow, data_str = row
                    try:
                        data = _json.loads(data_str) if data_str else {}
                    except Exception:
                        data = {"raw": data_str}
                    rows.append({
                        "id": row_id,
                        "ts": ts,
                        "stage": stg,
                        "event": evt,
                        "negotiation_id": neg_id,
                        "listing_id": lst_id,
                        "escrow_uid": escrow,
                        "data": data,
                    })
                return rows
            finally:
                conn.close()

        return await asyncio.to_thread(_query)

_sqlite_client: SQLiteClient | None = None


def get_sqlite_client() -> SQLiteClient:
    global _sqlite_client
    if _sqlite_client is None:
        _sqlite_client = SQLiteClient(db_path=settings.db_path)
    return _sqlite_client
