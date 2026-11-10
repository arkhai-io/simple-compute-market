"""A normalized structural view of a SQLite schema, for tests to compare.

Two databases built by different paths -- a baseline's ``CREATE TABLE`` and an
older chain's ``CREATE TABLE`` followed by ``ALTER TABLE ... ADD COLUMN`` --
store different SQL text for the same structure. The snapshot is read from
SQLite's own reports of each table's columns, keys, and indexes, so it compares
structure, not spelling. What SQLite reports only in a table's text -- a
``CHECK`` and ``AUTOINCREMENT`` -- is taken from that text, a ``CHECK`` with its
whitespace collapsed; a partial index's ``WHERE`` clause, an expression index's
definition, and a trigger's or view's body likewise. A column's ``COLLATE`` is
not seen. The ledger table is the engine's, not the service's, and is left out.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from market_schema_migrations.engine import LEDGER_TABLE

_WHITESPACE = re.compile(r"\s+")
_SPACE_AROUND_PUNCTUATION = re.compile(r"\s*([(),])\s*")
_AUTOINCREMENT = re.compile(r"\bAUTOINCREMENT\b", re.IGNORECASE)


def _normalize_sql(sql: str) -> str:
    collapsed = _WHITESPACE.sub(" ", sql.strip())
    return _SPACE_AROUND_PUNCTUATION.sub(r"\1", collapsed).rstrip(";")


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _check_constraints(sql: str) -> list[str]:
    """Every ``CHECK (...)`` clause in a table's text, normalized and sorted."""

    found: list[str] = []
    for match in re.finditer(r"\bCHECK\s*\(", sql, re.IGNORECASE):
        depth = 0
        start = match.end() - 1
        in_string: str | None = None
        for index in range(start, len(sql)):
            char = sql[index]
            if in_string is not None:
                if char == in_string:
                    in_string = None
                continue
            if char in ("'", '"'):
                in_string = char
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    found.append(_normalize_sql(sql[start + 1 : index]))
                    break
    return sorted(found)


def _partial_clause(sql: str | None) -> str | None:
    if not sql:
        return None
    match = re.search(r"\bWHERE\b(.*)$", sql, re.IGNORECASE | re.DOTALL)
    return _normalize_sql(match.group(1)) if match else None


def _columns(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    rows = connection.execute(f"PRAGMA table_xinfo({_quote(table)})").fetchall()
    return [
        {
            "name": name,
            "type": _WHITESPACE.sub(" ", (declared or "").strip()).upper(),
            "not_null": bool(not_null),
            "default": None if default is None else _normalize_sql(str(default)),
            "primary_key": int(pk),
            "hidden": int(hidden),
        }
        for _cid, name, declared, not_null, default, pk, hidden in rows
    ]


def _foreign_keys(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    rows = connection.execute(f"PRAGMA foreign_key_list({_quote(table)})").fetchall()
    keys: dict[int, dict[str, Any]] = {}
    for key_id, _seq, referenced, column, target, on_update, on_delete, match in rows:
        key = keys.setdefault(
            key_id,
            {
                "table": referenced,
                "columns": [],
                "references": [],
                "on_update": on_update,
                "on_delete": on_delete,
                "match": match,
            },
        )
        key["columns"].append(column)
        key["references"].append(target)
    return sorted(keys.values(), key=lambda key: (key["table"], key["columns"]))


def _indexes(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    indexes: list[dict[str, Any]] = []
    for _seq, name, unique, origin, partial in connection.execute(
        f"PRAGMA index_list({_quote(table)})"
    ).fetchall():
        keys = [
            {"column": column, "descending": bool(descending), "collation": collation}
            for _seqno, _cid, column, descending, collation, key in connection.execute(
                f"PRAGMA index_xinfo({_quote(name)})"
            ).fetchall()
            if key
        ]
        sql_row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?", (name,)
        ).fetchone()
        sql = sql_row[0] if sql_row else None
        indexes.append(
            {
                # SQLite names the index behind a UNIQUE or PRIMARY KEY
                # constraint by its position among the table's constraints,
                # which says nothing about structure.
                "name": name if origin == "c" else None,
                "unique": bool(unique),
                "origin": origin,
                "columns": keys,
                "where": _partial_clause(sql) if partial else None,
                # An expression key reports no column, so its definition is
                # the index's text.
                "expression": _normalize_sql(sql)
                if sql and any(key["column"] is None for key in keys)
                else None,
            }
        )
    return sorted(
        indexes,
        key=lambda index: (index["name"] or "", index["origin"], repr(index["columns"])),
    )


def schema_snapshot(connection: sqlite3.Connection) -> dict[str, Any]:
    """The tables, columns, keys, indexes, triggers, and views of a database.

    The result holds only plain values, so a test can commit it as JSON and
    compare a database built by a chain with it.
    """

    objects = connection.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
    ).fetchall()
    tables: dict[str, Any] = {}
    triggers: dict[str, Any] = {}
    views: dict[str, str] = {}
    for kind, name, table, sql in objects:
        if kind == "table" and name != LEDGER_TABLE:
            _schema, _name, _type, _ncol, without_rowid, strict = connection.execute(
                f"PRAGMA table_list({_quote(name)})"
            ).fetchone()
            tables[name] = {
                "columns": _columns(connection, name),
                "foreign_keys": _foreign_keys(connection, name),
                "indexes": _indexes(connection, name),
                "checks": _check_constraints(sql or ""),
                "autoincrement": bool(_AUTOINCREMENT.search(sql or "")),
                "without_rowid": bool(without_rowid),
                "strict": bool(strict),
            }
        elif kind == "trigger":
            triggers[name] = {"table": table, "sql": _normalize_sql(sql or "")}
        elif kind == "view":
            views[name] = _normalize_sql(sql or "")
    return {"tables": tables, "triggers": triggers, "views": views}
