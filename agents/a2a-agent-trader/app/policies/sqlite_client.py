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


