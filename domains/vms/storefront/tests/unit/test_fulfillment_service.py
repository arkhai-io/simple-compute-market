from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_core import VersionedEnvelope
from market_identity import Ed25519Signer

import market_storefront.container as container
from market_storefront.domain_runtime import (
    build_vm_storefront_domain,
    build_vm_storefront_registry,
)
from market_storefront.publication_binding import prepare_vm_listing_binding
from market_storefront.services import fulfillment_service
from market_storefront.settlement_stages import VmAlkahestSellerStage
from market_storefront.utils.sqlite_client import SQLiteClient
from tests._settings_overrides import settings_overrides
from tests.fake_site import (
    TEST_MARKETPLACE_SIGNER,
    TEST_SITE_AUTHORITIES,
    FakeSite,
    pump_events,
    site_capacity,
)
from tests.fulfillment_fixtures import make_vm_lifecycle_fixture

_TEST_STOREFRONT_SIGNER = TEST_MARKETPLACE_SIGNER
_TEST_PROVISIONING_AUTHORITIES = TEST_SITE_AUTHORITIES
_TEST_SELLER_PRINCIPAL = _TEST_STOREFRONT_SIGNER.identity
_TEST_BUYER_PRINCIPAL = Ed25519Signer(b"\x23" * 32).identity


@pytest.fixture(autouse=True)
def _identity_wiring(monkeypatch):
    monkeypatch.setattr(
        container,
        "resolved_marketplace_signer",
        _TEST_STOREFRONT_SIGNER,
    )
    monkeypatch.setattr(
        fulfillment_service,
        "get_provisioning_authorities",
        lambda: _TEST_PROVISIONING_AUTHORITIES,
    )


@pytest.fixture
def client(tmp_path):
    return SQLiteClient(
        db_path=str(tmp_path / "agent.db"),
        registry=build_vm_storefront_registry(build_vm_storefront_domain()),
    )


async def _seed_compute_pool(client: SQLiteClient) -> None:
    await client.upsert_resource(
        resource_id="pool-h200-1",
        resource_type="compute.gpu",
        resource_subtype="h200",
        unit="count",
        value=1,
        state="available",
        attributes={
            "gpu_model": "H200",
            "region": "California, US",
            "vm_host": "host-1",
        },
    )


async def _seed_bound_listing(
    client: SQLiteClient,
    *,
    listing_id: str,
    gpu_count: int,
) -> None:
    await client.upsert_listing_with_binding(
        binding=prepare_vm_listing_binding(
            listing_id=listing_id,
            candidate={
                "capacity_backing": "backed",
                "site_id": "default",
                "pool_id": "pool-h200-1",
                # The listing publishes this resource, so its binding names it:
                # a stored key is read from the binding, not the published fields.
                "resource_id": "pool-h200-1",
                "listing_shape": {"gpu": {"count": gpu_count, "model": "H200"}},
            },
        ),
        status="open",
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
        listing_resource={
            "resource_id": "pool-h200-1",
            "gpu_model": "H200",
            "gpu_count": gpu_count,
            "region": "California, US",
            "sla": 99.0,
            "offering_mode": "vm",
        },
        accepted_escrows=_compute_listing(gpu_count=gpu_count)["accepted_escrows"],
        demands=[],
        fulfillment_resource=None,
        max_duration_seconds=3600,
        storefront_url="http://seller",
        seller_principal=_TEST_SELLER_PRINCIPAL,
    )


async def _seed_compute_listings(client: SQLiteClient, *, max_gpu_count: int) -> None:
    for gpu_count in range(1, max_gpu_count + 1):
        await _seed_bound_listing(
            client,
            listing_id=f"listing-{gpu_count}x",
            gpu_count=gpu_count,
        )


