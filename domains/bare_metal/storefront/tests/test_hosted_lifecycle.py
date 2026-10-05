from __future__ import annotations

from types import SimpleNamespace

import pytest
from market_identity import Ed25519Signer
from market_settlement_runtime import SettlementObligationRecord
from arkhai_bare_metal import bare_metal_digest
from market_core import VersionedEnvelope

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
    def __init__(self, reservation=None, *, reservations=None, release=None) -> None:
        self.reservation = reservation
        self.reservations = list(reservations or [])
        #: What the site answers a release with: the released reservation, or
        #: ``None`` when its release guard refuses.
        self.release_answer = release
        self.released: list[str] = []

    async def release(self, *, capacity_reservation_id, deal_ref=None):
        self.released.append(capacity_reservation_id)
        return self.release_answer

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


def _teardown_without_fulfillment(release_answer):
    """A reclaimed deal whose reservation no fulfillment ever began on."""
    settlement = record(mechanism="fiat.stripe.v1", mechanism_status="reclaimed")
    db = FakeLifecycleDb(settlement)
    db.lifecycle.financial_state = "reclaimed"
    db.lifecycle.capacity_reservation_id = "reservation-a"
    site = FakeSite(release=release_answer)
    lifecycle = BareMetalHostedLifecycleCallbacks(
        db=db,
        runtime=FakeRuntime(),
        local_principal=SELLER,
        capacity_client=FakeCapacityClient(site),
        fulfillment_client=FakeFulfillmentClient("assigned"),
        publish_evidence=NoPhysicalEffects(),
    )
    lifecycle.capacity_client.reservation_sites = {"reservation-a": "site-a"}
    return settlement, db, site, lifecycle


@pytest.mark.asyncio
async def test_a_reservation_no_fulfillment_began_on_is_released_at_teardown() -> None:
    settlement, db, site, lifecycle = _teardown_without_fulfillment(
        {"capacity_reservation_id": "reservation-a", "state": "released"}
    )

    await lifecycle.teardown_lease(settlement.obligation_ref)

    assert site.released == ["reservation-a"]
    assert {"obligation_ref": settlement.obligation_ref, "teardown_state": "released"} in (
        db.advances
    )


@pytest.mark.asyncio
async def test_a_release_the_site_refuses_leaves_the_lease_unreleased() -> None:
    """The site frees capacity only when fulfillment proves nothing was
    dispatched; a refusal means one began that this lifecycle never recorded,
    so teardown is not recorded as done and is retried."""
    settlement, db, site, lifecycle = _teardown_without_fulfillment(None)

    with pytest.raises(BareMetalHostedLifecycleError, match="refused to release"):
        await lifecycle.teardown_lease(settlement.obligation_ref)

    assert site.released == ["reservation-a"]
    assert not any(advance.get("teardown_state") == "released" for advance in db.advances)


_KEY = "ssh-ed25519 AAAA tenant-a"


