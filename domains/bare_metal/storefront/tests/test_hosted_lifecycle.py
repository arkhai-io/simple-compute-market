from __future__ import annotations

from types import SimpleNamespace

import pytest
from market_identity import Ed25519Signer
from market_settlement_runtime import SettlementObligationRecord

from arkhai_bare_metal_storefront.hosted_lifecycle import (
    BareMetalHostedLifecycleCallbacks,
    BareMetalHostedLifecycleError,
)
from arkhai_bare_metal_storefront.hosted_routes import lifecycle_domain_callbacks

BUYER = Ed25519Signer(bytes.fromhex("11" * 32)).identity
SELLER = Ed25519Signer(bytes.fromhex("22" * 32)).identity


class FakeRuntime:
    def __init__(self, *, reservation_status: str = "pending") -> None:
        self.fulfillment_reservations = 0
        self.fulfillment_deferrals = 0
        self.reservation_status = reservation_status

    async def reserve_fulfillment(self, *args, **kwargs):
        self.fulfillment_reservations += 1
        return SimpleNamespace(status=self.reservation_status)

    async def defer_fulfillment(self, *args, **kwargs):
        self.fulfillment_deferrals += 1


class NoPhysicalEffects:
    def __init__(self) -> None:
        self.calls = 0

    def __getattr__(self, name):
        self.calls += 1
        raise AssertionError(f"unexpected pre-funding physical call: {name}")


class FakeLifecycleDb:
    def __init__(self, settlement: SettlementObligationRecord) -> None:
        self.settlement = settlement
        self.advances: list[dict] = []
        self.lifecycle = SimpleNamespace(
            accepted_binding=SimpleNamespace(
                obligation_ref=settlement.obligation_ref,
                agreement_ref=settlement.agreement_ref,
                negotiation_id=settlement.agreement_ref,
                option=SimpleNamespace(
                    facts=SimpleNamespace(
                        site_id="site-a",
                        resource_selection="specific",
                        physical_resource_id="resource-a",
                    ),
                ),
            ),
            physical_state="accepted",
            financial_state="pending",
            portable_evidence_ref=None,
            capacity_reservation_id=None,
            settlement_resource_id=None,
            fulfillment_id=None,
        )

    async def load_settlement_obligation(self, obligation_ref):
        assert obligation_ref == self.settlement.obligation_ref
        return self.settlement.model_dump(mode="json")

    async def load_bare_metal_hosted_lifecycle(self, *, obligation_ref):
        assert obligation_ref == self.settlement.obligation_ref
        return self.lifecycle

    async def load_bare_metal_hosted_lifecycle_for_agreement(self, *, agreement_ref):
        assert agreement_ref == self.settlement.agreement_ref
        return self.lifecycle

    async def advance_bare_metal_hosted_lifecycle(self, **fields):
        self.advances.append(fields)
        return self.lifecycle


class FakeSite:
    def __init__(self, reservation=None, *, reservations=None) -> None:
        self.reservation = reservation
        self.reservations = list(reservations or [])

    async def list_reservations(self):
        return list(self.reservations)

    async def get_reservation(self, reservation_id):
        if isinstance(self.reservation, Exception):
            raise self.reservation
        if self.reservation is not None:
            assert self.reservation["capacity_reservation_id"] == reservation_id
        return self.reservation


class FakeCapacityClient:
    def __init__(self, site: FakeSite) -> None:
        self.selected_site = site

    def site(self, site_id):
        assert site_id == "site-a"
        return self.selected_site


class FakeFulfillmentClient:
    def __init__(self, state: str | Exception) -> None:
        self.state = state

    async def get_fulfillment_status(
        self,
        fulfillment_id,
        *,
        capacity_reservation_id,
    ):
        if isinstance(self.state, Exception):
            raise self.state
        return SimpleNamespace(
            fulfillment_id=fulfillment_id,
            capacity_reservation_id=capacity_reservation_id,
            state=self.state,
        )


def _reclaim_guard(
    db: FakeLifecycleDb,
    *,
    reservation,
    fulfillment_state: str = "failed",
):
    if isinstance(reservation, dict):
        reservation = {
            "resource_id": "resource-a",
            **reservation,
        }
    lifecycle = BareMetalHostedLifecycleCallbacks(
        db=db,
        runtime=FakeRuntime(),
        local_principal=SELLER,
        capacity_client=FakeCapacityClient(FakeSite(reservation)),
        fulfillment_client=FakeFulfillmentClient(fulfillment_state),
        publish_evidence=NoPhysicalEffects(),
    )
    callback = lifecycle_domain_callbacks(db=db, lifecycle=lifecycle).before_reclaim
    assert callback is not None
    return callback