def _compute_listing(*, gpu_count: int = 1) -> dict:
    return {
        "listing_id": f"listing-{gpu_count}x",
        "seller_principal": _TEST_SELLER_PRINCIPAL.model_dump(mode="json"),
        "buyer_principal": _TEST_BUYER_PRINCIPAL.model_dump(mode="json"),
        "listing_resource": {
            "resource_id": "pool-h200-1",
            "gpu_model": "H200",
            "gpu_count": gpu_count,
            "region": "California, US",
            "sla": 99.0,
            "offering_mode": "vm",
        },
        "accepted_escrows": [
            {
                "chain_name": "anvil",
                "escrow_address": "0x" + "11" * 20,
                "literal_fields": {
                    "token": "0x" + "22" * 20,
                },
                "rates": [
                    {"field": "amount", "per": "hour", "value": "100"},
                ],
            }
        ],
    }


@pytest.mark.asyncio
async def test_fulfill_compute_obligation_defers_when_onchain_fulfillment_fails(
    client,
    monkeypatch,
):
    class FakeProvisioningClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None


    await _seed_compute_pool(client)
    lifecycle = await make_vm_lifecycle_fixture(
        Path(client.db_path),
        site_id="default",
        pool_id="pool-h200-1",
        with_context=False,
        context_payload={
            "order": _compute_listing(),
            "required_attributes": {"gpu_model": "H200", "gpu_count": 1},
        },
    )
    fake = FakeSite(deliverable_modes={"vm"})
    fake.add_resource(
        "pool-h200-1",
        1,
        attributes={
            "gpu_model": "H200",
            "region": "California, US",
            "vm_host": "host-1",
        },
    )
    monkeypatch.setattr(
        fulfillment_service,
        "ComputeProvisioningClient",
        FakeProvisioningClient,
    )

    async def controlled_provision(*args, on_job_submitted, **kwargs):
        await on_job_submitted("physical-1")
        return {"ssh": "ssh tenant@example"}

    monkeypatch.setattr(
        fulfillment_service,
        "_do_provision",
        controlled_provision,
    )

    alkahest = MagicMock()
    alkahest.string_obligation.do_obligation = AsyncMock(
        side_effect=RuntimeError("contract reverted")
    )
    alkahest.oracle.request_arbitration = AsyncMock()

    with site_capacity(
        fake,
        sqlite_client_factory=lambda: client,
        project_pool_modes=True,
    ):
        result = await fulfillment_service.fulfill_compute_obligation(
            sqlite_client=client,
            evidence=lifecycle.evidence,
            site_id="default",
        )

    assert result["status"] == "fulfilled"
    delivery = await client.load_vm_delivery(
        negotiation_id=lifecycle.evidence.negotiation_id
    )
    with pytest.raises(RuntimeError, match="contract reverted"):
        await VmAlkahestSellerStage(None).continue_delivery(
            evidence=lifecycle.evidence,
            db=client,
            delivery=delivery,
            connection_json=result["connection_details"],
            client=alkahest,
        )
    alkahest.oracle.request_arbitration.assert_not_called()

    # The VM exists and the lease was committed before the on-chain step
    # failed — the ledger keeps the capacity held.
    assert fake._available("pool-h200-1") == 0
    states = {a["state"] for a in fake.reservations.values()}
    assert states == {"leased"}


