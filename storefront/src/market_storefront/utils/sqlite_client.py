from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import uuid
from datetime import datetime
from typing import Any

from .config import CONFIG
from .resource_csv_importer import upsert_resources_from_csv

logger = logging.getLogger(__name__)


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
                for old_idx in (
                    "idx_credentials_order_id",
                    "idx_credentials_order_granted",
                ):
                    try:
                        cur.execute(f"DROP INDEX IF EXISTS {old_idx}")
                    except sqlite3.OperationalError:
                        pass

            # Policies table (callable-only)
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS policies (
                  agent_id TEXT NOT NULL,
                  name TEXT NOT NULL,
                  trigger_type TEXT NOT NULL,
                  callable_ref TEXT,
                  PRIMARY KEY(agent_id, name)
                )
                """
            )
            # Policy composites (ordered components per policy)
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS policy_composites (
                  agent_id TEXT NOT NULL,
                  policy_name TEXT NOT NULL,
                  position INTEGER NOT NULL,
                  component_name TEXT NOT NULL,
                  PRIMARY KEY(agent_id, policy_name, position),
                  FOREIGN KEY(agent_id, policy_name) REFERENCES policies(agent_id, name)
                )
                """
            )
            # Decisions table
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS decisions (
                  decision_id TEXT PRIMARY KEY,
                  event_id TEXT NOT NULL,
                  event_type TEXT NOT NULL,
                  agent_id TEXT NOT NULL,
                  policy_used TEXT,
                  action_type TEXT NOT NULL,
                  timestamp TEXT NOT NULL,
                  context_json TEXT
                )
                """
            )
            # Decision outcomes table
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS decision_outcomes (
                  decision_id TEXT PRIMARY KEY,
                  outcome_json TEXT,
                  timestamp TEXT NOT NULL,
                  FOREIGN KEY(decision_id) REFERENCES decisions(decision_id)
                )
                """
            )
            # Negotiation threads table
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
                  -- Committed agreement artifact: populated when terminal_state='success'.
                  -- Captures the negotiation's output as queryable state so settlement
                  -- can run (or be retried) as a separate step without replaying rounds.
                  agreed_price INTEGER,
                  agreed_duration_seconds INTEGER,
                  agreed_at TEXT
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
            # Listings table (local source of truth).
            # Duration is buyer-driven (Slice C): the seller advertises an
            # OPTIONAL ceiling (max_duration_seconds; NULL = unlimited).
            # demand.amount is per-hour; total payment at agreement time
            # is amount × agreed_duration_seconds / 3600.
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS listings (
                  listing_id TEXT PRIMARY KEY,
                  status TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  offer_resource TEXT NOT NULL,
                  demand_resource TEXT NOT NULL,
                  fulfillment_resource TEXT,
                  max_duration_seconds INTEGER,
                  seller TEXT NOT NULL,
                  buyer TEXT,
                  matched_offer_id TEXT,
                  seller_attestation TEXT,
                  buyer_attestation TEXT,
                  escrow_uid TEXT,
                  oracle_address TEXT,
                  paused INTEGER NOT NULL DEFAULT 0
                )
                """
            )
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
            # Create indexes
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_decisions_event_id ON decisions(event_id)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_decisions_event_type ON decisions(event_type)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_decisions_timestamp ON decisions(timestamp)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_decisions_agent_id ON decisions(agent_id)"
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
            # Settlement jobs — per-escrow provisioning status row. The
            # buyer creates an escrow on-chain then posts escrow_uid to
            # the seller's /settle/{uid} endpoint; that inserts a row
            # here with status='provisioning' and kicks off the async
            # provisioning task. When done, the task updates this row
            # with status='ready' (+ attestation/connection) or 'failed'
            # (+ reason). Buyer polls /settle/{uid}/status which reads
            # this row.
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS settlement_jobs (
                  escrow_uid TEXT PRIMARY KEY,
                  negotiation_id TEXT NOT NULL,
                  status TEXT NOT NULL,
                  attestation_uid TEXT,
                  connection_details TEXT,
                  tenant_credentials TEXT,
                  reason TEXT,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_settlement_jobs_status ON settlement_jobs(status)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_settlement_jobs_negotiation ON settlement_jobs(negotiation_id)"
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
        """Create or update a generic resource snapshot row."""
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
        """Import resources from CSV and upsert rows into the resources table."""
        report = await upsert_resources_from_csv(
            csv_path=csv_path,
            sqlite_client=self,
            dry_run=dry_run,
        )
        return report.to_dict()

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

    async def upsert_listing(
        self,
        *,
        listing_id: str,
        status: str,
        created_at: str,
        updated_at: str,
        offer_resource: Any,
        demand_resource: Any,
        fulfillment_resource: Any | None,
        max_duration_seconds: int | None,
        seller: str,
        buyer: str | None = None,
        matched_offer_id: str | None = None,
        seller_attestation: str | None = None,
        buyer_attestation: str | None = None,
        escrow_uid: str | None = None,
        oracle_address: str | None = None,
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
                      demand_resource,
                      fulfillment_resource,
                      max_duration_seconds,
                      seller,
                      buyer,
                      matched_offer_id,
                      seller_attestation,
                      buyer_attestation,
                      escrow_uid,
                      oracle_address
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(listing_id) DO UPDATE SET
                      status=excluded.status,
                      updated_at=excluded.updated_at,
                      offer_resource=excluded.offer_resource,
                      demand_resource=excluded.demand_resource,
                      fulfillment_resource=excluded.fulfillment_resource,
                      max_duration_seconds=excluded.max_duration_seconds,
                      seller=excluded.seller,
                      buyer=excluded.buyer,
                      matched_offer_id=excluded.matched_offer_id,
                      seller_attestation=excluded.seller_attestation,
                      buyer_attestation=excluded.buyer_attestation,
                      escrow_uid=excluded.escrow_uid,
                      oracle_address=excluded.oracle_address
                    """,
                    (
                        listing_id,
                        status,
                        created_at,
                        updated_at,
                        self._serialize_resource(offer_resource),
                        self._serialize_resource(demand_resource),
                        self._serialize_resource(fulfillment_resource),
                        max_duration_seconds,
                        seller,
                        buyer,
                        matched_offer_id,
                        seller_attestation,
                        buyer_attestation,
                        escrow_uid,
                        oracle_address,
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
        demand_resource: Any | None = None,
        fulfillment_resource: Any | None = None,
        max_duration_seconds: int | None = None,
        seller: str | None = None,
        buyer: str | None = None,
        matched_offer_id: str | None = None,
        seller_attestation: str | None = None,
        buyer_attestation: str | None = None,
        escrow_uid: str | None = None,
        oracle_address: str | None = None,
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
            add("demand_resource", demand_resource, serialize=True)
            add("fulfillment_resource", fulfillment_resource, serialize=True)
            add("max_duration_seconds", max_duration_seconds)
            add("seller", seller)
            add("buyer", buyer)
            add("matched_offer_id", matched_offer_id)
            add("seller_attestation", seller_attestation)
            add("buyer_attestation", buyer_attestation)
            add("escrow_uid", escrow_uid)
            add("oracle_address", oracle_address)

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
                           offer_resource, demand_resource, fulfillment_resource,
                           max_duration_seconds, seller, buyer,
                           matched_offer_id, seller_attestation, buyer_attestation,
                           escrow_uid, oracle_address,
                           COALESCE(paused, 0) AS paused
                    FROM listings WHERE listing_id = ?
                    """,
                    (listing_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                keys = [
                    "listing_id", "status", "created_at", "updated_at",
                    "offer_resource", "demand_resource", "fulfillment_resource",
                    "max_duration_seconds", "seller", "buyer",
                    "matched_offer_id", "seller_attestation", "buyer_attestation",
                    "escrow_uid", "oracle_address", "paused",
                ]
                d = dict(zip(keys, row))
                d["paused"] = bool(d["paused"])
                return d
            finally:
                conn.close()

        return await asyncio.to_thread(_load)


    async def save_policy(
        self,
        *,
        agent_id: str,
        name: str,
        trigger_type: str,
        callable_ref: str | None,
    ) -> None:
        def _save() -> None:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO policies(agent_id, name, trigger_type, callable_ref)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(agent_id, name) DO UPDATE SET
                        trigger_type=excluded.trigger_type,
                        callable_ref=excluded.callable_ref
                    """,
                    (agent_id, name, trigger_type, callable_ref),
                )
                conn.commit()
            finally:
                conn.close()

        await asyncio.to_thread(_save)

    async def load_policies_by_trigger(self, *, agent_id: str, trigger_type: str) -> list[dict[str, Any]]:
        def _load() -> list[dict[str, Any]]:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT name, callable_ref FROM policies WHERE agent_id=? AND trigger_type=?",
                    (agent_id, trigger_type),
                )
                rows = cur.fetchall()
                result: list[dict[str, Any]] = []
                for (name, callable_ref) in rows:
                    result.append(
                        {
                            "name": name,
                            "callable_ref": callable_ref,
                        }
                    )
                return result
            finally:
                conn.close()

        return await asyncio.to_thread(_load)

    async def save_policy_composite(self, *, agent_id: str, policy_name: str, components: list[str]) -> None:
        """Persist ordered component names for a composite policy."""
        def _save() -> None:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                # Clear existing components to avoid duplicates
                cur.execute(
                    "DELETE FROM policy_composites WHERE agent_id=? AND policy_name=?",
                    (agent_id, policy_name),
                )
                # Insert ordered components
                for idx, comp in enumerate(components):
                    cur.execute(
                        """
                        INSERT INTO policy_composites(agent_id, policy_name, position, component_name)
                        VALUES (?, ?, ?, ?)
                        """,
                        (agent_id, policy_name, idx, comp),
                    )
                conn.commit()
            finally:
                conn.close()

        await asyncio.to_thread(_save)

    async def load_policy_composite(self, *, agent_id: str, policy_name: str) -> list[str]:
        def _load() -> list[str]:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT component_name from policy_composites
                    WHERE agent_id=? AND policy_name=?
                    ORDER BY position ASC
                    """,
                    (agent_id, policy_name),
                )
                return [row[0] for row in cur.fetchall()]
            finally:
                conn.close()

        return await asyncio.to_thread(_load)

    async def list_seeded_policies(self) -> list[dict]:
        """Return all seeded policies joined with their ordered components.

        Used by the system controller's policy diagnostic and dry-run endpoints.
        Each row has: policy_name, trigger_type, callable_ref, components (list[str]).

        Note: policy_composites rows are keyed by callable_ref (the indirection
        pointer stored in the policies.callable_ref column), NOT by policies.name.
        """
        def _list() -> list[dict]:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT p.name, p.trigger_type, p.callable_ref,
                           GROUP_CONCAT(pc.component_name, '||') as components_concat
                    FROM policies p
                    LEFT JOIN policy_composites pc
                           ON pc.agent_id = p.agent_id
                           AND pc.policy_name = p.callable_ref
                    GROUP BY p.agent_id, p.name, p.trigger_type, p.callable_ref
                    ORDER BY p.name
                    """
                )
                rows = []
                for name, trigger_type, callable_ref, components_concat in cur.fetchall():
                    components = (
                        components_concat.split("||") if components_concat else []
                    )
                    rows.append({
                        "policy_name": name,
                        "trigger_type": trigger_type,
                        "callable_ref": callable_ref,
                        "components": components,
                    })
                return rows
            finally:
                conn.close()

        return await asyncio.to_thread(_list)

    async def save_decision(
        self,
        *,
        decision_id: str,
        event_id: str,
        event_type: str,
        agent_id: str,
        policy_used: str,
        action_type: str,
        timestamp: str,
        context_json: str | None,
    ) -> None:
        """Save a decision record."""
        def _save() -> None:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO decisions(decision_id, event_id, event_type, agent_id, policy_used, action_type, timestamp, context_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (decision_id, event_id, event_type, agent_id, policy_used, action_type, timestamp, context_json),
                )
                conn.commit()
            finally:
                conn.close()
        
        await asyncio.to_thread(_save)
    
    async def save_decision_outcome(
        self,
        *,
        decision_id: str,
        outcome_json: str | None,
        timestamp: str,
    ) -> None:
        """Save a decision outcome record."""
        def _save() -> None:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT OR REPLACE INTO decision_outcomes(decision_id, outcome_json, timestamp)
                    VALUES (?, ?, ?)
                    """,
                    (decision_id, outcome_json, timestamp),
                )
                conn.commit()
            finally:
                conn.close()
        
        await asyncio.to_thread(_save)
    
    async def load_recent_decisions(
        self,
        *,
        agent_id: str,
        limit: int = 10,
        event_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Load recent decisions for context building (without heavy context_json payloads)."""
        def _load() -> list[dict[str, Any]]:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                if event_type:
                    cur.execute(
                        """
                        SELECT decision_id, event_id, event_type, policy_used, action_type, timestamp
                        FROM decisions
                        WHERE agent_id = ? AND event_type = ?
                        ORDER BY timestamp DESC
                        LIMIT ?
                        """,
                        (agent_id, event_type, limit),
                    )
                else:
                    cur.execute(
                        """
                        SELECT decision_id, event_id, event_type, policy_used, action_type, timestamp
                        FROM decisions
                        WHERE agent_id = ?
                        ORDER BY timestamp DESC
                        LIMIT ?
                        """,
                        (agent_id, limit),
                    )
                rows = cur.fetchall()
                result = []
                for row in rows:
                    result.append({
                        "decision_id": row[0],
                        "event_id": row[1],
                        "event_type": row[2],
                        "policy_used": row[3],
                        "action_type": row[4],
                        "timestamp": row[5],
                    })
                return result
            finally:
                conn.close()
        
        return await asyncio.to_thread(_load)
    
    async def save_negotiation_message(
        self,
        *,
        negotiation_id: str,
        round: int | None = None,
        sender: str,
        our_price: int | None,
        their_price: int | None,
        proposed_price: int | None,
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
        agreed_price: int,
        agreed_duration_seconds: int,
    ) -> None:
        """Record the agreement artifact that comes out of a successful negotiation.

        Called before any settlement step touches the chain. Lets settlement
        run (or be retried) as a separate step by reading these columns,
        without replaying the round-by-round message history.

        ``agreed_duration_seconds`` echoes the buyer's negotiation-init ask;
        total payment = agreed_price (per-hour) × agreed_duration_seconds / 3600.
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
                        int(agreed_price),
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
        """Return the negotiation_threads row as a dict, or None if absent."""
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
                           agreed_price, agreed_duration_seconds, agreed_at
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
                    "agreed_price", "agreed_duration_seconds", "agreed_at",
                ]
                return dict(zip(keys, row))
            finally:
                conn.close()

        return await asyncio.to_thread(_load)

    # ------------------------------------------------------------------
    # settlement_jobs — polling-mode provisioning status per escrow.
    # ------------------------------------------------------------------

    async def insert_settlement_job(
        self,
        *,
        escrow_uid: str,
        negotiation_id: str,
        status: str = "provisioning",
    ) -> bool:
        """Create a new settlement_jobs row. Returns True if inserted,
        False if a row for this escrow already existed (idempotent)."""
        def _insert() -> bool:
            now = datetime.now().isoformat()
            conn = sqlite3.connect(self.db_path)
            try:
                try:
                    conn.execute(
                        """
                        INSERT INTO settlement_jobs
                          (escrow_uid, negotiation_id, status, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (escrow_uid, negotiation_id, status, now, now),
                    )
                    conn.commit()
                    return True
                except sqlite3.IntegrityError:
                    # PRIMARY KEY conflict — job already exists.
                    return False
            finally:
                conn.close()

        return await asyncio.to_thread(_insert)

    async def update_settlement_job(
        self,
        *,
        escrow_uid: str,
        status: str | None = None,
        attestation_uid: str | None = None,
        connection_details: str | None = None,
        tenant_credentials: str | None = None,
        reason: str | None = None,
    ) -> None:
        """Patch a settlement_jobs row. Any None field is skipped."""
        def _update() -> None:
            updates: list[str] = []
            values: list[Any] = []

            def add(col: str, val: Any) -> None:
                if val is None:
                    return
                updates.append(f"{col} = ?")
                values.append(val)

            add("status", status)
            add("attestation_uid", attestation_uid)
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
                    f"UPDATE settlement_jobs SET {', '.join(updates)} WHERE escrow_uid = ?",
                    (*values, escrow_uid),
                )
                conn.commit()
            finally:
                conn.close()

        await asyncio.to_thread(_update)

    async def load_settlement_job(
        self,
        *,
        escrow_uid: str,
    ) -> dict[str, Any] | None:
        """Return the settlement_jobs row as a dict, or None if absent."""
        def _load() -> dict[str, Any] | None:
            conn = sqlite3.connect(self.db_path)
            try:
                row = conn.execute(
                    """
                    SELECT escrow_uid, negotiation_id, status,
                           attestation_uid, connection_details, tenant_credentials,
                           reason, created_at, updated_at
                    FROM settlement_jobs WHERE escrow_uid = ?
                    """,
                    (escrow_uid,),
                ).fetchone()
                if not row:
                    return None
                keys = [
                    "escrow_uid", "negotiation_id", "status",
                    "attestation_uid", "connection_details", "tenant_credentials",
                    "reason", "created_at", "updated_at",
                ]
                return dict(zip(keys, row))
            finally:
                conn.close()

        return await asyncio.to_thread(_load)

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
        our_initial_price: int | None = None,
        our_strategy: str | None = None,
        requested_duration_seconds: int | None = None,
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
        """
        def _create() -> None:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                timestamp = datetime.now().isoformat()

                # Insert public thread info (ignore if exists, it's shared)
                cur.execute(
                    """
                    INSERT OR IGNORE INTO negotiation_threads(
                        negotiation_id, our_listing_id, their_listing_id,
                        our_agent_id, their_agent_id, status,
                        requested_duration_seconds,
                        created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        negotiation_id, our_listing_id, their_listing_id,
                        our_agent_id, their_agent_id, status,
                        requested_duration_seconds,
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
        """Return the listing_id for the given escrow_uid, or None if not found."""
        def _load() -> str | None:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT listing_id FROM listings WHERE escrow_uid = ? LIMIT 1",
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
                           offer_resource, demand_resource, fulfillment_resource,
                           max_duration_seconds, seller, buyer,
                           matched_offer_id, seller_attestation, buyer_attestation,
                           escrow_uid, oracle_address,
                           COALESCE(paused, 0) AS paused
                    FROM listings {where}
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (*params, limit, offset),
                )
                keys = [
                    "listing_id", "status", "created_at", "updated_at",
                    "offer_resource", "demand_resource", "fulfillment_resource",
                    "max_duration_seconds", "seller", "buyer",
                    "matched_offer_id", "seller_attestation", "buyer_attestation",
                    "escrow_uid", "oracle_address", "paused",
                ]
                rows = cur.fetchall()
                result = []
                for row in rows:
                    d = dict(zip(keys, row))
                    d["paused"] = bool(d["paused"])
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
                    "agreed_price", "agreed_duration_seconds",
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
                    "agreed_price", "agreed_duration_seconds", "agreed_at",
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

                return {
                    **thread,
                    "messages": messages,
                    "stage_events": stage_events,
                    "round_count": len(messages),
                }
            finally:
                conn.close()

        return await asyncio.to_thread(_load)

    # ------------------------------------------------------------------
    # Admin status counts
    # ------------------------------------------------------------------

    async def get_admin_status_counts(self) -> dict[str, int]:
        """Return live counts for the admin /status endpoint."""
        def _counts() -> dict[str, int]:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()

                cur.execute(
                    "SELECT COUNT(*) FROM negotiation_threads WHERE terminal_state IS NULL AND status = 'active'"
                )
                active_negotiations = int(cur.fetchone()[0] or 0)

                cur.execute(
                    "SELECT COUNT(*) FROM listings WHERE status = 'open' AND COALESCE(paused, 0) = 0"
                )
                open_orders = int(cur.fetchone()[0] or 0)

                cur.execute(
                    "SELECT COUNT(*) FROM listings WHERE COALESCE(paused, 0) = 1"
                )
                paused_orders = int(cur.fetchone()[0] or 0)

                return {
                    "active_negotiations": active_negotiations,
                    "open_orders": open_orders,
                    "paused_orders": paused_orders,
                }
            finally:
                conn.close()

        return await asyncio.to_thread(_counts)


_sqlite_client: SQLiteClient | None = None


def get_sqlite_client() -> SQLiteClient:
    global _sqlite_client
    if _sqlite_client is None:
        _sqlite_client = SQLiteClient(db_path=CONFIG.agent_db_path)
    return _sqlite_client