"""Deal servicing's tables come from the storefront's chain, never from opening a session.

Real SQLite files, no application: the schema a storefront migration applies
through ``create_schema``, and what each session and the respondent poller do
to a database when opened.
"""

import sqlite3
from unittest.mock import AsyncMock

import pytest

from market_deal_servicing import (
    SERVICING_SCHEMA, EndSession, EvidenceSession, RespondentPoller, SellerSession, WatchSession,
    create_schema,
)
from market_deal_servicing.evidence import transaction

_DDL_VERBS = ("CREATE", "ALTER", "DROP")


def _snapshot(path):
    """Every schema object with the DDL SQLite stored for it."""
    conn = sqlite3.connect(path)
    try:
        return conn.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall()
    finally:
        conn.close()


def _object_names(path):
    conn = sqlite3.connect(path)
    try:
        return {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
            )
        }
    finally:
        conn.close()


def _declared_names():
    names = set()
    for statement in SERVICING_SCHEMA:
        words = statement.split()
        # CREATE [UNIQUE] {TABLE|INDEX} IF NOT EXISTS <name> ...
        names.add(words[words.index("EXISTS") + 1])
    return names


def test_the_schema_creates_every_servicing_table_and_index_on_an_empty_database(tmp_path):
    path = tmp_path / "storefront.sqlite"
    with transaction(path) as conn:
        create_schema(conn)
    assert _object_names(path) == _declared_names()
    assert all(statement.split()[0] == "CREATE" and "IF NOT EXISTS" in statement
               for statement in SERVICING_SCHEMA)


def test_the_schema_leaves_present_tables_and_their_rows_unchanged(tmp_path):
    path = tmp_path / "storefront.sqlite"
    with transaction(path) as conn:
        create_schema(conn)
        conn.execute("INSERT INTO servicing_delivery VALUES ('deal', 3, '{}')")
    before = _snapshot(path)
    with transaction(path) as conn:
        create_schema(conn)
    assert _snapshot(path) == before
    with transaction(path) as conn:
        assert conn.execute("SELECT * FROM servicing_delivery").fetchall() == [("deal", 3, "{}")]


def test_the_schema_completes_a_database_holding_only_some_servicing_tables(tmp_path):
    """A storefront that captured evidence but never registered a delivery
    holds the evidence tables alone; applying the schema adds the rest."""
    path = tmp_path / "storefront.sqlite"
    evidence = [s for s in SERVICING_SCHEMA if "servicing_evidence" in s or "servicing_one_live" in s]
    with transaction(path) as conn:
        for statement in evidence:
            conn.execute(statement)
        conn.execute("INSERT INTO servicing_evidence_deals(negotiation_id) VALUES ('deal')")
    with transaction(path) as conn:
        create_schema(conn)
    assert _object_names(path) == _declared_names()
    with transaction(path) as conn:
        assert conn.execute("SELECT negotiation_id FROM servicing_evidence_deals").fetchall() == [("deal",)]

    fresh = tmp_path / "fresh.sqlite"
    with transaction(fresh) as conn:
        create_schema(conn)
    assert _snapshot(path) == _snapshot(fresh)


def test_opening_each_session_issues_no_ddl(tmp_path):
    path = tmp_path / "storefront.sqlite"
    with transaction(path) as conn:
        create_schema(conn)
    before = _snapshot(path)
    statements = []
    with transaction(path) as conn:
        conn.set_trace_callback(statements.append)
        EvidenceSession(conn)
        EndSession(conn)
        WatchSession(conn)
        SellerSession(conn)
        conn.set_trace_callback(None)
    assert not [s for s in statements if s.lstrip().upper().startswith(_DDL_VERBS)]
    assert _snapshot(path) == before


def test_opening_a_session_on_a_database_without_its_tables_creates_none(tmp_path):
    path = tmp_path / "storefront.sqlite"
    with transaction(path) as conn:
        EvidenceSession(conn)
        EndSession(conn)
        WatchSession(conn)
        SellerSession(conn)
    assert _object_names(path) == set()


async def test_the_respondent_poller_reads_through_the_chains_tables_and_creates_none(rig, tmp_path):
    def poller(path):
        return RespondentPoller(
            path, authority=rig["authority"], account="seller-account", read=AsyncMock(),
            resolve=lambda _case: None, signer=rig["seller"], clock=lambda: 150,
        )

    before = _snapshot(rig["path"])
    assert await poller(rig["path"]).repairs() == []
    assert _snapshot(rig["path"]) == before

    bare = tmp_path / "bare.sqlite"
    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        await poller(bare).repairs()
    assert _object_names(bare) == set()
