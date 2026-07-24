import sqlite3
from types import SimpleNamespace

import pytest

from compute_provisioning import (
    FulfillmentAcceptanceView,
    FulfillmentCredentialView,
    FulfillmentResultView,
    FulfillmentStatusView,
    ProvisionedResourceView,
    SettlementResourceView,
)
from market_storefront.services import fulfillment_reconciler as module
from market_storefront.services.fulfillment_reconciler import (
    StorefrontFulfillmentReconciler,
)
from market_storefront.utils.sqlite_client import SQLiteClient


class _ComputeClient:
    def __init__(self, calls, site_id):
        self.calls = calls
        self.site_id = site_id
        self.status = "dispatching"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def schedule_resource(self, request):
        self.calls.append((self.site_id, "schedule", request.capacity_reservation_id))
        return SettlementResourceView(
            capacity_reservation_id=request.capacity_reservation_id,
            settlement_resource_id="resource-b",
            pool_id="pool-b",
            resource_kind="compute.gpu",
            provider="ansible",
            attributes={"vm_host": "host-b"},
        )

    async def begin_fulfillment(self, request):
        self.calls.append((self.site_id, "begin", request.capacity_reservation_id))
        return FulfillmentAcceptanceView(
            capacity_reservation_id=request.capacity_reservation_id,
            fulfillment_id="fulfillment-b",
            state="dispatch_pending",
        )

    async def get_fulfillment_status(self, fulfillment_id):
        self.calls.append((self.site_id, "status", fulfillment_id))
        return FulfillmentStatusView(
            fulfillment_id=fulfillment_id,
            capacity_reservation_id="reservation-b",
            state=self.status,
        )

    async def get_fulfillment_result(self, fulfillment_id):
        self.calls.append((self.site_id, "result", fulfillment_id))
        return FulfillmentResultView(
            fulfillment_id=fulfillment_id,
            capacity_reservation_id="reservation-b",
            state="active",
            provisioned_resources=[ProvisionedResourceView(
                provisioned_resource_id="output-1",
                domain_resource_ref="vm-b",
                status="active",
            )],
            credential_generation=1,
            credentials=[FulfillmentCredentialView(
                kind="vm.access.v1",
                schema_version=1,
                payload={"role": "tenant", "password": "rotated"},
            )],
        )


class _CapacityClient:
    calls = []

    def __init__(self, base_url, admin_key):
        self.base_url = base_url
        self.admin_key = admin_key

    async def commit(self, **kwargs):
        self.calls.append((self.base_url, self.admin_key, kwargs))


async def _seed(client):
    await client.insert_escrow(
        escrow_uid="escrow-b",
        negotiation_id="neg-b",
        chain_name="anvil",
        escrow_address="0xescrow",
    )
    with sqlite3.connect(client.db_path) as conn:
        conn.execute(
            "INSERT INTO negotiation_threads "
            "(negotiation_id, our_listing_id, status, created_at, updated_at, "
            "terminal_state, agreed_price, agreed_duration_seconds) "
            "VALUES ('neg-b', 'listing-b', 'active', 'now', 'now', "
            "'success', '1', 3600)"
        )
        conn.execute(
            "INSERT INTO listings "
            "(listing_id, status, created_at, updated_at, offer_resource, seller) "
            "VALUES ('listing-b', 'open', 'now', 'now', '{}', 'seller')"
        )
        conn.commit()
    await client.create_fulfillment_workflow(
        escrow_uid="escrow-b",
        site_id="site-b",
        capacity_reservation_id="reservation-b",
        schedule_request={
            "contract_version": "1.0",
            "capacity_reservation_id": "reservation-b",
            "market": "vms",
            "requirements": {"resource_kind": "compute.gpu", "dimensions": {"gpu_count": 1}},
            "resource_id": None,
        },
        begin_request={
            "contract_version": "1.0",
            "capacity_reservation_id": "reservation-b",
            "market": "vms",
            "fulfillment_request": {
                "kind": "vms.fulfillment", "schema_version": 1, "payload": {}
            },
        },
    )


@pytest.mark.asyncio
async def test_restart_resumes_every_phase_at_only_the_persisted_site(tmp_path, monkeypatch):
    db = SQLiteClient(str(tmp_path / "storefront.db"))
    await _seed(db)
    calls = []
    compute = _ComputeClient(calls, "site-b")
    monkeypatch.setattr(module, "compute_client_for_site", lambda site_id: compute)
    monkeypatch.setattr(
        module,
        "require_provisioning_site",
        lambda site_id: SimpleNamespace(
            site_id=site_id, base_url="https://site-b", admin_key="key-b"
        ),
    )
    _CapacityClient.calls = []
    monkeypatch.setattr(module, "RemoteCapacityClient", _CapacityClient)

    # Reconstruct the worker between every durable phase.
    for expected in ("scheduled", "committed", "accepted"):
        workflow = await db.load_fulfillment_workflow(escrow_uid="escrow-b")
        await StorefrontFulfillmentReconciler(sqlite_client=db).reconcile_one(workflow)
        assert (await db.load_fulfillment_workflow(escrow_uid="escrow-b"))["phase"] == expected

    workflow = await db.load_fulfillment_workflow(escrow_uid="escrow-b")
    await StorefrontFulfillmentReconciler(sqlite_client=db).reconcile_one(workflow)
    assert (await db.load_fulfillment_workflow(escrow_uid="escrow-b"))["phase"] == "accepted"

    compute.status = "active"
    workflow = await db.load_fulfillment_workflow(escrow_uid="escrow-b")
    await StorefrontFulfillmentReconciler(sqlite_client=db).reconcile_one(workflow)
    persisted = await db.load_fulfillment_workflow(escrow_uid="escrow-b")
    escrow = await db.load_escrow(escrow_uid="escrow-b")

    assert persisted["phase"] == "result_applied"
    assert persisted["credential_generation"] == 1
    assert "rotated" not in str(persisted)
    assert "rotated" in escrow["tenant_credentials"]
    assert {call[0] for call in calls} == {"site-b"}
    assert _CapacityClient.calls[0][0:2] == ("https://site-b", "key-b")
    assert _CapacityClient.calls[0][2]["resource_id"] == "resource-b"
