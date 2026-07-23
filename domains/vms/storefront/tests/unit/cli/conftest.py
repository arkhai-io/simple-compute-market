"""Shared fixtures for market-storefront CLI unit tests.

CLI unit tests intentionally patch the boundary each command has already
resolved. They do not perform real network, chain, subprocess, Make, or SQLite
work; command-group tests assert CLI wiring, validation, and rendering behavior.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from typer.testing import CliRunner


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def app():
    from market_storefront.cli import app

    return app


@pytest.fixture
def private_key() -> str:
    return "0x" + "ab" * 32


def fake_chain(name: str = "anvil") -> Any:
    """Minimal ChainConfig-like object sufficient for CLI tests."""
    return SimpleNamespace(
        name=name,
        rpc_url="http://localhost:8545",
        chain_id=31337,
        alkahest_address_config_path=None,
    )


class FakeRow(dict):
    """sqlite3.Row-like test row supporting string and integer indexing."""

    def __init__(self, mapping: dict[str, Any], columns: list[str] | None = None):
        super().__init__(mapping)
        self._columns = columns or list(mapping.keys())

    def __getitem__(self, key: str | int) -> Any:
        if isinstance(key, int):
            return dict.__getitem__(self, self._columns[key])
        return dict.__getitem__(self, key)


class FakeRows:
    def __init__(self, rows: list[Any]):
        self.rows = rows

    def fetchall(self) -> list[Any]:
        return self.rows

    def fetchone(self) -> Any | None:
        return self.rows[0] if self.rows else None


class FakeLogCursor:
    def __init__(self, conn: "FakeLogConnection"):
        self.conn = conn

    def execute(self, query: str, params: list[Any] | tuple[Any, ...] = ()) -> FakeRows:
        return self.conn.execute(query, params)


class FakeLogConnection:
    """Small fake for the query surface used by ``market-storefront logs``."""

    row_factory = None

    def __init__(
        self,
        *,
        stage_events: list[dict[str, Any]] | None = None,
        threads: list[dict[str, Any]] | None = None,
        listings: list[dict[str, Any]] | None = None,
        escrows: list[dict[str, Any]] | None = None,
        messages_count: int = 0,
        fail_stage_events: bool = False,
    ) -> None:
        self.stage_events = stage_events or []
        self.threads = threads or []
        self.listings = listings or []
        self.escrows = escrows or []
        self.messages_count = messages_count
        self.fail_stage_events = fail_stage_events
        self.queries: list[tuple[str, list[Any] | tuple[Any, ...]]] = []
        self.closed = False

    def cursor(self) -> FakeLogCursor:
        return FakeLogCursor(self)

    def execute(self, query: str, params: list[Any] | tuple[Any, ...] = ()) -> FakeRows:
        import sqlite3

        self.queries.append((query, params))
        compact = " ".join(query.split())

        if "FROM stage_events" in compact:
            if self.fail_stage_events:
                raise sqlite3.OperationalError("no such table: stage_events")
            status_shape = compact.startswith("SELECT ts, stage, event, data FROM stage_events")
            return FakeRows([self._stage_event_row(row, status_shape=status_shape) for row in self._filtered_stage_events(compact, params)])

        if "COUNT(*) FROM negotiation_messages" in compact:
            return FakeRows([FakeRow({"count": self.messages_count}, ["count"])])

        if "FROM negotiation_threads WHERE negotiation_id = ?" in compact:
            needle = params[0]
            rows = [self._thread_row(row) for row in self.threads if row.get("negotiation_id") == needle]
            if compact.startswith("SELECT negotiation_id"):
                rows = [FakeRow({"negotiation_id": r["negotiation_id"]}, ["negotiation_id"]) for r in rows]
            return FakeRows(rows)

        if "FROM negotiation_threads WHERE our_listing_id = ? OR their_listing_id = ?" in compact:
            needles = set(params)
            rows = [
                FakeRow({"negotiation_id": row["negotiation_id"]}, ["negotiation_id"])
                for row in self.threads
                if row.get("our_listing_id") in needles or row.get("their_listing_id") in needles
            ]
            return FakeRows(rows)

        if "FROM listings WHERE listing_id = ?" in compact:
            needle = params[0]
            return FakeRows([self._listing_row(row) for row in self.listings if row.get("listing_id") == needle])

        if "FROM escrows" in compact:
            needle = params[0]
            return FakeRows([
                FakeRow(
                    {
                        "escrow_uid": row.get("escrow_uid"),
                        "fulfillment_uid": row.get("fulfillment_uid"),
                    },
                    ["escrow_uid", "fulfillment_uid"],
                )
                for row in self.escrows
                if row.get("negotiation_id") == needle and row.get("is_primary", 1) == 1
            ])

        raise AssertionError(f"Unexpected query: {query!r} params={params!r}")

    def close(self) -> None:
        self.closed = True

    def _filtered_stage_events(self, query: str, params: list[Any] | tuple[Any, ...]) -> list[dict[str, Any]]:
        rows = list(self.stage_events)
        if "negotiation_id = ? OR negotiation_id LIKE ?" in query:
            needle = params[0]
            rows = [row for row in rows if row.get("negotiation_id") == needle or needle in str(row.get("negotiation_id") or "")]
        if "stage = ?" in query:
            stage = params[-2] if query.endswith("LIMIT ?") else params[-1]
            rows = [row for row in rows if row.get("stage") == stage]
        if "negotiation_id IN" in query:
            needles = set(params)
            rows = [
                row for row in rows
                if row.get("negotiation_id") in needles
                or row.get("listing_id") in needles
                or row.get("escrow_uid") in needles
            ]
        return rows

    @staticmethod
    def _stage_event_row(row: dict[str, Any], *, status_shape: bool = False) -> FakeRow:
        data = row.get("data")
        if not isinstance(data, str):
            import json

            data = json.dumps(data or {})
        if status_shape:
            mapping = {
                "ts": row.get("ts", "2024-01-01T00:00:00Z"),
                "stage": row["stage"],
                "event": row["event"],
                "data": data,
            }
            return FakeRow(mapping, ["ts", "stage", "event", "data"])
        mapping = {
            "ts": row.get("ts", "2024-01-01T00:00:00Z"),
            "stage": row["stage"],
            "event": row["event"],
            "negotiation_id": row.get("negotiation_id"),
            "listing_id": row.get("listing_id"),
            "escrow_uid": row.get("escrow_uid"),
            "data": data,
        }
        return FakeRow(mapping, ["ts", "stage", "event", "negotiation_id", "listing_id", "escrow_uid", "data"])

    @staticmethod
    def _thread_row(row: dict[str, Any]) -> FakeRow:
        defaults = {
            "negotiation_id": row.get("negotiation_id"),
            "our_listing_id": row.get("our_listing_id"),
            "their_listing_id": row.get("their_listing_id"),
            "status": row.get("status", "active"),
            "terminal_state": row.get("terminal_state"),
        }
        return FakeRow(defaults, list(defaults))

    @staticmethod
    def _listing_row(row: dict[str, Any]) -> FakeRow:
        defaults = {
            "listing_id": row.get("listing_id"),
            "status": row.get("status", "open"),
        }
        return FakeRow(defaults, list(defaults))


@pytest.fixture
def fake_log_db(monkeypatch):
    """Patch logs DB resolution/connect and return a setter for the fake DB."""
    import market_storefront.cli_logs as logs_mod

    state: dict[str, FakeLogConnection] = {}

    def install(conn: FakeLogConnection, db_path: str = "/fake/agent.db") -> FakeLogConnection:
        state["conn"] = conn
        monkeypatch.setattr(logs_mod, "_resolve_db_path", lambda _db: db_path)
        monkeypatch.setattr(logs_mod.sqlite3, "connect", lambda *args, **kwargs: conn)
        return conn

    return install


@pytest.fixture
def patch_escrow_show_prereqs(monkeypatch):
    def install(*, chains: dict[str, Any] | None = None, decoded: Any | None = None, error: Exception | None = None) -> None:
        import market_storefront.utils.config as config_mod

        monkeypatch.setattr(config_mod, "CHAINS", chains or {"anvil": fake_chain("anvil")})
        monkeypatch.setattr(
            "market_alkahest.alkahest.prewarm_alkahest_address_config_cache",
            lambda _path: None,
        )
        monkeypatch.setattr(
            "market_alkahest.alkahest.resolve_alkahest_address_config",
            lambda _net, **_kwargs: object(),
        )
        monkeypatch.setattr(
            "market_alkahest.alkahest.get_alkahest_network",
            lambda _name: "anvil",
        )
        monkeypatch.setattr("alkahest_py.AlkahestClient", lambda **_kwargs: object())

        async def fake_get_obligation(*_args, **_kwargs):
            if error:
                raise error
            return decoded

        monkeypatch.setattr(
            "market_alkahest.alkahest.get_escrow_obligation_with_codec",
            fake_get_obligation,
        )

    return install
