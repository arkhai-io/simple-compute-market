"""The ``delivery-recovery`` loop re-drives a payment deal waiting for its start.

Application integration: the served VM storefront and its typed clients over
SQLite (``tests.recurring_world``), with the payments service the in-process
engine behind ``PaymentsClient``. The buyer negotiates the on-demand option with
an Agreement start at wall time and settles while the deal lifecycle's clock
runs an hour behind it, so the deal is committed and waits for its start. With
the storefront's loops held, the clock is brought to the start and
``delivery-recovery`` is stepped once through the typed admin client; its
re-drive reaches the world's site and provisioning fakes through the deal
lifecycle's capacity runtime and fulfillment client, and re-checks the deal
through the composition's real payments stage, whose re-checks are recorded.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from datetime import datetime, timedelta, timezone

from arkhai_vms import make_vm_provision_terms
from market_arkhai_payments import PaymentSellerStage, PaymentSettlementData

import market_storefront.container as container
from tests.integration.test_payment_settlement import IMPOSTOR
from tests.integration.test_rate_delivery import PAYER, _on_demand, _published, approve
from tests.recurring_world import MECHANISM, recurring_world, settlement

_RECOVERY_LOGGER = "market_storefront.services.fulfillment_resume_runtime"


def _row(db, negotiation_id: str) -> dict:
    with sqlite3.connect(db.db_path) as conn:
        conn.row_factory = sqlite3.Row
        return dict(conn.execute(
            "SELECT * FROM vm_delivery_records WHERE negotiation_id=?", (negotiation_id,),
        ).fetchone())


class _RecordedStage:
    """A seller stage as composed, its evidence re-checks recorded."""

    def __init__(self, stage, rechecks: list[str]) -> None:
        self._stage = stage
        self._rechecks = rechecks

    async def recover_evidence(self, *, evidence, **kwargs):
        self._rechecks.append(evidence.negotiation_id)
        return await self._stage.recover_evidence(evidence=evidence, **kwargs)

    def __getattr__(self, name):
        return getattr(self._stage, name)


class _Recomposed:
    """The resolved settlement composition with some of its attributes replaced.

    The composition is frozen and derives its seller stages from its domain and
    its payments stage from its configuration, so a test stands this in front of
    it rather than rebuilding either.
    """

    def __init__(self, composition, **replaced) -> None:
        self._composition = composition
        self.__dict__.update(replaced)

    def __getattr__(self, name):
        return getattr(self._composition, name)


async def _waiting_deal(world, settled, offset: list[int]) -> tuple[str, list[str]]:
    """A deal negotiated to start at wall time and settled while the lifecycle's
    clock runs ``offset`` seconds behind it, committed and waiting for its start.

    ``offset`` is then set to zero, bringing the deal to its start, and the
    composition's seller stages are recorded, so the returned list holds the
    re-checks the step makes. The site stamps activation in wall time, so the
    start is never after it.
    """
    listing = await _published(world)
    start = datetime.now(timezone.utc).replace(microsecond=0)
    reply = await world.app.buyer.negotiate_new(
        listing_id=listing["listing_id"],
        # One period at the clause's 2.5 an hour, in base units.
        initial_amount=625_000,
        provision_terms=make_vm_provision_terms(
            duration_seconds=3600, ssh_public_key="ssh-ed25519 test",
            start_utc=start.isoformat().replace("+00:00", "Z"),
        ).model_dump(mode="json"),
        settlement_selection={
            "option_id": _on_demand(listing)["option_id"], "expiration_unix": 2_147_483_647,
            "settlement": {"schema": MECHANISM, "payer_account": PAYER},
        },
        selection_only=True,
    )
    assert reply["action"] == "accept", reply
    negotiation_id = reply["agreement"]["negotiation_id"]
    thread = await world.app.db.load_negotiation_thread_row(negotiation_id=negotiation_id)
    raw = thread["settlement_data"]
    approve(settled, PaymentSettlementData.parse(json.loads(raw) if isinstance(raw, str) else raw))
    await world.app.buyer.settle_agreement(negotiation_id)
    await settled.delivered(negotiation_id)

    row = _row(world.app.db, negotiation_id)
    assert row["status"] == "provisioning" and row["capacity_reservation_id"] is not None
    assert settled.site.rows[row["capacity_reservation_id"]]["state"] == "leased"
    assert settled.provisioning.begins == [] and row["processing_owner"] is None

    rechecks: list[str] = []
    composition = container.resolved_settlement_composition
    container.resolved_settlement_composition = _Recomposed(composition, seller_stages={
        mechanism: _RecordedStage(stage, rechecks) for mechanism, stage in composition.seller_stages.items()
    })
    offset[0] = 0
    return negotiation_id, rechecks


def _offset_clock(offset: list[int]):
    return lambda: int(time.time()) + offset[0]


async def test_a_deal_waiting_for_its_start_is_claimed_re_checked_and_driven_at_its_start(tmp_path):
    offset = [-3600]
    async with recurring_world(tmp_path) as world, settlement(world, clock=_offset_clock(offset)) as settled:
        await world.app.client.admin_pause_lifecycle_loops()
        negotiation_id, rechecks = await _waiting_deal(world, settled, offset)
        owners_at_begin: list[str | None] = []
        begin = settled.provisioning.begin_fulfillment

        async def observed_begin(body, *args, **kwargs):
            owners_at_begin.append(_row(world.app.db, negotiation_id)["processing_owner"])
            return await begin(body, *args, **kwargs)

        settled.provisioning.begin_fulfillment = observed_begin

        report = await world.app.client.admin_run_lifecycle_cycle("delivery-recovery")
        row = _row(world.app.db, negotiation_id)
        activated_at = settled.site.rows[row["capacity_reservation_id"]]["activated_at_utc"]

    assert report["redriven"] == 1
    assert rechecks == [negotiation_id]
    # The step held the deal's claim while it drove, and released it after.
    [owner] = owners_at_begin
    assert owner is not None and owner.startswith("delivery-recovery:")
    assert row["processing_owner"] is None
    assert row["status"] == "ready"
    assert activated_at is not None


async def test_a_deal_another_worker_holds_is_skipped(tmp_path):
    offset = [-3600]
    async with recurring_world(tmp_path) as world, settlement(world, clock=_offset_clock(offset)) as settled:
        await world.app.client.admin_pause_lifecycle_loops()
        negotiation_id, rechecks = await _waiting_deal(world, settled, offset)
        assert await world.app.db.claim_vm_delivery(
            negotiation_id=negotiation_id, owner="another-worker",
            lease_until=(datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
        )

        report = await world.app.client.admin_run_lifecycle_cycle("delivery-recovery")
        row = _row(world.app.db, negotiation_id)

    assert report["redriven"] == 0
    assert rechecks == []
    assert settled.provisioning.begins == []
    assert row["processing_owner"] == "another-worker"
    assert row["status"] == "provisioning"


async def test_a_deal_whose_evidence_fails_its_re_check_is_not_driven(tmp_path, caplog):
    offset = [-3600]
    async with recurring_world(tmp_path) as world, settlement(world, clock=_offset_clock(offset)) as settled:
        await world.app.client.admin_pause_lifecycle_loops()
        negotiation_id, rechecks = await _waiting_deal(world, settled, offset)
        # The receipt identity pin has moved: the stored receipt does not verify
        # under it. The stage differs from the composed one only in that pin.
        composed = container.resolved_settlement_composition
        stage = composed.arkhai_payments_stage
        container.resolved_settlement_composition = _Recomposed(
            composed, arkhai_payments_stage=PaymentSellerStage(
                stage.config.model_copy(update={"service_identity": IMPOSTOR.identity}),
                client_for_owner=settled.payments, rate_servicing=stage.rate_servicing,
            ),
        )

        with caplog.at_level(logging.WARNING):
            report = await world.app.client.admin_run_lifecycle_cycle("delivery-recovery")
        row = _row(world.app.db, negotiation_id)

    assert report["redriven"] == 0
    assert rechecks == [negotiation_id]
    assert [record.getMessage() for record in caplog.records if record.name == _RECOVERY_LOGGER] == [
        f"[DELIVERY] {negotiation_id} does not re-check for recovery: "
        "payment evidence does not match accepted Agreement",
    ]
    assert not [record for record in caplog.records if record.name == "compute_delivery.recovery"]
    assert settled.provisioning.begins == []
    assert row["processing_owner"] is None
    assert row["status"] == "provisioning"
