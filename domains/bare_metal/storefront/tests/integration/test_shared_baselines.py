"""The shared baselines reproduce the v0.3.0 floor's tables they own.

A real SQLite database, no application: core storefront's, the settlement
runtime's, contact exchange's, and the pool-override store's baselines, applied
in the order a storefront chain composes them, give exactly the tables,
indexes, and triggers of those packages in the bare-metal storefront's floor
fixture. The bare-metal floor is the one to compare with because its ``escrows``
is core's alone: the VM and API-credit storefronts add their own obligation
columns to it.
"""

import json
import sqlite3
from pathlib import Path

from core_storefront import migrations as core
from market_contact_exchange import migrations as contact_exchange
from market_pool_overrides import migrations as pool_overrides
from market_schema_migrations import schema_snapshot
from market_settlement_runtime import migrations as settlement

_FLOOR = Path(__file__).resolve().parents[1] / "fixtures" / "v0_3_0_floor" / "schema.json"

_SHARED = (core, settlement, contact_exchange, pool_overrides)


def test_the_shared_baselines_reproduce_their_floor_tables() -> None:
    owned = frozenset().union(*(package.BASELINE_TABLES for package in _SHARED))
    floor = json.loads(_FLOOR.read_text())
    expected = {
        "tables": {name: table for name, table in floor["tables"].items() if name in owned},
        "triggers": {
            name: trigger
            for name, trigger in floor["triggers"].items()
            if trigger["table"] in owned
        },
        "views": {},
    }

    conn = sqlite3.connect(":memory:")
    try:
        for package in _SHARED:
            package.BASELINE.apply(conn)
        assert schema_snapshot(conn) == expected
    finally:
        conn.close()
