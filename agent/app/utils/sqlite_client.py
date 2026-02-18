from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime
from typing import Any

from .config import CONFIG


class SQLiteClient:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._ensure_tables_sync()

    def _ensure_tables_sync(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.cursor()
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
                  our_order_id TEXT,
                  their_order_id TEXT,
                  our_agent_id TEXT,
                  their_agent_id TEXT,
                  status TEXT DEFAULT 'active',
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  terminal_state TEXT
                )
                """
            )
            # Add columns if they don't exist (for existing databases)
            try:
                cur.execute("ALTER TABLE negotiation_threads ADD COLUMN our_order_id TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists
            try:
                cur.execute("ALTER TABLE negotiation_threads ADD COLUMN their_order_id TEXT")
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
                cur.execute("ALTER TABLE negotiation_threads ADD COLUMN agreed_price INTEGER")
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
            # Orders table (local source of truth)
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS orders (
                  order_id TEXT PRIMARY KEY,
                  status TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  offer_resource TEXT NOT NULL,
                  demand_resource TEXT NOT NULL,
                  fulfillment_resource TEXT,
                  duration_hours INTEGER NOT NULL,
                  order_maker TEXT NOT NULL,
                  order_taker TEXT,
                  matched_offer_id TEXT,
                  maker_attestation TEXT,
                  taker_attestation TEXT,
                  escrow_uid TEXT
                )
                """
            )
            # Add negotiation_id column to orders if it doesn't exist
            try:
                cur.execute("ALTER TABLE orders ADD COLUMN negotiation_id TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists
            # Create indexes
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_orders_negotiation_id ON orders(negotiation_id)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_orders_matched_offer_id ON orders(matched_offer_id)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_orders_escrow_uid ON orders(escrow_uid)"
            )
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
                "CREATE INDEX IF NOT EXISTS idx_negotiation_threads_our_order_id ON negotiation_threads(our_order_id)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_negotiation_threads_their_order_id ON negotiation_threads(their_order_id)"
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
                "CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_orders_updated_at ON orders(updated_at)"
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
            return json.dumps(a_dict, sort_keys=True) == json.dumps(b_dict, sort_keys=True)
        except Exception:
            return False

    async def find_symmetric_open_order(
        self,
        *,
        offer_resource: Any,
        demand_resource: Any,
        order_maker: str | None = None,
    ) -> dict[str, Any] | None:
        """Find an open local order whose resources are symmetric to the given pair.

        Symmetric means:
        - local.offer_resource == demand_resource
        - local.demand_resource == offer_resource
        """
        def _find() -> dict[str, Any] | None:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT order_id, offer_resource, demand_resource, order_maker, status, order_taker, created_at
                    FROM orders
                    WHERE status = 'open'
                      AND (order_taker IS NULL OR order_taker = '')
                    """
                )
                rows = cur.fetchall()
                matches: list[dict[str, Any]] = []
                for row in rows:
                    row_order_id, row_offer, row_demand, row_maker, row_status, row_taker, row_created = row
                    if order_maker and row_maker != order_maker:
                        continue
                    if self._resources_equal(row_offer, demand_resource) and self._resources_equal(row_demand, offer_resource):
                        matches.append({
                            "order_id": row_order_id,
                            "order_maker": row_maker,
                            "created_at": row_created,
                        })
                if not matches:
                    return None
                matches.sort(key=lambda m: m.get("created_at") or "", reverse=True)
                return matches[0]
            finally:
                conn.close()

        return await asyncio.to_thread(_find)

    async def upsert_order(
        self,
        *,
        order_id: str,
        status: str,
        created_at: str,
        updated_at: str,
        offer_resource: Any,
        demand_resource: Any,
        fulfillment_resource: Any | None,
        duration_hours: int,
        order_maker: str,
        order_taker: str | None = None,
        matched_offer_id: str | None = None,
        maker_attestation: str | None = None,
        taker_attestation: str | None = None,
        escrow_uid: str | None = None,
        negotiation_id: str | None = None,
    ) -> None:
        def _save() -> None:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO orders(
                      order_id,
                      status,
                      created_at,
                      updated_at,
                      offer_resource,
                      demand_resource,
                      fulfillment_resource,
                      duration_hours,
                      order_maker,
                      order_taker,
                      matched_offer_id,
                      maker_attestation,
                      taker_attestation,
                      escrow_uid,
                      negotiation_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(order_id) DO UPDATE SET
                      status=excluded.status,
                      updated_at=excluded.updated_at,
                      offer_resource=excluded.offer_resource,
                      demand_resource=excluded.demand_resource,
                      fulfillment_resource=excluded.fulfillment_resource,
                      duration_hours=excluded.duration_hours,
                      order_maker=excluded.order_maker,
                      order_taker=excluded.order_taker,
                      matched_offer_id=excluded.matched_offer_id,
                      maker_attestation=excluded.maker_attestation,
                      taker_attestation=excluded.taker_attestation,
                      escrow_uid=excluded.escrow_uid,
                      negotiation_id=excluded.negotiation_id
                    """,
                    (
                        order_id,
                        status,
                        created_at,
                        updated_at,
                        self._serialize_resource(offer_resource),
                        self._serialize_resource(demand_resource),
                        self._serialize_resource(fulfillment_resource),
                        duration_hours,
                        order_maker,
                        order_taker,
                        matched_offer_id,
                        maker_attestation,
                        taker_attestation,
                        escrow_uid,
                        negotiation_id,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

        await asyncio.to_thread(_save)

    async def update_order(
        self,
        *,
        order_id: str,
        status: str | None = None,
        updated_at: str | None = None,
        offer_resource: Any | None = None,
        demand_resource: Any | None = None,
        fulfillment_resource: Any | None = None,
        duration_hours: int | None = None,
        order_maker: str | None = None,
        order_taker: str | None = None,
        matched_offer_id: str | None = None,
        maker_attestation: str | None = None,
        taker_attestation: str | None = None,
        escrow_uid: str | None = None,
        negotiation_id: str | None = None,
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
            add("duration_hours", duration_hours)
            add("order_maker", order_maker)
            add("order_taker", order_taker)
            add("matched_offer_id", matched_offer_id)
            add("maker_attestation", maker_attestation)
            add("taker_attestation", taker_attestation)
            add("escrow_uid", escrow_uid)
            add("negotiation_id", negotiation_id)

            if not updates:
                return

            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    f"UPDATE orders SET {', '.join(updates)} WHERE order_id=?",
                    (*values, order_id),
                )
                conn.commit()
            finally:
                conn.close()

        await asyncio.to_thread(_save)

    async def update_order_by_escrow_uid(
        self,
        *,
        escrow_uid: str,
        status: str | None = None,
        updated_at: str | None = None,
        fulfillment_resource: Any | None = None,
        maker_attestation: str | None = None,
        taker_attestation: str | None = None,
    ) -> None:
        """
        Update order fields based on escrow_uid, when order_id is not available.
        """
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
            add("fulfillment_resource", fulfillment_resource, serialize=True)
            add("maker_attestation", maker_attestation)
            add("taker_attestation", taker_attestation)

            if not updates:
                return

            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    f"UPDATE orders SET {', '.join(updates)} WHERE escrow_uid=?",
                    (*values, escrow_uid),
                )
                conn.commit()
            finally:
                conn.close()

        await asyncio.to_thread(_save)

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
        agreed_price: int | None = None,
    ) -> None:
        """Update the terminal state of a negotiation thread."""
        def _update() -> None:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                if agreed_price is not None:
                    cur.execute(
                        """
                        UPDATE negotiation_threads
                        SET terminal_state = ?, status = 'terminated', updated_at = ?, agreed_price = ?
                        WHERE negotiation_id = ?
                        """,
                        (terminal_state, datetime.now().isoformat(), agreed_price, negotiation_id),
                    )
                else:
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
        our_order_id: str,
        their_order_id: str,
        our_agent_id: str,
        their_agent_id: str,
        owner_id: str,  # The agent creating this record
        status: str = "active",
        our_initial_price: int | None = None,
        our_strategy: str | None = None,
    ) -> None:
        """Create a new negotiation thread with private local state.
        
        Args:
            negotiation_id: Unique negotiation identifier
            our_order_id: Our order ID
            their_order_id: Their order ID
            our_agent_id: Our agent ID (participant A)
            their_agent_id: Their agent ID (participant B)
            owner_id: ID of the agent owning this private state
            status: Initial status (default: 'active')
            our_initial_price: Private initial price
            our_strategy: Private strategy
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
                        negotiation_id, our_order_id, their_order_id,
                        our_agent_id, their_agent_id, status, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        negotiation_id, our_order_id, their_order_id,
                        our_agent_id, their_agent_id, status, timestamp, timestamp
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
                    SELECT t.negotiation_id, t.our_order_id, t.their_order_id,
                           t.our_agent_id, t.their_agent_id, t.status, t.terminal_state,
                           l.our_initial_price, l.our_strategy, t.agreed_price
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
                        "our_order_id": row[1],
                        "their_order_id": row[2],
                        "our_agent_id": row[3],
                        "their_agent_id": row[4],
                        "status": row[5],
                        "terminal_state": row[6],
                        # Default to None if no local state found for this owner
                        "our_initial_price": row[7],
                        "our_strategy": row[8],
                        "agreed_price": row[9],
                    }
                return None
            finally:
                conn.close()
        return await asyncio.to_thread(_get)

    async def check_existing_negotiation(
        self,
        *,
        our_order_id: str | None = None,
        their_order_id: str | None = None,
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
                    SELECT negotiation_id, our_order_id, their_order_id, our_agent_id, their_agent_id, status
                    FROM negotiation_threads
                    WHERE status = 'active' AND (
                        (our_order_id = ? AND their_order_id = ?) OR
                        (our_order_id = ? AND their_order_id = ?) OR
                        (our_agent_id = ? AND their_agent_id = ?) OR
                        (our_agent_id = ? AND their_agent_id = ?)
                    )
                """
                params = (
                    our_order_id, their_order_id,
                    their_order_id, our_order_id,
                    our_agent_id, their_agent_id,
                    their_agent_id, our_agent_id,
                )
                cur.execute(query, params)
                row = cur.fetchone()
                if row:
                    return {
                        "negotiation_id": row[0],
                        "our_order_id": row[1],
                        "their_order_id": row[2],
                        "our_agent_id": row[3],
                        "their_agent_id": row[4],
                        "status": row[5],
                    }
                return None
            finally:
                conn.close()
        return await asyncio.to_thread(_check)

    async def get_active_negotiations_for_order(
        self, *, order_id: str
    ) -> list[dict[str, Any]]:
        """Get all active negotiations involving an order (as our_order_id or their_order_id)."""
        def _load() -> list[dict[str, Any]]:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT negotiation_id, our_order_id, their_order_id, our_agent_id, their_agent_id, status
                    FROM negotiation_threads
                    WHERE (our_order_id = ? OR their_order_id = ?) AND status = 'active'
                    """,
                    (order_id, order_id),
                )
                rows = cur.fetchall()
                result = []
                for row in rows:
                    result.append({
                        "negotiation_id": row[0],
                        "our_order_id": row[1],
                        "their_order_id": row[2],
                        "our_agent_id": row[3],
                        "their_agent_id": row[4],
                        "status": row[5],
                    })
                return result
            finally:
                conn.close()
        return await asyncio.to_thread(_load)

    async def get_active_negotiations_for_agent(
        self, *, agent_id: str
    ) -> list[dict[str, Any]]:
        """Get all active negotiations involving an agent (as our_agent_id or their_agent_id)."""
        def _load() -> list[dict[str, Any]]:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT negotiation_id, our_order_id, their_order_id, our_agent_id, their_agent_id, status
                    FROM negotiation_threads
                    WHERE (our_agent_id = ? OR their_agent_id = ?) AND status = 'active'
                    """,
                    (agent_id, agent_id),
                )
                rows = cur.fetchall()
                result = []
                for row in rows:
                    result.append({
                        "negotiation_id": row[0],
                        "our_order_id": row[1],
                        "their_order_id": row[2],
                        "our_agent_id": row[3],
                        "their_agent_id": row[4],
                        "status": row[5],
                    })
                return result
            finally:
                conn.close()
        return await asyncio.to_thread(_load)

    async def cancel_negotiations_for_order(
        self, *, order_id: str, except_negotiation_id: str | None = None
    ) -> list[str]:
        """Cancel all active negotiations for an order, except the specified one.
        
        Returns:
            List of canceled negotiation IDs
        """
        def _cancel() -> list[str]:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                
                # Find all active negotiations involving this order
                cur.execute(
                    """
                    SELECT negotiation_id, our_order_id, their_order_id, 
                           our_agent_id, their_agent_id
                    FROM negotiation_threads
                    WHERE (our_order_id = ? OR their_order_id = ?)
                      AND (status = 'active')
                      AND negotiation_id != COALESCE(?, '')
                    """,
                    (order_id, order_id, except_negotiation_id or '')
                )
                
                canceled_ids = []
                for row in cur.fetchall():
                    neg_id = row[0]
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
                    canceled_ids.append(neg_id)
                
                conn.commit()
                return canceled_ids
            finally:
                conn.close()
        
        return await asyncio.to_thread(_cancel)

    async def cancel_negotiations_for_agent(
        self, *, agent_id: str, except_negotiation_id: str | None = None
    ) -> None:
        """Cancel all active negotiations for an agent, except the specified one."""
        def _cancel() -> None:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    UPDATE negotiation_threads
                    SET status = 'superseded',
                        terminal_state = 'superseded',
                        updated_at = ?
                    WHERE (our_agent_id = ? OR their_agent_id = ?)
                      AND (status = 'active')
                      AND negotiation_id != COALESCE(?, '')
                    """,
                    (datetime.now().isoformat(), agent_id, agent_id, except_negotiation_id or '')
                )
                conn.commit()
            finally:
                conn.close()
        await asyncio.to_thread(_cancel)


    async def list_negotiations(
        self,
        *,
        status: str | None = None,
        order_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        def _load() -> list[dict[str, Any]]:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                filters: list[str] = []
                params: list[Any] = []
                if status:
                    filters.append("t.status = ?")
                    params.append(status)
                if order_id:
                    filters.append("(t.our_order_id = ? OR t.their_order_id = ?)")
                    params.extend([order_id, order_id])
                where = " WHERE " + " AND ".join(filters) if filters else ""
                params.append(limit)
                cur.execute(
                    f"""
                    SELECT t.negotiation_id, t.our_order_id, t.their_order_id,
                           t.status, t.terminal_state, t.updated_at,
                           COUNT(m.message_id) AS round_count, t.agreed_price
                    FROM negotiation_threads t
                    LEFT JOIN negotiation_messages m ON m.negotiation_id = t.negotiation_id
                    {where}
                    GROUP BY t.negotiation_id
                    ORDER BY t.updated_at DESC LIMIT ?
                    """,
                    params,
                )
                cols = ["negotiation_id", "our_order_id", "their_order_id",
                        "status", "terminal_state", "updated_at", "round_count",
                        "agreed_price"]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
            finally:
                conn.close()
        return await asyncio.to_thread(_load)

    async def get_negotiation_detail(
        self,
        *,
        negotiation_id: str,
        owner_id: str,
    ) -> dict[str, Any] | None:
        def _load() -> dict[str, Any] | None:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT t.negotiation_id, t.our_order_id, t.their_order_id,
                           t.our_agent_id, t.their_agent_id, t.status, t.terminal_state,
                           t.created_at, t.updated_at,
                           l.our_strategy, l.our_initial_price, t.agreed_price
                    FROM negotiation_threads t
                    LEFT JOIN negotiation_local_state l
                           ON t.negotiation_id = l.negotiation_id AND l.owner_id = ?
                    WHERE t.negotiation_id = ?
                    """,
                    (owner_id, negotiation_id),
                )
                row = cur.fetchone()
                if not row:
                    return None
                result = {
                    "negotiation_id": row[0], "our_order_id": row[1],
                    "their_order_id": row[2], "our_agent_id": row[3],
                    "their_agent_id": row[4], "status": row[5],
                    "terminal_state": row[6], "created_at": row[7],
                    "updated_at": row[8], "our_strategy": row[9],
                    "our_initial_price": row[10], "agreed_price": row[11],
                }
                cur.execute(
                    """
                    SELECT round, sender, action_taken, our_price, their_price,
                           proposed_price, message_type, timestamp
                    FROM negotiation_messages
                    WHERE negotiation_id = ?
                    ORDER BY round ASC
                    """,
                    (negotiation_id,),
                )
                msg_cols = ["round", "sender", "action_taken", "our_price",
                            "their_price", "proposed_price", "message_type", "timestamp"]
                result["messages"] = [dict(zip(msg_cols, r)) for r in cur.fetchall()]
                return result
            finally:
                conn.close()
        return await asyncio.to_thread(_load)

    async def get_decision(self, *, decision_id: str) -> dict[str, Any] | None:
        def _load() -> dict[str, Any] | None:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT d.decision_id, d.event_id, d.event_type, d.agent_id,
                           d.policy_used, d.action_type, d.context_json, d.timestamp,
                           o.outcome_json, o.timestamp AS outcome_timestamp
                    FROM decisions d
                    LEFT JOIN decision_outcomes o ON d.decision_id = o.decision_id
                    WHERE d.decision_id = ?
                    """,
                    (decision_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return {
                    "decision_id": row[0], "event_id": row[1],
                    "event_type": row[2], "agent_id": row[3],
                    "policy_used": row[4], "action_type": row[5],
                    "context_json": row[6], "timestamp": row[7],
                    "outcome_json": row[8], "outcome_timestamp": row[9],
                }
            finally:
                conn.close()
        return await asyncio.to_thread(_load)

    async def list_decisions_with_outcomes(
        self,
        *,
        agent_id: str,
        limit: int = 50,
        event_type: str | None = None,
        action_type: str | None = None,
    ) -> list[dict[str, Any]]:
        def _load() -> list[dict[str, Any]]:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                filters = ["d.agent_id = ?"]
                params: list[Any] = [agent_id]
                if event_type:
                    filters.append("d.event_type = ?")
                    params.append(event_type)
                if action_type:
                    filters.append("d.action_type = ?")
                    params.append(action_type)
                where = " WHERE " + " AND ".join(filters)
                params.append(limit)
                cur.execute(
                    f"""
                    SELECT d.decision_id, d.event_type, d.policy_used,
                           d.action_type, d.timestamp, o.outcome_json
                    FROM decisions d
                    LEFT JOIN decision_outcomes o ON d.decision_id = o.decision_id
                    {where}
                    ORDER BY d.timestamp DESC LIMIT ?
                    """,
                    params,
                )
                cols = ["decision_id", "event_type", "policy_used",
                        "action_type", "timestamp", "outcome_json"]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
            finally:
                conn.close()
        return await asyncio.to_thread(_load)

    async def load_order(self, *, order_id: str) -> dict[str, Any] | None:
        """Load a single order by primary key (no decision joins)."""
        def _load() -> dict[str, Any] | None:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,))
                row = cur.fetchone()
                if not row:
                    return None
                cols = [desc[0] for desc in cur.description]
                return dict(zip(cols, row))
            finally:
                conn.close()
        return await asyncio.to_thread(_load)

    async def find_latest_order_by_matched_offer_id(
        self,
        *,
        matched_offer_id: str,
        order_maker: str | None = None,
    ) -> dict[str, Any] | None:
        """Find the most recent local order linked to a remote order via matched_offer_id."""
        def _find() -> dict[str, Any] | None:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                if order_maker:
                    cur.execute(
                        """
                        SELECT * FROM orders
                        WHERE matched_offer_id = ? AND order_maker = ?
                        ORDER BY updated_at DESC LIMIT 1
                        """,
                        (matched_offer_id, order_maker),
                    )
                else:
                    cur.execute(
                        """
                        SELECT * FROM orders
                        WHERE matched_offer_id = ?
                        ORDER BY updated_at DESC LIMIT 1
                        """,
                        (matched_offer_id,),
                    )
                row = cur.fetchone()
                if not row:
                    return None
                cols = [desc[0] for desc in cur.description]
                return dict(zip(cols, row))
            finally:
                conn.close()
        return await asyncio.to_thread(_find)

    async def load_orders_by_escrow_uid(
        self,
        *,
        escrow_uid: str,
    ) -> list[dict[str, Any]]:
        """Find all orders sharing an escrow UID."""
        def _load() -> list[dict[str, Any]]:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT * FROM orders WHERE escrow_uid = ? ORDER BY updated_at DESC",
                    (escrow_uid,),
                )
                cols = [desc[0] for desc in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
            finally:
                conn.close()
        return await asyncio.to_thread(_load)

    async def find_order_by_negotiation_id(
        self,
        *,
        negotiation_id: str,
        order_maker: str | None = None,
    ) -> dict[str, Any] | None:
        """Find a local order by its negotiation_id."""
        def _find() -> dict[str, Any] | None:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                if order_maker:
                    cur.execute(
                        """
                        SELECT * FROM orders
                        WHERE negotiation_id = ? AND order_maker = ?
                        ORDER BY updated_at DESC LIMIT 1
                        """,
                        (negotiation_id, order_maker),
                    )
                else:
                    cur.execute(
                        """
                        SELECT * FROM orders
                        WHERE negotiation_id = ?
                        ORDER BY updated_at DESC LIMIT 1
                        """,
                        (negotiation_id,),
                    )
                row = cur.fetchone()
                if not row:
                    return None
                cols = [desc[0] for desc in cur.description]
                return dict(zip(cols, row))
            finally:
                conn.close()
        return await asyncio.to_thread(_find)

    async def get_orders(self, *, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        def _load() -> list[dict[str, Any]]:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                if status:
                    cur.execute(
                        "SELECT * FROM orders WHERE status = ? ORDER BY updated_at DESC LIMIT ?",
                        (status, limit),
                    )
                else:
                    cur.execute(
                        "SELECT * FROM orders ORDER BY updated_at DESC LIMIT ?",
                        (limit,),
                    )
                cols = [desc[0] for desc in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
            finally:
                conn.close()
        return await asyncio.to_thread(_load)

    async def get_order(self, *, order_id: str) -> dict[str, Any] | None:
        def _load() -> dict[str, Any] | None:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,))
                row = cur.fetchone()
                if not row:
                    return None
                cols = [desc[0] for desc in cur.description]
                order = dict(zip(cols, row))
                # Join decision outcomes for this order
                cur.execute(
                    """
                    SELECT d.decision_id, d.event_type, d.action_type, d.timestamp, do.outcome_json
                    FROM decisions d
                    LEFT JOIN decision_outcomes do ON d.decision_id = do.decision_id
                    WHERE d.event_id = ?
                    ORDER BY d.timestamp DESC
                    """,
                    (order_id,),
                )
                dcols = [desc[0] for desc in cur.description]
                order["decisions"] = [dict(zip(dcols, r)) for r in cur.fetchall()]
                return order
            finally:
                conn.close()
        return await asyncio.to_thread(_load)


_sqlite_client: SQLiteClient | None = None


def get_sqlite_client() -> SQLiteClient:
    global _sqlite_client
    if _sqlite_client is None:
        _sqlite_client = SQLiteClient(db_path=CONFIG.agent_db_path)
    return _sqlite_client