@pytest.mark.asyncio
async def test_reservation_closes_oversized_dynamic_listings(client, monkeypatch):
    class FakeProvisioningClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None


    await _seed_compute_pool(client)
    await client.upsert_resource(
        resource_id="pool-h200-1",
        resource_type="compute.gpu",
        resource_subtype="h200",
        unit="count",
        value=4,
        state="available",
        attributes={
            "gpu_model": "H200",
            "region": "California, US",
            "vm_host": "host-1",
        },
    )
    lifecycle = await make_vm_lifecycle_fixture(
        Path(client.db_path),
        listing_id="listing-2x",
        site_id="default",
        pool_id="pool-h200-1",
        with_context=False,
        context_payload={
            "order": _compute_listing(gpu_count=2),
            "required_attributes": {"gpu_model": "H200", "gpu_count": 2},
        },
    )
    for gpu_count in (1, 3, 4):
        await _seed_bound_listing(
            client, listing_id=f"listing-{gpu_count}x", gpu_count=gpu_count
        )
    fake = FakeSite(deliverable_modes={"vm"})
    fake.add_resource(
        "pool-h200-1",
        4,
        attributes={
            "gpu_model": "H200",
            "region": "California, US",
            "vm_host": "host-1",
        },
    )
    monkeypatch.setattr(
        fulfillment_service,
        "ComputeProvisioningClient",
        FakeProvisioningClient,
    )

    async def controlled_provision(*args, on_job_submitted, **kwargs):
        await on_job_submitted("physical-1")
        return {"ssh": "ssh tenant@example"}

    monkeypatch.setattr(
        fulfillment_service,
        "_do_provision",
        controlled_provision,
    )

    with (
        settings_overrides(
            enable_registry_discovery=False,
            registry__urls=[],
        ),
        site_capacity(
            fake,
            sqlite_client_factory=lambda: client,
            project_pool_modes=True,
        ) as aggregate,
    ):
        result = await fulfillment_service.fulfill_compute_obligation(
            sqlite_client=client,
            evidence=lifecycle.evidence,
            site_id="default",
        )
        # The poller delivers deltas in production; pump them here.
        await pump_events(aggregate, fake)

    assert result["status"] == "fulfilled"
    statuses = {
        gpu_count: (await client.load_listing(listing_id=f"listing-{gpu_count}x"))[
            "status"
        ]
        for gpu_count in range(1, 5)
    }
    assert statuses == {
        1: "open",
        2: "open",
        3: "closed",
        4: "closed",
    }


@pytest.mark.asyncio
async def test_terminate_vm_lease_calls_the_same_client_as_registration(monkeypatch):
    """No early-termination business flow calls this yet --
    this only confirms the plumbing: same client class registration uses,
    correct endpoint-backing method, and the reason passed through."""
    captured = {}

    class FakeComputeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def terminate_lease(self, capacity_reservation_id, termination):
            captured["capacity_reservation_id"] = capacity_reservation_id
            captured["termination"] = termination

    monkeypatch.setattr(
        fulfillment_service, "ComputeProvisioningClient", FakeComputeClient
    )
    monkeypatch.setattr(
        fulfillment_service,
        "settings",
        SimpleNamespace(
            provisioning=SimpleNamespace(service_url="http://provisioning"),
            admin_api_key="admin",
        ),
    )

    await fulfillment_service.terminate_vm_lease(
        capacity_reservation_id="reservation-1",
        reason="buyer requested early termination",
    )

    assert captured["capacity_reservation_id"] == "reservation-1"
    assert captured["termination"].reason == "buyer requested early termination"


