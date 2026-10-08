"""Bare-metal agreement settlement and refunds through the canonical typed client.

The storefront app, its lifespan and authentication, its negotiation runtime, and
SQLite persistence are real; each deal is opened through ``negotiate_new`` with a
payment selection, exactly as a buyer opens one. Site capacity and provisioning
are in-memory authorities, and the payments service is the kit's fake injected at
``PaymentsClient`` through the settlement composition. Settlement must start
fulfillment itself once the receipt verifies.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from types import SimpleNamespace

import httpx
import pytest
from arkhai_bare_metal.fixtures.listing import LISTING_HARDWARE
from market_arkhai_payments import PaymentSettlementData
from market_arkhai_payments.fixtures import FakePaymentsClient, build_signed_receipt
from market_core.schemas import RateValue, SettlementOption, derive_settlement_option_id
from market_identity import Ed25519Signer, TrustedIdentitySet
from source_sites import listing_source_projection
from storefront_client import StorefrontClient, StorefrontClientError

from arkhai_bare_metal_storefront.domain_runtime import get_market_domain_contract
from arkhai_bare_metal_storefront.runtime import BareMetalStorefrontRuntime
from arkhai_bare_metal_storefront.server import (
    build_bare_metal_storefront_app,
    build_bare_metal_storefront_registry,
)
from arkhai_bare_metal_storefront.settlement_composition import (
    BareMetalStorefrontSettlementComposition,
)
from arkhai_bare_metal_storefront.sqlite_client import SQLiteClient

PAYER = "11111111-1111-4111-8111-111111111111"
PAYEE = "22222222-2222-4222-8222-222222222222"
DISPUTE = "33333333-3333-4333-8333-333333333333"
SERVICE = Ed25519Signer(b"\x07" * 32)
IMPOSTOR = Ed25519Signer(b"\x08" * 32)
BUYER = Ed25519Signer(b"\x31" * 32)
SELLER = Ed25519Signer(b"\x32" * 32)
ADMIN = Ed25519Signer(b"\x33" * 32)
LISTING = "bm-payment-listing"
# The source-sites fixture's identities, so the listing source check matches.
SITE, POOL, RESOURCE = "site-a", "pool-a", "resource-1"
HOST, PHYSICAL_HOST = "machine-1", "physical-host-1"
SSH_KEY = "ssh-ed25519 buyer"


class Capacity:
    """The selected site: it answers the listing source check and reservations."""

    def __init__(self) -> None:
        self.reservation_sites: dict[str, str] = {}

    def site(self, site_id):
        assert site_id == SITE
        return self

    async def resource_pool_projection(self):
        return listing_source_projection()

    async def list_reservations(self):
        return []

    async def reserve(self, **request):
        self.reservation_sites["reservation-pay"] = request["site"]
        return {"capacity_reservation_id": "reservation-pay", "site": request["site"]}

    async def commit(self, **request):
        """Write-once, as the site's: the first commit's lease window is kept."""
        self.window = getattr(self, "window", None) or (
            request["lease_start_utc"],
            request["lease_end_utc"],
        )
        return {
            "capacity_reservation_id": request["capacity_reservation_id"],
            "state": "leased",
            "lease_start_utc": self.window[0],
            "lease_end_utc": self.window[1],
            "site": request["site_id"],
        }


class Provisioning:
    def __init__(self) -> None:
        self.begin_calls: list = []
        # When set, dispatch pauses after delivery started until ``release`` is set.
        self.started: asyncio.Event | None = None
        self.release: asyncio.Event | None = None

    async def schedule_resource(self, request):
        return SimpleNamespace(
            settlement_resource_id=RESOURCE,
            pool_id=POOL,
            resource_kind="compute.bare-metal",
            provider="bare_metal.ansible",
            attributes={
                "bare_metal_publication": {
                    "enabled": True,
                    "host_id": HOST,
                    "physical_host_id": PHYSICAL_HOST,
                }
            },
        )

    async def begin_fulfillment(self, request):
        self.begin_calls.append(request)
        if self.started is not None and self.release is not None:
            self.started.set()
            await self.release.wait()
        return SimpleNamespace(
            fulfillment_id="fulfillment-pay",
            capacity_reservation_id="reservation-pay",
            state="dispatch_pending",
        )


def _option() -> SettlementOption:
    params = {"payee_account": PAYEE, "asset": "USD/2", "window": "P7D", "deposit_agreement": False}
    rates = [RateValue(field="amount", per="hour", value=100)]
    return SettlementOption(
        option_id=derive_settlement_option_id(
            mechanism="arkhai.payments.v1", asset="USD/2", rates=rates, params=params
        ),
        mechanism="arkhai.payments.v1",
        asset="USD/2",
        rates=rates,
        params=params,
    )


def _composition(
    payments: FakePaymentsClient, *, enabled: bool = True
) -> BareMetalStorefrontSettlementComposition:
    return BareMetalStorefrontSettlementComposition.from_raw_config(
        {
            # Disabled means no longer published for new deals; the servicing
            # fields stay, so accepted deals keep settling and refunding.
            "priority": ["arkhai.payments.v1"] if enabled else [],
            "arkhai_payments": {
                "enabled": enabled,
                "service_url": "http://127.0.0.1:9",
                "service_identity": SERVICE.identity.model_dump(mode="json"),
                "fee_bps": 250,
                "dispute_authority": DISPUTE,
                "development_auth": True,
            },
        },
        payments_client_for_owner=payments,
    )


async def _publish(runtime: BareMetalStorefrontRuntime) -> None:
    await runtime.db.upsert_bare_metal_listing(
        listing_id=LISTING,
        status="open",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        seller_principal=SELLER.identity,
        storefront_url="http://test",
        site_id=SITE,
        pool_id=POOL,
        physical_resource_id=RESOURCE,
        listing={
            "capacity_backing": "backed",
            **LISTING_HARDWARE,
            "kind": "bare_metal.v2",
            "host_id": HOST,
            "physical_host_id": PHYSICAL_HOST,
            "access_methods": ["ssh"],
        },
        accepted_escrows=[],
        settlement_options=[_option().model_dump(mode="json")],
    )


async def _open(buyer: StorefrontClient) -> dict:
    """Open the deal as a buyer does: an exact payment selection, accepted at round zero."""
    option = _option()
    return await buyer.negotiate_new(
        listing_id=LISTING,
        initial_amount=None,
        provision_terms={
            "kind": "bare_metal.v2",
            "version": 1,
            "payload": {
                "duration_seconds": 3600,
                "access_method": "ssh",
                "ssh_public_key": SSH_KEY,
            },
        },
        settlement_selection={
            "mechanism": option.mechanism,
            "option_id": option.option_id,
            "expiration_unix": 1_900_000_000,
            "params": {"payer_account": PAYER},
        },
        selection_only=True,
    )


class Harness(SimpleNamespace):
    def serve(self, signer=SERVICE):
        self.payments.serve(build_signed_receipt(signer=signer, mandate=self.data.mandate))

    async def settle(self):
        return await self.buyer.settle_agreement(self.negotiation_id)

    async def refund(self):
        return await self.seller.refund_settlement(self.negotiation_id)


@pytest.fixture
def enabled() -> bool:
    return True


@pytest.fixture
async def harness(tmp_path, enabled):
    payments = FakePaymentsClient()
    domain = get_market_domain_contract()
    provisioning = Provisioning()
    runtime = BareMetalStorefrontRuntime(
        db=SQLiteClient(str(tmp_path / "storefront.db"), domain=domain),
        domain=domain,
        seller_principal=SELLER.identity,
        admin_principals=TrustedIdentitySet(identities=(ADMIN.identity,)),
        storefront_url="http://test",
        marketplace_signer=SELLER,
        settlement_composition=_composition(payments),
        capacity_client=Capacity(),
        fulfillment_client=provisioning,
    )
    await _publish(runtime)
    app = build_bare_metal_storefront_app(
        registry=build_bare_metal_storefront_registry(domain=domain), runtime=runtime
    )
    publishers = TrustedIdentitySet(identities=(SELLER.identity,))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with (
            StorefrontClient(
                "http://test", signer=BUYER, caller_role="buyer",
                expected_publishers=publishers, transport=transport,
            ) as buyer,
            StorefrontClient(
                "http://test", signer=SELLER, caller_role="seller",
                expected_publishers=publishers, transport=transport,
            ) as seller,
        ):
            opened = await _open(buyer)
            if not enabled:
                # Payments stops being offered for new deals; this one stays serviced.
                disabled = _composition(payments, enabled=False)
                object.__setattr__(runtime, "settlement_composition", disabled)
            yield Harness(
                app=app,
                runtime=runtime,
                payments=payments,
                provisioning=provisioning,
                opened=opened,
                negotiation_id=opened["negotiation_id"],
                data=PaymentSettlementData.parse(opened["settlement_data"]),
                buyer=buyer,
                seller=seller,
            )


@pytest.mark.asyncio
async def test_a_negotiated_payment_deal_records_what_settlement_needs(harness):
    opened = harness.opened
    assert opened["action"] == "accept"
    agreement_bytes = base64.b64decode(opened["agreement_bytes"])
    agreement = json.loads(agreement_bytes)
    assert agreement["settlement_params"] == {"payer_account": PAYER}
    assert agreement["amount"] == "100"
    db = harness.runtime.db
    terms = await db.load_bare_metal_terms(negotiation_id=harness.negotiation_id)
    assert (terms.host_id, terms.physical_host_id, terms.ssh_public_key) == (
        HOST,
        PHYSICAL_HOST,
        SSH_KEY,
    )
    record = await db.load_bare_metal_settlement_record(negotiation_id=harness.negotiation_id)
    assert record["agreement_sha256"] == hashlib.sha256(agreement_bytes).hexdigest()
    assert record["status"] == "accepted"


async def _status_code(call) -> int:
    with pytest.raises(StorefrontClientError) as exc:
        await call()
    return exc.value.status_code


@pytest.mark.asyncio
async def test_a_verified_receipt_starts_fulfillment_once(harness):
    pending = await harness.settle()
    assert pending.pending and pending.retryable
    assert harness.provisioning.begin_calls == []

    harness.serve()
    started = await harness.settle()
    assert not started.pending
    assert started.settlement_ref == harness.data.transaction_id
    assert started.escrow_uid == harness.negotiation_id
    await harness.settle()
    assert len(harness.provisioning.begin_calls) == 1


@pytest.mark.asyncio
async def test_an_impostor_receipt_is_refused_without_fulfillment(harness):
    harness.serve(signer=IMPOSTOR)
    assert await _status_code(harness.settle) == 409
    assert harness.provisioning.begin_calls == []
    record = await harness.runtime.db.load_bare_metal_settlement_record(
        negotiation_id=harness.negotiation_id
    )
    assert record["status"] == "accepted"


@pytest.mark.asyncio
async def test_a_refund_before_delivery_blocks_fulfillment(harness):
    harness.serve()
    refunded = await harness.refund()
    assert refunded.status == "refunded"
    assert (await harness.settle()).status == "refunded"
    assert harness.provisioning.begin_calls == []
    assert harness.payments.count("reverse") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False])
async def test_an_accepted_deal_settles_and_refunds_after_payments_is_disabled(harness):
    harness.serve()
    await harness.settle()
    assert len(harness.provisioning.begin_calls) == 1
    assert (await harness.refund()).status == "refunded"


@pytest.mark.asyncio
async def test_a_refund_recorded_before_delivery_start_stops_delivery(harness):
    db = harness.runtime.db
    gate = asyncio.Event()
    start = db.start_bare_metal_payment_lifecycle

    async def gated_start(**kwargs):
        await gate.wait()
        return await start(**kwargs)

    db.start_bare_metal_payment_lifecycle = gated_start
    harness.serve()
    settling = asyncio.create_task(harness.settle())
    await asyncio.sleep(0.05)
    assert (await harness.refund()).status == "refunded"
    gate.set()
    with pytest.raises(StorefrontClientError):
        await settling
    assert harness.provisioning.begin_calls == []
    assert await db.load_bare_metal_fulfillment_lifecycle(negotiation_id=harness.negotiation_id) is None


@pytest.mark.asyncio
async def test_a_refund_after_delivery_start_records_both(harness):
    harness.provisioning.started = asyncio.Event()
    harness.provisioning.release = asyncio.Event()
    harness.serve()
    settling = asyncio.create_task(harness.settle())
    await harness.provisioning.started.wait()
    assert (await harness.refund()).status == "refunded"
    harness.provisioning.release.set()
    await settling
    db = harness.runtime.db
    assert len(harness.provisioning.begin_calls) == 1
    assert await db.load_bare_metal_fulfillment_lifecycle(negotiation_id=harness.negotiation_id) is not None
    record = await db.load_bare_metal_settlement_record(negotiation_id=harness.negotiation_id)
    assert record["status"] == "refunded"


@pytest.mark.asyncio
async def test_an_interrupted_refund_completes_on_the_next_call(harness):
    harness.serve()
    await harness.settle()
    await harness.runtime.db.record_bare_metal_refund_intent(negotiation_id=harness.negotiation_id)
    harness.payments.reversed = True
    harness.payments.reverse_error = "hold_not_reversible"
    assert (await harness.refund()).status == "refunded"


@pytest.mark.asyncio
async def test_every_settlement_route_contract_is_mounted(harness):
    """The settle, status, and refund routes are mounted where the contract declares them."""
    from storefront_client.settlement_routes import unmounted_settlement_routes

    mounted = [
        (method, route.path)
        for route in harness.app.routes
        if getattr(route, "path", None)
        for method in (getattr(route, "methods", None) or ())
    ]

    assert unmounted_settlement_routes(mounted) == []



def _restarted_runtime(tmp_path, payments: FakePaymentsClient) -> tuple[BareMetalStorefrontRuntime, Provisioning]:
    """A fresh runtime over the same SQLite file, as after a process restart."""
    domain = get_market_domain_contract()
    provisioning = Provisioning()
    runtime = BareMetalStorefrontRuntime(
        db=SQLiteClient(str(tmp_path / "storefront.db"), domain=domain),
        domain=domain,
        seller_principal=SELLER.identity,
        admin_principals=TrustedIdentitySet(identities=(ADMIN.identity,)),
        storefront_url="http://test",
        marketplace_signer=SELLER,
        settlement_composition=_composition(payments),
        capacity_client=Capacity(),
        fulfillment_client=provisioning,
    )
    return runtime, provisioning


@pytest.mark.asyncio
async def test_an_approved_payment_converges_after_restart_without_the_buyer(harness, tmp_path):
    """The buyer approved, never settled, and the storefront restarted: the seller delivers."""
    payments = FakePaymentsClient()
    payments.serve(build_signed_receipt(signer=SERVICE, mandate=harness.data.mandate))
    runtime, provisioning = _restarted_runtime(tmp_path, payments)
    assert runtime.payments_reconciliation_enabled()

    # The registered step: what the timer loop and an operator's step run.
    done = await runtime.settlement_service().reconcile_payments_once()

    assert (done.attempted, done.failed) == (1, 0)
    assert len(provisioning.begin_calls) == 1
    record = await runtime.db.load_bare_metal_settlement_record(negotiation_id=harness.negotiation_id)
    assert record["status"] == "settlement_verified"
    assert await runtime.db.load_bare_metal_fulfillment_lifecycle(
        negotiation_id=harness.negotiation_id
    ) is not None

    # Delivery has started, so a later pass leaves the deal to fulfillment.
    again = await runtime.settlement_service().reconcile_payments_once()
    assert again.attempted == 0
    assert len(provisioning.begin_calls) == 1


@pytest.mark.asyncio
async def test_reconciliation_leaves_an_unapproved_payment_pending(harness, tmp_path):
    runtime, provisioning = _restarted_runtime(tmp_path, FakePaymentsClient())

    done = await runtime.settlement_service().reconcile_payments_once()

    assert (done.attempted, done.failed) == (1, 0)
    assert provisioning.begin_calls == []
    record = await runtime.db.load_bare_metal_settlement_record(negotiation_id=harness.negotiation_id)
    assert record["status"] == "accepted"

def _clone_row(db_path: str, table: str, source: str, new_id: str, **columns) -> None:
    """Copy one negotiation-keyed row under a new negotiation ID, overriding columns."""
    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DROP TABLE IF EXISTS temp.clone")
        conn.execute(f"CREATE TEMP TABLE clone AS SELECT * FROM {table} WHERE negotiation_id = ?", (source,))
        assignments = ", ".join(f"{name} = ?" for name in ("negotiation_id", *columns))
        conn.execute(f"UPDATE clone SET {assignments}", (new_id, *columns.values()))
        conn.execute(f"INSERT INTO {table} SELECT * FROM clone")
        conn.commit()
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_completed_deals_never_crowd_out_an_unsettled_one(harness):
    """More completed payment deals than the pass limit still leave room for the stranded one."""
    db_path = harness.runtime.db.db_path
    for index in range(3):
        completed = f"completed-{index}"
        _clone_row(
            db_path, "negotiation_threads", harness.negotiation_id, completed,
            created_at=f"2000-01-01T00:00:0{index}",
        )
        _clone_row(
            db_path, "bare_metal_settlement_records", harness.negotiation_id, completed,
            status="refunded",
        )
    harness.serve()

    done = await harness.runtime.settlement_service().reconcile_payments_once(limit=1)

    assert (done.attempted, done.failed) == (1, 0)
    assert len(harness.provisioning.begin_calls) == 1
    record = await harness.runtime.db.load_bare_metal_settlement_record(
        negotiation_id=harness.negotiation_id
    )
    assert record["status"] == "settlement_verified"


@pytest.mark.asyncio
async def test_a_malformed_agreement_never_stops_reconciliation(harness):
    """One corrupt accepted thread is skipped; the stranded deal still converges."""
    db_path = harness.runtime.db.db_path
    _clone_row(
        db_path, "negotiation_threads", harness.negotiation_id, "corrupt",
        created_at="2000-01-01T00:00:00", agreement_bytes=b"{not json",
    )
    _clone_row(db_path, "bare_metal_settlement_records", harness.negotiation_id, "corrupt")
    harness.serve()

    done = await harness.runtime.settlement_service().reconcile_payments_once(limit=1)

    assert (done.attempted, done.failed) == (1, 0)
    assert len(harness.provisioning.begin_calls) == 1
