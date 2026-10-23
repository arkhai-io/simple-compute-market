"""The coordinator's continuations resolve the stage the accepted Agreement selected."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from market_core import SettlementStageTable

from arkhai_api_selling.settlement_composition import fulfill_settlement, prepare_settlement
from tests.bundles import accepted_agreement


class _Stage:
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[tuple[str, dict]] = []

    async def prepare(self, **context):
        self.calls.append(("prepare", context))
        return self.name

    async def deliver_prepared(self, prepared, *, mechanism_client):
        self.calls.append(("deliver", {"prepared": prepared, "client": mechanism_client}))
        return self.name


class _Threads:
    def __init__(self, mechanism_thread):
        self._thread = mechanism_thread

    async def load_negotiation_thread_row(self, *, negotiation_id):
        return self._thread


def _thread():
    agreement, raw = accepted_agreement("L-1")
    return {
        "negotiation_id": agreement.negotiation_id,
        "terminal_state": "success",
        "agreement_bytes": raw,
        "buyer_principal": agreement.buyer,
        "seller_principal": agreement.seller,
    }


async def test_preparation_and_delivery_run_on_the_accepted_mechanisms_stage():
    chosen, other = _Stage("chosen"), _Stage("other")
    stages = SettlementStageTable({"opaque.future.v1": chosen, "other.v1": other})
    db = _Threads(_thread())

    assert await prepare_settlement(stages, sqlite_client=db, negotiation_id="neg-accepted") == "chosen"
    prepared = SimpleNamespace(
        agreement_ref="neg-accepted", fulfillment_input=SimpleNamespace(sqlite_client=db)
    )
    assert await fulfill_settlement(stages, prepared, mechanism_client="client") == "chosen"
    assert [call for call, _ in chosen.calls] == ["prepare", "deliver"]
    assert other.calls == []


async def test_an_accepted_mechanism_no_stage_serves_is_refused():
    stages = SettlementStageTable({"other.v1": _Stage("other")})
    with pytest.raises(ValueError, match="unsupported accepted settlement mechanism"):
        await prepare_settlement(stages, sqlite_client=_Threads(_thread()), negotiation_id="neg-accepted")