class _AccessReadyDb(FakeLifecycleDb):
    """A deal whose fulfillment was begun and is about to be reported active."""

    def __init__(self, settlement: SettlementObligationRecord) -> None:
        super().__init__(settlement)
        self.lifecycle.accepted_binding.buyer_principal = BUYER
        self.lifecycle.accepted_binding.seller_principal = SELLER
        self.lifecycle.accepted_binding.claimant_principal = SELLER
        self.lifecycle.accepted_binding.listing_id = "listing-a"
        self.lifecycle.accepted_binding.access_public_digest = bare_metal_digest(
            {"ssh_public_key": _KEY}
        )
        self.lifecycle.accepted_binding.option.facts.resource_selection = "fungible"
        self.lifecycle.accepted_binding.option.facts.physical_resource_id = None
        self.lifecycle.accepted_binding.option.facts.pool_id = "pool-a"
        self.lifecycle.accepted_binding.option.facts.offering_mode = "bare_metal"
        self.lifecycle.accepted_binding.option.facts.access_method = "ssh"
        self.lifecycle.physical_state = "fulfillment_pending"
        self.lifecycle.capacity_reservation_id = "reservation-a"
        self.lifecycle.settlement_resource_id = "settlement-resource-a"
        self.lifecycle.fulfillment_id = "fulfillment-a"
        self.lifecycle.fulfillment_identity = "fulfillment-identity-a"
        self.lifecycle.public_result = None

    async def load_bare_metal_fulfillment_context(self, *, negotiation_id):
        return {
            "terminal_state": "success",
            "buyer_scheme": BUYER.scheme.value,
            "buyer_identifier": BUYER.identifier,
            "seller_scheme": SELLER.scheme.value,
            "seller_identifier": SELLER.identifier,
            "site_id": "site-a",
            "pool_id": "pool-a",
            "claimed_attributes": {"gpu_model": "H200"},
        }

    async def load_bare_metal_terms(self, *, negotiation_id):
        return SimpleNamespace(
            access_method="ssh", ssh_public_key=_KEY, duration_seconds=3600, access_ref=None
        )

    async def advance_bare_metal_hosted_lifecycle(self, **fields):
        self.advances.append(fields)
        for name, value in fields.items():
            if name != "obligation_ref":
                setattr(self.lifecycle, name, value)
        return self.lifecycle

    async def ensure_bare_metal_fulfillment_lifecycle(self, **fields):
        return None

    async def update_bare_metal_fulfillment_lifecycle(self, **fields):
        return None


class _ActiveFulfillment:
    """Reports the grant done on machine-1, and records lease registrations
    with the reservation's state at the time."""

    def __init__(self, db: _AccessReadyDb) -> None:
        self.db = db
        self.registrations: list[tuple[object, str]] = []

    async def get_fulfillment_status(self, fulfillment_id, *, capacity_reservation_id):
        return SimpleNamespace(state="active", failure_reason=None, failure_message=None)

    async def get_fulfillment_result(self, fulfillment_id, *, capacity_reservation_id):
        return VersionedEnvelope(
            kind="fulfillment.result.v1",
            schema_version=1,
            payload={
                "state": "active",
                "domain_result": {
                    "kind": "bare_metal.fulfillment.result.v1",
                    "schema_version": 2,
                    "payload": {
                        "kind": "bare_metal.v2",
                        "action": "node_grant_access",
                        "status": "success",
                        "host_id": "machine-1",
                        "physical_host_id": "host-1",
                        "access_grant_ref": "grant-a",
                        "lease_expires_at": "2099-01-01T01:00:00+00:00",
                        "timestamp": "2099-01-01T00:00:05+00:00",
                    },
                },
            },
        )

    async def register_lease(self, registration):
        self.registrations.append((registration, self.db.lifecycle.physical_state))
        return registration


@pytest.mark.asyncio
async def test_access_readiness_registers_the_lease_on_the_family_surface() -> None:
    """Once the grant is reported active, the lease is registered with the
    machine as its target before the deal is recorded access-ready, so a
    failed registration is retried with the rest of the step. It names no
    window: the committed window is the site's."""
    settlement = record(mechanism="fiat.stripe.v1", mechanism_status="succeeded")
    db = _AccessReadyDb(settlement)
    fulfillment = _ActiveFulfillment(db)
    capacity = FakeCapacityClient(FakeSite())
    capacity.reservation_sites = {}
    lifecycle = BareMetalHostedLifecycleCallbacks(
        db=db,
        runtime=FakeRuntime(),
        local_principal=SELLER,
        capacity_client=capacity,
        fulfillment_client=fulfillment,
        publish_evidence=NoPhysicalEffects(),
    )

    ready = await lifecycle._ensure_access_ready(settlement)

    ((registration, state_at_registration),) = fulfillment.registrations
    assert registration.capacity_reservation_id == "reservation-a"
    assert registration.executor_target == "machine-1"
    assert (registration.lease_start_utc, registration.lease_end_utc) == (None, None)
    assert registration.deal_ref == {
        "negotiation_id": settlement.agreement_ref,
        "hosted_obligation_ref": settlement.obligation_ref,
    }
    assert state_at_registration == "fulfillment_pending"
    assert ready.physical_state == "access_ready"