def record(*, mechanism: str, mechanism_status: str) -> SettlementObligationRecord:
    obligation = {
        "payer": "buyer",
        "claimant": "seller",
        "payer_principal": BUYER.model_dump(mode="json"),
        "claimant_principal": SELLER.model_dump(mode="json"),
        "amount": 100,
        "asset": "usd",
        "expiration_unix": 2_000_000_000,
        "conditions": [],
        "mechanism": mechanism,
        "params": {},
    }
    return SettlementObligationRecord(
        obligation_ref="a" * 64,
        agreement_ref="agreement-a",
        obligation_index=0,
        obligation_hash="b" * 64,
        obligation=obligation,
        payer_principal=BUYER,
        claimant_principal=SELLER,
        mechanism_status=mechanism_status,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    ["pending", "awaiting_payment", "requires_action", "manual_required"],
)
async def test_nonfunded_state_performs_no_physical_or_fulfillment_mutation(
    status,
) -> None:
    runtime = FakeRuntime()
    physical = NoPhysicalEffects()
    callbacks = BareMetalHostedLifecycleCallbacks(
        db=physical,
        runtime=runtime,
        local_principal=SELLER,
        capacity_client=physical,
        fulfillment_client=physical,
        publish_evidence=physical,
    )
    pending = record(mechanism="fiat.stripe.v1", mechanism_status=status)

    returned = await callbacks.fulfill(pending, "worker-a")

    assert returned is pending
    assert runtime.fulfillment_reservations == 0
    assert physical.calls == 0


@pytest.mark.asyncio
async def test_hosted_callback_never_falls_back_from_alkahest() -> None:
    runtime = FakeRuntime()
    physical = NoPhysicalEffects()
    callbacks = BareMetalHostedLifecycleCallbacks(
        db=physical,
        runtime=runtime,
        local_principal=SELLER,
        capacity_client=physical,
        fulfillment_client=physical,
        publish_evidence=physical,
    )

    with pytest.raises(BareMetalHostedLifecycleError, match="another settlement"):
        await callbacks.fulfill(
            record(mechanism="alkahest.v1", mechanism_status="ready"),
            "worker-a",
        )

    assert runtime.fulfillment_reservations == 0
    assert physical.calls == 0


@pytest.mark.asyncio
async def test_busy_fulfillment_reservation_resumes_without_duplicate_physical_effect() -> (
    None
):
    funded = record(mechanism="fiat.stripe.v1", mechanism_status="ready")
    db = FakeLifecycleDb(funded)
    runtime = FakeRuntime(reservation_status="busy")
    physical = NoPhysicalEffects()
    callbacks = BareMetalHostedLifecycleCallbacks(
        db=db,
        runtime=runtime,
        local_principal=SELLER,
        capacity_client=physical,
        fulfillment_client=physical,
        publish_evidence=physical,
    )

    resumed = await callbacks.fulfill(funded, "worker-b")

    assert resumed == funded
    assert runtime.fulfillment_reservations == 1
    assert physical.calls == 0


@pytest.mark.asyncio
async def test_pending_physical_fulfillment_defers_poll_without_error(
    monkeypatch,
) -> None:
    funded = record(mechanism="fiat.stripe.v1", mechanism_status="ready")
    db = FakeLifecycleDb(funded)
    runtime = FakeRuntime()
    physical = NoPhysicalEffects()
    callbacks = BareMetalHostedLifecycleCallbacks(
        db=db,
        runtime=runtime,
        local_principal=SELLER,
        capacity_client=physical,
        fulfillment_client=physical,
        publish_evidence=physical,
    )

    async def pending_access(*args, **kwargs):
        return SimpleNamespace(public_result=None)

    monkeypatch.setattr(
        BareMetalHostedLifecycleCallbacks,
        "_ensure_access_ready",
        pending_access,
    )

    returned = await callbacks.fulfill(funded, "worker-a")

    assert returned == funded
    assert runtime.fulfillment_reservations == 1
    assert runtime.fulfillment_deferrals == 1
    assert physical.calls == 0


