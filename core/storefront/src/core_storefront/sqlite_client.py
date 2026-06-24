"""Market-state SQLite persistence shared by storefront composition roots.

Owns the domain-neutral tables — listings, negotiation threads/messages,
escrows, settlement claims, publications, credentials, heartbeats,
capacity holds, stage events — plus the legacy renames and versioned
migrations that keep persisted databases upgradable across image
versions. Domain storefronts subclass :class:`SQLiteClient` to add their
inventory tables and migrations (``_ensure_domain_tables`` /
``_ensure_domain_indexes`` / ``_domain_migrations``); the settings-bound
singleton factory stays with each composition root.

Hoisted from ``market_storefront.utils.sqlite_client`` when the
API-tokens domain became the second composition root. A few VM-era
column names (e.g. ``ssh_commands`` on credentials) ride along until a
future cross-root consolidation pass.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import time
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from .sqlite_migrations import Migration, apply_schema_migrations

logger = logging.getLogger(__name__)


def _amount_to_db_text(value: Any) -> str | None:
    """Serialize a raw token amount for SQLite without int64 overflow.

    Negotiation amounts are EVM ``uint256`` values. SQLite INTEGER cannot
    represent many normal 18-decimal token amounts, so amount-bearing columns
    store decimal-digit text and callers get Python ints back on read.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("raw token amounts must be numeric, not boolean")
    if isinstance(value, int):
        if value < 0:
            raise ValueError("raw token amounts must be non-negative")
        return str(value)

    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"raw token amount {value!r} is not numeric") from exc
    if parsed < 0:
        raise ValueError("raw token amounts must be non-negative")
    integral = parsed.to_integral_value()
    if parsed != integral:
        raise ValueError(f"raw token amount {value!r} is not an integer")
    return str(int(integral))


