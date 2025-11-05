from __future__ import annotations

import asyncio
import json
import sqlite3
from typing import Any


class SQLiteClient:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._ensure_tables_sync()

    def _ensure_tables_sync(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.cursor()
            # Policies table
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS policies (
                  agent_id TEXT NOT NULL,
                  name TEXT NOT NULL,
                  trigger_type TEXT NOT NULL,
                  rule_json TEXT,
                  callable_ref TEXT,
                  priority INTEGER,
                  PRIMARY KEY(agent_id, name)
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
                  confidence REAL,
                  timestamp TEXT NOT NULL,
                  context_json TEXT
                )
                """
            )
            # Decision outcomes table (no utility column)
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
            conn.commit()
        finally:
            conn.close()

    async def save_policy(
        self,
        *,
        agent_id: str,
        name: str,
        trigger_type: str,
        rule_json: str | None,
        callable_ref: str | None,
        priority: int,
    ) -> None:
        def _save() -> None:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO policies(agent_id, name, trigger_type, rule_json, callable_ref, priority)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(agent_id, name) DO UPDATE SET
                        trigger_type=excluded.trigger_type,
                        rule_json=excluded.rule_json,
                        callable_ref=excluded.callable_ref,
                        priority=excluded.priority
                    """,
                    (agent_id, name, trigger_type, rule_json, callable_ref, priority),
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
                    "SELECT name, rule_json, callable_ref, priority FROM policies WHERE agent_id=? AND trigger_type=?",
                    (agent_id, trigger_type),
                )
                rows = cur.fetchall()
                result: list[dict[str, Any]] = []
                for (name, rule_json, callable_ref, priority) in rows:
                    result.append(
                        {
                            "name": name,
                            "rule_json": rule_json,
                            "callable_ref": callable_ref,
                            "priority": priority,
                        }
                    )
                return result
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
                    INSERT INTO decisions(decision_id, event_id, event_type, agent_id, policy_used, action_type, confidence, timestamp, context_json)
                    VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?)
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
        """Load recent decisions for context building."""
        def _load() -> list[dict[str, Any]]:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.cursor()
                if event_type:
                    cur.execute(
                        """
                        SELECT decision_id, event_id, event_type, policy_used, action_type, timestamp, context_json
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
                        SELECT decision_id, event_id, event_type, policy_used, action_type, timestamp, context_json
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
                        "context_json": row[6],
                    })
                return result
            finally:
                conn.close()
        
        return await asyncio.to_thread(_load)


