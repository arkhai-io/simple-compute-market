"""The opening hook hands the repository one write: the thread, its message, and the purchase terms."""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace

from market_negotiation_runtime import NegotiationTerms, OpeningWrite

from arkhai_api.purchase import provision_terms_model
from arkhai_api_selling.negotiation import open_negotiation
from arkhai_api_selling.persistence import TERMS_TABLE
from tests.bundles import EXAMPLE


class _Repository:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def open_negotiation(self, *, thread, message, domain_writes=None) -> int:
        self.calls.append({"thread": thread, "message": message, "domain_writes": domain_writes})
        return 0


def _write(terms) -> OpeningWrite:
    opening = SimpleNamespace(negotiation_id="neg-1", terms=NegotiationTerms(decoded=terms, wire=None))
    return OpeningWrite(thread={"negotiation_id": "neg-1"}, message={"negotiation_id": "neg-1"}, opening=opening)


def _terms_table() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        f"CREATE TABLE {TERMS_TABLE} (negotiation_id TEXT PRIMARY KEY, quantity INTEGER NOT NULL, "
        "key_mode TEXT NOT NULL DEFAULT 'new', key_id TEXT)"
    )
    return conn


async def test_the_terms_are_written_in_the_repositorys_opening_transaction():
    repository = _Repository()
    terms = provision_terms_model(EXAMPLE.kind).purchase(quantity=3, key_mode="existing", key_id="ak_1")

    await open_negotiation(repository, _write(terms))

    (call,) = repository.calls
    assert call["thread"] == {"negotiation_id": "neg-1"}
    assert call["message"] == {"negotiation_id": "neg-1"}
    conn = _terms_table()
    call["domain_writes"](conn)
    assert conn.execute(f"SELECT negotiation_id, quantity, key_mode, key_id FROM {TERMS_TABLE}").fetchall() == [
        ("neg-1", 3, "existing", "ak_1")
    ]


async def test_an_opening_without_a_quantity_writes_no_terms():
    repository = _Repository()

    await open_negotiation(repository, _write(None))

    (call,) = repository.calls
    assert call["domain_writes"] is None
