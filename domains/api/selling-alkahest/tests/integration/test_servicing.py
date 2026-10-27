"""Obligations accepted under the escrow are serviced after the escrow is disabled, against the real journal."""

from __future__ import annotations

from arkhai_api_selling.settlement_composition import (
    build_settlement_registry,
    servicing_mechanism_clients,
)
from market_alkahest import ALKAHEST_MECHANISM_ID, RECIPIENT_RELEASE
from market_core import SettlementStageTable
from market_settlement_runtime import (
    ConditionOutcome,
    EffectOutcome,
    SettlementRuntime,
    SettlementServicingWorker,
    SettlementSQLiteRepository,
    StatusOutcome,
)

from arkhai_api_selling_alkahest.stage import AlkahestSellerStage
from tests.bundles import ESCROW_UID, EXAMPLE, NEGOTIATION, SELLER, obligation

RESOURCES = {"get_client": lambda _chain: None, "chains": {}, "default_chain": None, "clients": {}}


class ReadyEscrow:
    """An escrow the chain reports funded, whose condition holds and which collects."""

    def __init__(self) -> None:
        self.collected: list[str] = []

    async def get_status(self, _obligation, **kwargs):
        return StatusOutcome(status="ready", mechanism_ref=kwargs["mechanism_ref"])

    async def check(self, _obligation, **_kwargs):
        return ConditionOutcome(decision="ready")

    async def collect(self, _obligation, **kwargs):
        self.collected.append(kwargs.get("mechanism_ref"))
        return EffectOutcome(receipt={"tx": "collected"})


def _stages(escrow: ReadyEscrow) -> SettlementStageTable:
    stage = AlkahestSellerStage(
        EXAMPLE, fulfils_through_capacity=True, release_models=frozenset({RECIPIENT_RELEASE}),
        chains=lambda: {}, seller_wallet=lambda: "", composition=lambda: None,
        sqlite_client=lambda: None, backfill_escrows=None, stage_event=lambda *a, **k: None,
        escrow_client=lambda **_resources: escrow,
    )
    return SettlementStageTable({ALKAHEST_MECHANISM_ID: stage})


def _config(registry, *, enabled: bool | None):
    mapping = {"schema_version": 1, "priority": [ALKAHEST_MECHANISM_ID] if enabled else []}
    if enabled is not None:
        mapping["alkahest"] = {"enabled": enabled}
    return registry.resolve(mapping, role="seller")


async def test_an_accepted_obligation_is_collected_after_its_mechanism_is_disabled(tmp_path):
    escrow = ReadyEscrow()
    stages = _stages(escrow)
    registry = build_settlement_registry(stages)
    repository = SettlementSQLiteRepository(str(tmp_path / "journal.db"))

    accepting = SettlementRuntime(
        repository, servicing_mechanism_clients(stages, registry, _config(registry, enabled=True), RESOURCES)
    )
    record = (await accepting.register_plan(agreement_ref=NEGOTIATION, obligations=[obligation()]))[0]
    await accepting.adopt(record.obligation_ref, local_principal=SELLER.identity, mechanism_ref=ESCROW_UID)
    await accepting.bind_fulfillment(record.obligation_ref, "0xattestation", local_principal=SELLER.identity)

    restarted_clients = servicing_mechanism_clients(
        stages, registry, _config(registry, enabled=False), RESOURCES
    )
    assert set(restarted_clients) == {ALKAHEST_MECHANISM_ID}
    restarted = SettlementRuntime(repository, restarted_clients)
    worker = SettlementServicingWorker(restarted, repository, worker_id="restarted", interval_seconds=30)

    assert await worker.run_once() == 1
    serviced = (await restarted.get_status(NEGOTIATION)).obligations[0]
    assert serviced.collection_state == "succeeded"
    assert escrow.collected == [ESCROW_UID]


def test_an_unconfigured_mechanism_builds_no_servicing_client():
    stages = _stages(ReadyEscrow())
    registry = build_settlement_registry(stages)

    assert servicing_mechanism_clients(stages, registry, _config(registry, enabled=None), RESOURCES) == {}
