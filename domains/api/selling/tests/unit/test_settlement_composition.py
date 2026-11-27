"""The settlement composition's mechanism-neutral parts: clients, servicing, continuations, outcomes."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from market_core import SettlementStageTable
from market_settlement_runtime import FulfillmentOutcome

from arkhai_api_selling.route_services import checked_refund_payload, checked_settle_payload
from arkhai_api_selling.settlement_composition import (
    fulfill_settlement,
    mechanism_servicing,
    persist_settlement_outcome,
    prepare_settlement,
    servicing_mechanism_clients,
)
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
        "our_listing_id": agreement.listing_id,
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


class _ClientStage:
    def __init__(self, client=None, *, fails: bool = False, servicing=None) -> None:
        self._client = client
        self._fails = fails
        self._servicing = servicing

    def client(self, _resources):
        if self._fails:
            raise ValueError("no chain is configured")
        return self._client

    def servicing(self, _settlement_config):
        return self._servicing


def _registry_and_config(sections):
    registrations = [
        SimpleNamespace(mechanism_id=mechanism, config_key=mechanism) for mechanism in sections
    ]
    registry = SimpleNamespace(ordered_registrations=lambda _config, role: registrations)
    config = SimpleNamespace(mechanism_config=lambda key: sections[key])
    return registry, config


def test_every_configured_mechanism_gets_its_servicing_client_whether_or_not_it_publishes():
    stages = SettlementStageTable({
        "enabled.v1": _ClientStage("enabled-client"),
        "disabled.v1": _ClientStage("disabled-client"),
        "unbuildable.v1": _ClientStage(fails=True),
        "unconfigured.v1": _ClientStage("never"),
    })
    registry, config = _registry_and_config({
        "enabled.v1": SimpleNamespace(enabled=True),
        "disabled.v1": SimpleNamespace(enabled=False),
        "unbuildable.v1": SimpleNamespace(enabled=False),
        "unconfigured.v1": None,
    })

    assert servicing_mechanism_clients(stages, registry, config, {}) == {
        "enabled.v1": "enabled-client", "disabled.v1": "disabled-client",
    }


def test_an_enabled_mechanism_whose_client_cannot_be_built_is_refused():
    stages = SettlementStageTable({"enabled.v1": _ClientStage(fails=True)})
    registry, config = _registry_and_config({"enabled.v1": SimpleNamespace(enabled=True)})

    with pytest.raises(ValueError, match="no chain is configured"):
        servicing_mechanism_clients(stages, registry, config, {})


def test_servicing_is_kept_for_each_stage_that_has_one():
    stages = SettlementStageTable({"served.v1": _ClientStage(servicing="kit"), "other.v1": _ClientStage()})

    assert mechanism_servicing(stages, object()) == {"served.v1": "kit"}


async def test_a_deferred_outcome_leaves_the_deal_open():
    class _Recording:
        def __init__(self) -> None:
            self.writes: list[str] = []

        async def save_issuance_progress(self, **_fields):
            self.writes.append("progress")

        async def update_escrow(self, **_fields):
            self.writes.append("escrow")

    db = _Recording()
    prepared = SimpleNamespace(agreement_ref="neg-1", mechanism_ref="ref-1")

    await persist_settlement_outcome(db, prepared, FulfillmentOutcome(status="deferred", reason="later"))
    assert db.writes == []

    await persist_settlement_outcome(db, prepared, FulfillmentOutcome(status="failed", reason="no"))
    assert db.writes == ["progress", "escrow"]


def test_a_stage_payload_that_is_not_the_settle_response_is_refused():
    with pytest.raises(ValueError):
        checked_settle_payload({"negotiation_id": "neg-1"})
    with pytest.raises(ValueError):
        checked_refund_payload({"status": "refunded"})
    refunded = {"negotiation_id": "neg-1", "settlement_ref": "tx-1", "status": "refunded"}
    assert checked_refund_payload(refunded) == refunded