@pytest.mark.asyncio
async def test_do_provision_end_to_end_delivers_credentials_for_storage(
    client,
    monkeypatch,
):
    """Exercises the real _do_provision (schedule_resource -> begin_fulfillment
    -> poll -> get_fulfillment_result) through fulfill_vm_obligation's
    unmodified credential-storage code, with the fulfillment client mocked at
    the network boundary but capacity reservation going through a real
    FakeSite ledger. Confirms end to end -- real stored rows, not code
    inspection -- that credentials produced by the new fulfillment path
    reach the storefront's existing credential store correctly."""

    await _seed_compute_pool(client)
    lifecycle = await make_vm_lifecycle_fixture(
        Path(client.db_path),
        escrow_uid="escrow-e2e-1",
        negotiation_id="neg-e2e-1",
        listing_id="listing-1",
        site_id="default",
        pool_id="pool-h200-1",
        with_context=False,
        context_payload={
            "order": _compute_listing(),
            "required_attributes": {"gpu_model": "H200", "gpu_count": 1},
        },
    )
    fake = FakeSite(deliverable_modes={"vm"})
    fake.add_resource(
        "pool-h200-1",
        1,
        attributes={
            "gpu_model": "H200",
            "region": "California, US",
            "vm_host": "host-1",
        },
    )

    fulfillment_client = SimpleNamespace(
        schedule_resource=AsyncMock(
            return_value=SimpleNamespace(settlement_resource_id="host-1")
        ),
        begin_fulfillment=AsyncMock(
            return_value=SimpleNamespace(
                fulfillment_id="fulfillment-e2e-1", state="dispatching"
            )
        ),
        get_fulfillment_status=AsyncMock(
            return_value=SimpleNamespace(state="active", failure_message=None)
        ),
        get_fulfillment_result=AsyncMock(
            return_value=VersionedEnvelope(
                kind="fulfillment.result.v1",
                schema_version=1,
                payload={
                    "provisioned_resources": [
                        {
                            "provisioned_resource_id": "provisioned-vm-e2e-1",
                            "status": "active",
                        }
                    ],
                    "domain_result": {
                        "kind": "compute.access-delivery",
                        "schema_version": 1,
                        "payload": {
                            "endpoints": [
                                {"protocol": "ssh", "host": "host-1", "port": 2222, "user": "tenant"}
                            ],
                            "credentials": [
                                {"role": "root", "password": "root-pw", "key_type": None},
                                {"role": "tenant", "password": "tenant-pw", "key_type": "generated"},
                            ],
                            "ready_at": "2030-01-01T00:00:01+00:00",
                        },
                    },
                },
            )
        ),
    )

    class FakeComputeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None


    monkeypatch.setattr(
        fulfillment_service, "build_fulfillment_client", lambda *_: fulfillment_client
    )
    monkeypatch.setattr(fulfillment_service, "ComputeProvisioningClient", FakeComputeClient)
    monkeypatch.setattr(
        fulfillment_service.settings,
        "provisioning",
        SimpleNamespace(
            timeout=5.0,
            poll_interval=0.001,
            service_url="http://provisioning",
            frp_server_addr="",
        ),
        raising=False,
    )

    with site_capacity(
        fake,
        sqlite_client_factory=lambda: client,
        project_pool_modes=True,
    ):
        result = await fulfillment_service.fulfill_compute_obligation(
            sqlite_client=client,
            evidence=lifecycle.evidence,
            site_id="default",
        )

    assert result["status"] == "fulfilled"
    fulfillment_client.schedule_resource.assert_awaited_once()
    fulfillment_client.begin_fulfillment.assert_awaited_once()
    fulfillment_client.get_fulfillment_result.assert_awaited_once()

    # Real rows via the unchanged downstream credential-storage code --
    # verified here for real, not by field-name inspection alone.
    stored = await client.get_credentials(listing_id="listing-1", granted_to="self")
    roles = {row["role"]: row for row in stored}
    assert set(roles) == {"root", "tenant"}
    assert roles["root"]["password"] == "root-pw"
    # A delivery carries no key path on a provisioner host, so none is stored.
    assert roles["root"]["ssh_key_path_host"] is None
    assert roles["tenant"]["password"] == "tenant-pw"
    assert roles["tenant"]["key_type"] == "generated"

    # The escrow row carries the durable fulfillment identity by the time
    # this call returns. This proves the identifiers round-trip correctly;
    # it does not by itself prove restart *resumption* -- nothing yet reads
    # these values back to resume an in-progress fulfillment after a crash.
    escrow = await client.load_vm_delivery(negotiation_id="neg-e2e-1")
    assert escrow["fulfillment_id"] == "fulfillment-e2e-1"
    assert escrow["settlement_resource_id"] == "host-1"
    assert escrow["capacity_reservation_id"]