def _amount_from_db_text(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    integral = parsed.to_integral_value()
    if parsed != integral:
        return None
    amount = int(integral)
    return amount if amount >= 0 else None


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
                  requested_start_utc TEXT,
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
                  agreed_price TEXT,
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
                cur.execute("ALTER TABLE negotiation_threads ADD COLUMN agreed_price TEXT")
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
                cur.execute("ALTER TABLE negotiation_threads ADD COLUMN requested_start_utc TEXT")
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
                  our_initial_price TEXT,
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
                  our_price TEXT,
                  their_price TEXT,
                  proposed_price TEXT,
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
            # literal_fields, rates} — the canonical pricing+escrow
            # advertisement. The legacy ``demand_resource`` and per-deal
            # ``escrow_uid``/``buyer``/``matched_offer_id``/
            # ``seller_attestation``/``buyer_attestation`` columns are
            # backfilled+dropped by the versioned escrow/listing migration.
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
                  accepted_escrows TEXT,
                  demands TEXT
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
            try:
                cur.execute("ALTER TABLE listings ADD COLUMN demands TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists
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
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS capacity_holds (
                  negotiation_id TEXT PRIMARY KEY,
                  listing_id TEXT,
                  allocation_id TEXT NOT NULL,
                  payload TEXT,
                  expires_at TEXT,
                  created_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'))
                )
                """
            )
            # Domain-owned inventory tables (hook). Created before the
            # versioned migrations run so those can reference them.
            self._ensure_domain_tables(cur)
            apply_schema_migrations(
                conn, extra_migrations=self._domain_migrations(),
            )
            # Domain-owned indexes (hook) — after migrations, which may
            # add the columns they cover.
            self._ensure_domain_indexes(cur)
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
            # deal, single attestation_uid column). The versioned migrations
            # rename the old table + widen columns + backfill from the
            # listings row when present.
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
            # Settlement claims — the deal-servicing engine's persisted
            # state (core_storefront.settlement_lifecycle.ClaimRecord):
            # one row per obligation the seller must drive to collection.
            # JSON columns mirror the record's dict fields verbatim.
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS settlement_claims (
                  claim_ref TEXT PRIMARY KEY,
                  state TEXT NOT NULL,
                  deal_ref TEXT,
                  obligation TEXT,
                  fulfillment_ref TEXT,
                  attempts INTEGER NOT NULL DEFAULT 0,
                  next_attempt_unix REAL,
                  mechanism_state TEXT,
                  last_error TEXT,
                  result TEXT,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_claims_state "
                "ON settlement_claims(state, next_attempt_unix)"
            )
            # Deal heartbeats — buyer-signed liveness attestations
            # persisted as evidence (core_storefront.heartbeats owns
            # validation/replay semantics).
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS deal_heartbeats (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  deal_ref TEXT NOT NULL,
                  signer TEXT,
                  sent_at_unix REAL NOT NULL,
                  payload TEXT,
                  received_at_unix REAL NOT NULL
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_heartbeats_deal "
                "ON deal_heartbeats(deal_ref, sent_at_unix)"
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
        (``{chain_name, escrow_address, literal_fields, rates}``).
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

    # ------------------------------------------------------------------
    # Domain hooks — storefront composition roots override these to add
    # their inventory tables beside the core market state.
    # ------------------------------------------------------------------

    def _ensure_domain_tables(self, cur: sqlite3.Cursor) -> None:
        """Create domain-owned tables. Runs before schema migrations."""

    def _ensure_domain_indexes(self, cur: sqlite3.Cursor) -> None:
        """Create domain-owned indexes. Runs after schema migrations."""

    def _domain_migrations(self) -> tuple[Migration, ...]:
        """Domain-owned versioned migrations, appended to the core set."""
        return ()

    async def save_capacity_hold(
        self,
        *,
        negotiation_id: str,
        listing_id: str | None,
        allocation_id: str,
        payload: dict[str, Any] | None = None,
        expires_at: str | None = None,
    ) -> None:
        def _save() -> None:
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute(
                    """
                    INSERT INTO capacity_holds(
                      negotiation_id, listing_id, allocation_id, payload, expires_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(negotiation_id) DO UPDATE SET
                      listing_id=excluded.listing_id,
                      allocation_id=excluded.allocation_id,
                      payload=excluded.payload,
                      expires_at=excluded.expires_at
                    """,
                    (
                        negotiation_id,
                        listing_id,
                        allocation_id,
                        json.dumps(payload) if payload is not None else None,
                        expires_at,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

        return await asyncio.to_thread(_save)

    async def load_capacity_hold(
        self, *, negotiation_id: str,
    ) -> dict[str, Any] | None:
        def _load() -> dict[str, Any] | None:
            conn = sqlite3.connect(self.db_path)
            try:
                row = conn.execute(
                    """
                    SELECT negotiation_id, listing_id, allocation_id, payload, expires_at
                    FROM capacity_holds
                    WHERE negotiation_id = ?
                    """,
                    (negotiation_id,),
                ).fetchone()
            finally:
                conn.close()
            if row is None:
                return None
            try:
                payload = json.loads(row[3]) if row[3] else {}
            except (ValueError, TypeError):
                payload = {}
            return {
                "negotiation_id": row[0],
                "listing_id": row[1],
                "allocation_id": row[2],
                "payload": payload,
                "expires_at": row[4],
            }

        return await asyncio.to_thread(_load)

    async def delete_capacity_hold(self, *, negotiation_id: str) -> None:
        def _delete() -> None:
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute(
                    "DELETE FROM capacity_holds WHERE negotiation_id = ?",
                    (negotiation_id,),
                )
                conn.commit()
            finally:
                conn.close()

        return await asyncio.to_thread(_delete)

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
        demands: Any | None = None,
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
                      accepted_escrows,
                      demands
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(listing_id) DO UPDATE SET
                      status=excluded.status,
                      updated_at=excluded.updated_at,
                      offer_resource=excluded.offer_resource,
                      fulfillment_resource=excluded.fulfillment_resource,
                      max_duration_seconds=excluded.max_duration_seconds,
                      seller=excluded.seller,
                      oracle_address=excluded.oracle_address,
                      paused=excluded.paused,
                      accepted_escrows=excluded.accepted_escrows,
                      demands=excluded.demands
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
                        self._serialize_resource(demands),
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
                           accepted_escrows,
                           demands
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
                    "paused", "accepted_escrows", "demands",
                ]
                d = dict(zip(keys, row))
                d["paused"] = bool(d["paused"])
                d["accepted_escrows"] = self._deserialize_accepted_escrows(
                    d.get("accepted_escrows"),
                )
                d["demands"] = self._deserialize_accepted_escrows(
                    d.get("demands"),
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
        our_price: int | str | float | None,
        their_price: int | str | float | None,
        proposed_price: int | str | float | None,
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
                our_price_text = _amount_to_db_text(our_price)
                their_price_text = _amount_to_db_text(their_price)
                proposed_price_text = _amount_to_db_text(proposed_price)
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
                        negotiation_id, actual_round, sender, our_price_text,
                        their_price_text, proposed_price_text, action_taken,
                        message_type, timestamp
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
                        "our_price": _amount_from_db_text(row[2]),
                        "their_price": _amount_from_db_text(row[3]),
                        "proposed_price": _amount_from_db_text(row[4]),
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
        agreed_price: int | str | float,
        agreed_duration_seconds: int,
        agreed_start_utc: str | None = None,
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
                agreed_price_text = _amount_to_db_text(agreed_price)
                cur.execute(
                    """
                    UPDATE negotiation_threads
                    SET agreed_price = ?,
                        agreed_duration_seconds = ?,
                        requested_start_utc = COALESCE(requested_start_utc, ?),
                        agreed_at = ?,
                        updated_at = ?
                    WHERE negotiation_id = ?
                    """,
                    (
                        agreed_price_text,
                        int(agreed_duration_seconds),
                        agreed_start_utc,
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
        caller (settlement) re-types it via market_core.schemas.EscrowProposal.
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
                           requested_start_utc,
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
                    "requested_start_utc",
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
                result["agreed_price"] = _amount_from_db_text(result.get("agreed_price"))
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

    # ------------------------------------------------------------------
    # Deal heartbeats (core_storefront.heartbeats store)
    # ------------------------------------------------------------------

    async def latest_heartbeat(self, deal_ref: str) -> dict | None:
        def _load() -> dict | None:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.execute(
                    """
                    SELECT deal_ref, signer, sent_at_unix, payload, received_at_unix
                    FROM deal_heartbeats WHERE deal_ref = ?
                    ORDER BY sent_at_unix DESC LIMIT 1
                    """,
                    (deal_ref,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return {
                    "deal_ref": row[0],
                    "signer": row[1],
                    "sent_at_unix": row[2],
                    "payload": json.loads(row[3]) if row[3] else {},
                    "received_at_unix": row[4],
                }
            finally:
                conn.close()

        return await asyncio.to_thread(_load)

    async def insert_heartbeat(self, record: dict) -> None:
        def _insert() -> None:
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute(
                    """
                    INSERT INTO deal_heartbeats
                      (deal_ref, signer, sent_at_unix, payload, received_at_unix)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        record["deal_ref"],
                        record.get("signer"),
                        float(record["sent_at_unix"]),
                        json.dumps(record.get("payload") or {}),
                        float(record["received_at_unix"]),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

        await asyncio.to_thread(_insert)

    async def count_heartbeats(self, deal_ref: str) -> int:
        def _count() -> int:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.execute(
                    "SELECT COUNT(*) FROM deal_heartbeats WHERE deal_ref = ?",
                    (deal_ref,),
                )
                return int(cur.fetchone()[0])
            finally:
                conn.close()

        return await asyncio.to_thread(_count)

    # ------------------------------------------------------------------
    # Settlement claims (deal-servicing engine store)
    # ------------------------------------------------------------------

    _CLAIM_JSON_FIELDS = ("deal_ref", "obligation", "mechanism_state", "result")

    def _claim_row_to_dict(self, row: tuple, columns: list[str]) -> dict:
        out = dict(zip(columns, row))
        for f in self._CLAIM_JSON_FIELDS:
            raw = out.get(f)
            out[f] = json.loads(raw) if raw else ({} if f != "result" else None)
        out.pop("created_at", None)
        out.pop("updated_at", None)
        return out

    async def due_claims(self, now_unix: float, limit: int = 50) -> list[dict]:
        """Non-terminal claims whose next attempt is unset or due."""
        def _load() -> list[dict]:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.execute(
                    """
                    SELECT claim_ref, state, deal_ref, obligation,
                           fulfillment_ref, attempts, next_attempt_unix,
                           mechanism_state, last_error, result,
                           created_at, updated_at
                    FROM settlement_claims
                    WHERE state NOT IN ('collected', 'abandoned')
                      AND (next_attempt_unix IS NULL OR next_attempt_unix <= ?)
                    ORDER BY created_at
                    LIMIT ?
                    """,
                    (now_unix, limit),
                )
                columns = [d[0] for d in cur.description]
                return [self._claim_row_to_dict(r, columns) for r in cur.fetchall()]
            finally:
                conn.close()

        return await asyncio.to_thread(_load)

    async def upsert_claim(self, claim: dict) -> None:
        """Insert the claim if new; no-op when claim_ref already exists."""
        def _insert() -> None:
            now = datetime.now().isoformat()
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO settlement_claims
                      (claim_ref, state, deal_ref, obligation, fulfillment_ref,
                       attempts, next_attempt_unix, mechanism_state,
                       last_error, result, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        claim["claim_ref"],
                        claim.get("state") or "awaiting_conditions",
                        json.dumps(claim.get("deal_ref") or {}),
                        json.dumps(claim.get("obligation") or {}),
                        claim.get("fulfillment_ref"),
                        int(claim.get("attempts") or 0),
                        claim.get("next_attempt_unix"),
                        json.dumps(claim.get("mechanism_state") or {}),
                        claim.get("last_error"),
                        json.dumps(claim["result"]) if claim.get("result") is not None else None,
                        now, now,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

        await asyncio.to_thread(_insert)

    async def save_claim(self, claim: dict) -> None:
        """Persist the full updated claim row."""
        def _save() -> None:
            now = datetime.now().isoformat()
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute(
                    """
                    UPDATE settlement_claims
                    SET state = ?, deal_ref = ?, obligation = ?,
                        fulfillment_ref = ?, attempts = ?,
                        next_attempt_unix = ?, mechanism_state = ?,
                        last_error = ?, result = ?, updated_at = ?
                    WHERE claim_ref = ?
                    """,
                    (
                        claim["state"],
                        json.dumps(claim.get("deal_ref") or {}),
                        json.dumps(claim.get("obligation") or {}),
                        claim.get("fulfillment_ref"),
                        int(claim.get("attempts") or 0),
                        claim.get("next_attempt_unix"),
                        json.dumps(claim.get("mechanism_state") or {}),
                        claim.get("last_error"),
                        json.dumps(claim["result"]) if claim.get("result") is not None else None,
                        now,
                        claim["claim_ref"],
                    ),
                )
                conn.commit()
            finally:
                conn.close()

        await asyncio.to_thread(_save)

    async def load_claim(self, claim_ref: str) -> dict | None:
        """Load one claim row (None when absent)."""
        def _load() -> dict | None:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.execute(
                    """
                    SELECT claim_ref, state, deal_ref, obligation,
                           fulfillment_ref, attempts, next_attempt_unix,
                           mechanism_state, last_error, result,
                           created_at, updated_at
                    FROM settlement_claims WHERE claim_ref = ?
                    """,
                    (claim_ref,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                columns = [d[0] for d in cur.description]
                return self._claim_row_to_dict(row, columns)
            finally:
                conn.close()

        return await asyncio.to_thread(_load)

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
        our_initial_price: int | str | float | None = None,
        our_strategy: str | None = None,
        requested_duration_seconds: int | None = None,
        requested_start_utc: str | None = None,
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
            requested_start_utc: Buyer's requested lease start. None means now.
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
                our_initial_price_text = _amount_to_db_text(our_initial_price)

                # Insert public thread info (ignore if exists, it's shared)
                cur.execute(
                    """
                    INSERT OR IGNORE INTO negotiation_threads(
                        negotiation_id, our_listing_id, their_listing_id,
                        our_agent_id, their_agent_id, status,
                        requested_duration_seconds,
                        requested_start_utc,
                        buyer_escrow_proposal,
                        created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        negotiation_id, our_listing_id, their_listing_id,
                        our_agent_id, their_agent_id, status,
                        requested_duration_seconds,
                        requested_start_utc,
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
                    (
                        negotiation_id, owner_id, our_initial_price_text,
                        our_strategy,
                    ),
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
                        "our_initial_price": _amount_from_db_text(row[6]),
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
                           accepted_escrows,
                           demands
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
                    "paused", "accepted_escrows", "demands",
                ]
                rows = cur.fetchall()
                result = []
                for row in rows:
                    d = dict(zip(keys, row))
                    d["paused"] = bool(d["paused"])
                    d["accepted_escrows"] = self._deserialize_accepted_escrows(
                        d.get("accepted_escrows"),
                    )
                    d["demands"] = self._deserialize_accepted_escrows(
                        d.get("demands"),
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
                           requested_start_utc,
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
                    "requested_start_utc",
                    # Column stays ``agreed_price``; wire field is
                    # ``agreed_amount`` (absolute amount in base units).
                    "agreed_amount", "agreed_duration_seconds",
                    "agreed_at", "created_at", "updated_at",
                ]
                result = [dict(zip(keys, row)) for row in cur.fetchall()]
                for item in result:
                    item["agreed_amount"] = _amount_from_db_text(
                        item.get("agreed_amount"),
                    )
                return result
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
                           requested_start_utc,
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
                    "requested_start_utc",
                    # Column is named ``agreed_price`` (kept from before the
                    # per-hour → absolute refactor); the wire field is
                    # ``agreed_amount`` since it holds an absolute amount.
                    "agreed_amount", "agreed_duration_seconds", "agreed_at",
                    "created_at", "updated_at",
                ]
                thread = dict(zip(thread_keys, thread_row))
                thread["agreed_amount"] = _amount_from_db_text(
                    thread.get("agreed_amount"),
                )

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
                for message in messages:
                    message["our_price"] = _amount_from_db_text(
                        message.get("our_price"),
                    )
                    message["their_price"] = _amount_from_db_text(
                        message.get("their_price"),
                    )
                    message["proposed_price"] = _amount_from_db_text(
                        message.get("proposed_price"),
                    )

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