@pytest.mark.asyncio
async def test_collection_unknown_freezes_cleanup_and_enters_manual_review() -> None:
    uncertain = record(
        mechanism="fiat.stripe.v1",
        mechanism_status="ready",
    ).model_copy(update={"collection_state": "in_progress"})
    db = FakeLifecycleDb(uncertain)
    physical = NoPhysicalEffects()
    callbacks = BareMetalHostedLifecycleCallbacks(
        db=db,
        runtime=FakeRuntime(),
        local_principal=SELLER,
        capacity_client=physical,
        fulfillment_client=physical,
        publish_evidence=physical,
    )

    await callbacks.reconcile_terminal(uncertain, "manual_required", "unknown")

    assert db.advances[-1]["financial_state"] == "collection_unknown"
    assert db.advances[-1]["recovery_state"] == "manual_review"
    assert physical.calls == 0


@pytest.mark.asyncio
async def test_precollection_funding_return_blocks_collection_without_physical_work() -> (
    None
):
    returned = record(
        mechanism="fiat.stripe.v1",
        mechanism_status="failed",
    )
    db = FakeLifecycleDb(returned)
    physical = NoPhysicalEffects()
    callbacks = BareMetalHostedLifecycleCallbacks(
        db=db,
        runtime=FakeRuntime(),
        local_principal=SELLER,
        capacity_client=physical,
        fulfillment_client=physical,
        publish_evidence=physical,
    )

    await callbacks.reconcile_terminal(returned, "failed", "funding returned")

    assert db.advances[-1]["financial_state"] == "collection_blocked"
    assert db.advances[-1]["recovery_state"] == "funding_returned"
    assert physical.calls == 0


@pytest.mark.asyncio
async def test_postcollection_loss_is_incident_only_and_never_reclaims() -> None:
    loss = record(
        mechanism="fiat.stripe.v1",
        mechanism_status="manual_required",
    ).model_copy(update={"collection_state": "succeeded"})
    db = FakeLifecycleDb(loss)
    physical = NoPhysicalEffects()
    callbacks = BareMetalHostedLifecycleCallbacks(
        db=db,
        runtime=FakeRuntime(),
        local_principal=SELLER,
        capacity_client=physical,
        fulfillment_client=physical,
        publish_evidence=physical,
    )

    await callbacks.reconcile_terminal(loss, "manual_required", "late loss")

    assert db.advances[-1]["financial_state"] == "collected"
    assert db.advances[-1]["recovery_state"] == "loss_manual"
    assert all(advance.get("financial_state") != "reclaimed" for advance in db.advances)
    assert physical.calls == 0


@pytest.mark.asyncio
async def test_reclaim_allows_authoritative_terminal_no_effect_state() -> None:
    settlement = record(mechanism="fiat.stripe.v1", mechanism_status="failed")
    db = FakeLifecycleDb(settlement)
    db.lifecycle.physical_state = "physical_failed"
    db.lifecycle.capacity_reservation_id = "reservation-a"
    db.lifecycle.settlement_resource_id = "settlement-resource-a"
    db.lifecycle.fulfillment_id = "fulfillment-a"
    reservation = {
        "capacity_reservation_id": "reservation-a",
        "deal_ref": {
            "negotiation_id": settlement.agreement_ref,
            "hosted_obligation_ref": settlement.obligation_ref,
        },
        "state": "released",
    }
    guard = _reclaim_guard(
        db,
        reservation=reservation,
        fulfillment_state="failed",
    )

    returned = await guard(settlement, "worker-a")

    assert returned is settlement


@pytest.mark.asyncio
async def test_reclaim_blocks_active_selected_site_reservation() -> None:
    settlement = record(mechanism="fiat.stripe.v1", mechanism_status="failed")
    db = FakeLifecycleDb(settlement)
    db.lifecycle.physical_state = "capacity_committed"
    db.lifecycle.capacity_reservation_id = "reservation-a"
    reservation = {
        "capacity_reservation_id": "reservation-a",
        "deal_ref": {
            "negotiation_id": settlement.agreement_ref,
            "hosted_obligation_ref": settlement.obligation_ref,
        },
        "state": "leased",
    }
    guard = _reclaim_guard(db, reservation=reservation)

    with pytest.raises(ValueError, match="may still have a physical effect"):
        await guard(settlement, "worker-a")