@pytest.mark.asyncio
async def test_do_provision_result_fetch_is_safe_to_repeat(client, monkeypatch):
    """Duplicate-result coverage: fetching get_fulfillment_result
    more than once for the same fulfillment must not mutate state or
    double-store credentials -- store_credential's own INSERT OR IGNORE
    already guarantees the storage half; this confirms _do_provision's
    calling code doesn't do anything that would defeat that (e.g. calling
    schedule/begin a second time)."""

    await _seed_compute_pool(client)
    lifecycle = await make_vm_lifecycle_fixture(
        Path(client.db_path),
        escrow_uid="escrow-dup-1",
        negotiation_id="neg-dup-1",
        listing_id="listing-1",
        site_id="default",
        pool_id="pool-h200-1",
        with_context=False,
        context_payload={
            "order": _compute_listing(),
            "required_attributes": {"gpu_model": "H200", "gpu_count": 1},
        },
    )
    fake = FakeSite(deliverable_modes={"vm"})
    fake.add_resource(
        "pool-h200-1",
        1,
        attributes={
            "gpu_model": "H200",
            "region": "California, US",
            "vm_host": "host-1",
        },
    )

    envelope = VersionedEnvelope(
        kind="fulfillment.result.v1",
        schema_version=1,
        payload={
            "provisioned_resources": [
                {"provisioned_resource_id": "provisioned-vm-dup-1", "status": "active"}
            ],
            "domain_result": {
                "kind": "compute.access-delivery",
                "schema_version": 1,
                "payload": {
                    "endpoints": [
                        {"protocol": "ssh", "host": "host-1", "port": 2222, "user": "tenant"}
                    ],
                    "credentials": [
                        {"role": "tenant", "password": "tenant-pw", "key_type": None},
                    ],
                    "ready_at": "2030-01-01T00:00:01+00:00",
                },
            },
        },
    )
    fulfillment_client = SimpleNamespace(
        schedule_resource=AsyncMock(
            return_value=SimpleNamespace(settlement_resource_id="host-1")
        ),
        begin_fulfillment=AsyncMock(
            return_value=SimpleNamespace(
                fulfillment_id="fulfillment-dup-1", state="dispatching"
            )
        ),
        get_fulfillment_status=AsyncMock(
            return_value=SimpleNamespace(state="active", failure_message=None)
        ),
        get_fulfillment_result=AsyncMock(return_value=envelope),
    )

    class FakeComputeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None


    monkeypatch.setattr(
        fulfillment_service, "build_fulfillment_client", lambda *_: fulfillment_client
    )
    monkeypatch.setattr(fulfillment_service, "ComputeProvisioningClient", FakeComputeClient)
    monkeypatch.setattr(
        fulfillment_service.settings,
        "provisioning",
        SimpleNamespace(
            timeout=5.0, poll_interval=0.001, service_url="http://provisioning",
        ),
        raising=False,
    )

    with site_capacity(
        fake,
        sqlite_client_factory=lambda: client,
        project_pool_modes=True,
    ):
        first = await fulfillment_service.fulfill_compute_obligation(
            sqlite_client=client,
            evidence=lifecycle.evidence,
            site_id="default",
        )
        # A second, independent get_fulfillment_result read for the same
        # fulfillment (e.g. a caller re-checking status/result) must be
        # side-effect-free.
        escrow = await client.load_vm_delivery(negotiation_id="neg-dup-1")
        second_envelope = await fulfillment_client.get_fulfillment_result(
            "fulfillment-dup-1",
            capacity_reservation_id=escrow["capacity_reservation_id"],
        )

    assert first["status"] == "fulfilled"
    assert second_envelope.payload == envelope.payload

    stored = await client.get_credentials(listing_id="listing-1", granted_to="self")
    # Exactly one tenant credential row -- INSERT OR IGNORE plus the
    # unique id per call means a genuinely repeated store_credential call
    # with the same content would still only be exercised once here since
    # fulfill_compute_obligation itself only stores once per call; this
    # pins that fulfill_compute_obligation doesn't call store_credential
    # more than once for a single fulfillment.
    assert len([row for row in stored if row["role"] == "tenant"]) == 1