@pytest.mark.asyncio
@pytest.mark.parametrize("remote_state", ["active", "dispatching", "unknown"])
async def test_reclaim_blocks_active_or_unknown_fulfillment_aggregate(
    remote_state,
) -> None:
    settlement = record(mechanism="fiat.stripe.v1", mechanism_status="failed")
    db = FakeLifecycleDb(settlement)
    db.lifecycle.physical_state = "fulfillment_pending"
    db.lifecycle.capacity_reservation_id = "reservation-a"
    db.lifecycle.settlement_resource_id = "settlement-resource-a"
    db.lifecycle.fulfillment_id = "fulfillment-a"
    reservation = {
        "capacity_reservation_id": "reservation-a",
        "deal_ref": {
            "negotiation_id": settlement.agreement_ref,
            "hosted_obligation_ref": settlement.obligation_ref,
        },
        "state": "released",
    }
    guard = _reclaim_guard(
        db,
        reservation=reservation,
        fulfillment_state=remote_state,
    )

    with pytest.raises(ValueError, match="may still have a physical effect"):
        await guard(settlement, "worker-a")


@pytest.mark.asyncio
async def test_reclaim_blocks_crash_after_remote_fulfillment_begin() -> None:
    settlement = record(mechanism="fiat.stripe.v1", mechanism_status="failed")
    db = FakeLifecycleDb(settlement)
    db.lifecycle.physical_state = "scheduled"
    db.lifecycle.capacity_reservation_id = "reservation-a"
    db.lifecycle.settlement_resource_id = "settlement-resource-a"
    reservation = {
        "capacity_reservation_id": "reservation-a",
        "deal_ref": {
            "negotiation_id": settlement.agreement_ref,
            "hosted_obligation_ref": settlement.obligation_ref,
        },
        "state": "released",
    }
    guard = _reclaim_guard(db, reservation=reservation)

    with pytest.raises(ValueError, match="identity is missing after scheduling"):
        await guard(settlement, "worker-a")


@pytest.mark.asyncio
async def test_reclaim_allows_authoritative_absence_before_reservation() -> None:
    settlement = record(mechanism="fiat.stripe.v1", mechanism_status="failed")
    db = FakeLifecycleDb(settlement)
    guard = _reclaim_guard(db, reservation=None)

    returned = await guard(settlement, "worker-a")

    assert returned is settlement


@pytest.mark.asyncio
async def test_reclaim_blocks_missing_or_inconsistent_reservation() -> None:
    settlement = record(mechanism="fiat.stripe.v1", mechanism_status="failed")
    db = FakeLifecycleDb(settlement)
    db.lifecycle.physical_state = "capacity_reserved"
    db.lifecycle.capacity_reservation_id = "reservation-a"
    missing = _reclaim_guard(db, reservation=None)

    with pytest.raises(ValueError, match="reservation is missing"):
        await missing(settlement, "worker-a")

    inconsistent = _reclaim_guard(
        db,
        reservation={
            "capacity_reservation_id": "reservation-a",
            "deal_ref": {"negotiation_id": "another-negotiation"},
            "state": "released",
        },
    )
    with pytest.raises(ValueError, match="identity is inconsistent"):
        await inconsistent(settlement, "worker-a")


@pytest.mark.asyncio
async def test_reclaim_blocks_when_selected_site_is_unreachable() -> None:
    settlement = record(mechanism="fiat.stripe.v1", mechanism_status="failed")
    db = FakeLifecycleDb(settlement)
    db.lifecycle.physical_state = "capacity_reserved"
    db.lifecycle.capacity_reservation_id = "reservation-a"
    guard = _reclaim_guard(
        db,
        reservation=RuntimeError("site unavailable"),
    )

    with pytest.raises(RuntimeError, match="site unavailable"):
        await guard(settlement, "worker-a")


@pytest.mark.asyncio
async def test_reclaim_blocks_when_fulfillment_authority_is_unreachable() -> None:
    settlement = record(mechanism="fiat.stripe.v1", mechanism_status="failed")
    db = FakeLifecycleDb(settlement)
    db.lifecycle.physical_state = "fulfillment_pending"
    db.lifecycle.capacity_reservation_id = "reservation-a"
    db.lifecycle.settlement_resource_id = "settlement-resource-a"
    db.lifecycle.fulfillment_id = "fulfillment-a"
    reservation = {
        "capacity_reservation_id": "reservation-a",
        "deal_ref": {
            "negotiation_id": settlement.agreement_ref,
            "hosted_obligation_ref": settlement.obligation_ref,
        },
        "state": "released",
    }
    guard = _reclaim_guard(
        db,
        reservation=reservation,
        fulfillment_state=RuntimeError("fulfillment unavailable"),
    )

    with pytest.raises(RuntimeError, match="fulfillment unavailable"):
        await guard(settlement, "worker-a")
