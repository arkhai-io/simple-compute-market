"""Quota-backed publish and capacity-driven listing reconcile."""

from __future__ import annotations

import json
from datetime import datetime

import httpx
import pytest

from core_storefront.auth import signed_response_headers
from core_storefront.capacity import CapacityDelta
from market_capacity_publication import CapacityReconcileContext
from market_core.schemas import SettlementOption

from apicredits_storefront import container
from apicredits_storefront.domain_runtime import get_market_domain_contract
from apicredits_storefront.server import build_listing_service
from apicredits_storefront.settlement_composition import SELLER_STAGES
from market_site_client import SiteCapacityClient
from market_identity import Ed25519Signer, TrustedIdentitySet
from tests.integration.credit_negotiation import payment_option
from tests.listing_bindings import upsert_bound_listing

_SELLER_SIGNER = Ed25519Signer(bytes.fromhex("22" * 32))
_AUTHORITY_SIGNER = Ed25519Signer(bytes.fromhex("33" * 32))
SELLER_PRINCIPAL = _SELLER_SIGNER.identity


def _quota_remote(available_by_resource: dict[str, int]) -> SiteCapacityClient:
    """A SiteCapacityClient whose snapshot is served from a dict."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/capacity/snapshot":
            body = {
                "resources": [
                    {
                        "resource_id": rid,
                        "resource_type": "api_credits",
                        "total_units": 1000,
                        "available_units": available,
                    }
                    for rid, available in available_by_resource.items()
                ],
            }
            headers = signed_response_headers(
                signer=_AUTHORITY_SIGNER,
                role="service",
                method=request.method,
                operation="capacity_snapshot",
                resource="",
                request_id=request.headers["X-Market-Request-ID"],
                status=200,
                body=body,
            )
            return httpx.Response(200, json=body, headers=headers)
        return httpx.Response(404, json={})

    return SiteCapacityClient(
        "http://tokens:8082",
        signer=_SELLER_SIGNER,
        expected_authorities=TrustedIdentitySet(
            identities=(_AUTHORITY_SIGNER.identity,),
        ),
        transport=httpx.MockTransport(handler),
    )


class _QuotaRuntime:
    """The credits site: its availability and its pool projection."""

    def __init__(
        self,
        values: dict[str, int],
        *,
        backing: str = "backed",
        pool_id: str = "default",
        reachable: bool = True,
    ) -> None:
        self._values = values
        self._backing = backing
        self._pool_id = pool_id
        self._reachable = reachable

    def site_client(self, site_id: str) -> "_QuotaRuntime":
        assert site_id == "tokens"
        return self

    async def resource_pool_projection(self) -> dict:
        if not self._reachable:
            raise ConnectionError("credits site unreachable")
        return {
            "resource_pools": [
                {
                    "pool_id": self._pool_id,
                    "resources": [
                        {"physical_resource_id": resource_id}
                        for resource_id in self._values
                    ],
                    "pool_metadata": {
                        "enabled": True,
                        "policy_tags": {
                            "deliverable_modes": (
                                ["api_credits"] if self._backing == "backed" else []
                            ),
                            "advertisable_modes": ["api_credits"],
                            "capacity_backing": self._backing,
                        },
                    },
                }
            ]
        }

    async def availability(self) -> dict[tuple[str, str], int]:
        return {
            ("tokens", resource_id): units
            for resource_id, units in self._values.items()
        }


class _SettlementComposition:
    stages = SELLER_STAGES

    async def readiness(self) -> tuple[()]:
        return ()

    async def publication_artifacts(
        self,
        _facts,
        _clauses,
    ) -> tuple[list[dict], list[dict], tuple[()]]:
        return [], [], ()

    def release_conditions(self, _accepted_escrows) -> list[dict]:
        return []


def _listing_service(db, composition):
    return build_listing_service(
        get_market_domain_contract(),
        sqlite_client=db,
        seller_principal=SELLER_PRINCIPAL,
        settlement_composition=composition,
    )


@pytest.fixture
async def db(tmp_path):
    from apicredits_storefront.container import storefront_sqlite_client

    return storefront_sqlite_client(db_path=str(tmp_path / "publish.db"))


async def _insert_listing(db, listing_id: str, resource_id: str, status: str):
    await upsert_bound_listing(
        db,
        listing_id=listing_id,
        status=status,
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat(),
        listing_resource={
            "kind": "api_credits.v1",
            "service_name": "Acme",
            "resource_id": resource_id,
            "capacity_site_id": "tokens",
            "offering_mode": "api_credits",
        },
        accepted_escrows=[
            {
                "chain_name": "anvil",
                "escrow_address": "0x" + "11" * 20,
                "literal_fields": {"token": "0x" + "01" * 20},
                "rates": [{"field": "amount", "per": "token", "value": "100"}],
            }
        ],
        fulfillment_resource=None,
        max_duration_seconds=None,
        storefront_url="http://seller:8002",
        seller_principal=SELLER_PRINCIPAL,
    )


async def test_publish_from_quota_requires_registered_sellable_resource(
    db,
    monkeypatch,
):
    monkeypatch.setattr(container, "_sqlite_client", db)
    runtime = _QuotaRuntime({"svc-quota": 42, "svc-empty": 0})
    monkeypatch.setattr(container.QUOTA_CAPACITY, "runtime", lambda factory: runtime)

    svc = _listing_service(db, _SettlementComposition())
    result = await svc.publish_from_quota(
        resource_id="svc-quota",
        service_name="Acme Inference",
        accepted_escrows=[
            {
                "chain_name": "anvil",
                "escrow_address": "0x" + "11" * 20,
                "literal_fields": {"token": "0x" + "01" * 20},
                "rates": [{"field": "amount", "per": "token", "value": "100"}],
            }
        ],
        openapi_url="https://api.acme.example/openapi.json",
        base_url="https://api.acme.example",
    )
    assert result["status"] == "created"
    # Registry discovery is disabled in tests; the local row is the artifact.
    row = await db.load_listing(listing_id=result["listing_id"])
    assert row["status"] == "open"
    listing_resource = row["listing_resource"]
    listing_resource = json.loads(listing_resource) if isinstance(listing_resource, str) else listing_resource
    assert listing_resource["resource_id"] == "svc-quota"
    assert listing_resource["capacity_site_id"] == "tokens"
    assert listing_resource["offering_mode"] == "api_credits"
    assert listing_resource["kind"] == "api_credits.v1"
    assert listing_resource["service_name"] == "Acme Inference"
    assert listing_resource["description"] is None

    with pytest.raises(ValueError, match="no sellable units"):
        await svc.publish_from_quota(
            resource_id="svc-empty",
            service_name="Empty",
            accepted_escrows=row["accepted_escrows"]
            if isinstance(row["accepted_escrows"], list)
            else json.loads(row["accepted_escrows"]),
        )
    with pytest.raises(ValueError, match="exactly one"):
        await svc.publish_from_quota(
            resource_id="svc-unknown",
            service_name="Ghost",
            accepted_escrows=[
                {"chain_name": "anvil", "escrow_address": "0x" + "11" * 20}
            ],
        )


async def test_publish_from_quota_validates_listing_through_domain_runtime(
    db,
    monkeypatch,
):
    runtime = _QuotaRuntime({"svc-quota": 42})
    monkeypatch.setattr(container.QUOTA_CAPACITY, "runtime", lambda factory: runtime)

    svc = _listing_service(db, _SettlementComposition())
    with pytest.raises(ValueError, match="service_name"):
        await svc.publish_from_quota(
            resource_id="svc-quota",
            service_name=" ",
            accepted_escrows=[
                {
                    "chain_name": "anvil",
                    "escrow_address": "0x" + "11" * 20,
                    "literal_fields": {"token": "0x" + "01" * 20},
                    "rates": [{"field": "amount", "per": "token", "value": "100"}],
                }
            ],
        )


async def test_capacity_deltas_close_and_reopen_token_listings(db, monkeypatch):
    monkeypatch.setattr(container, "_sqlite_client", db)
    monkeypatch.setattr(
        container.QUOTA_CAPACITY, "runtime", lambda factory: _QuotaRuntime({"svc-live": 10, "svc-dry": 5})
    )
    await _insert_listing(db, "L-live", "svc-live", "open")
    await _insert_listing(db, "L-dry", "svc-dry", "open")

    availability = await _QuotaRuntime({"svc-live": 10, "svc-dry": 0}).availability()
    closed = await container.QUOTA_PUBLICATION.close_after_capacity_change(db, availability)
    assert closed == ["L-dry"]
    assert (await db.load_listing(listing_id="L-dry"))["status"] == "closed"
    assert (await db.load_listing(listing_id="L-live"))["status"] == "open"

    # Quota released → the listing reopens.
    availability = await _QuotaRuntime({"svc-live": 10, "svc-dry": 5}).availability()
    reopened = await container.QUOTA_PUBLICATION.reopen_after_capacity_change(db, availability)
    assert reopened == ["L-dry"]
    assert (await db.load_listing(listing_id="L-dry"))["status"] == "open"


async def test_capacity_release_does_not_reopen_a_listing_its_seller_closed(
    db, monkeypatch
):
    """The capacity-event reconciler, entered as a released delta, leaves a
    seller's close alone while still reopening a listing quota exhaustion closed."""
    monkeypatch.setattr(container, "_sqlite_client", db)
    monkeypatch.setattr(
        container.QUOTA_CAPACITY, "runtime", lambda factory: _QuotaRuntime({"svc-a": 5, "svc-b": 5})
    )
    await _insert_listing(db, "L-withdrawn", "svc-a", "open")
    await _insert_listing(db, "L-exhausted", "svc-b", "open")

    await container.QUOTA_PUBLICATION.close(db, "L-withdrawn")
    exhausted = await _QuotaRuntime({"svc-a": 0, "svc-b": 0}).availability()
    await container.QUOTA_PUBLICATION.close_after_capacity_change(db, exhausted)
    assert (await db.load_listing(listing_id="L-withdrawn"))["closed_by"] == "seller"
    assert (await db.load_listing(listing_id="L-exhausted"))["closed_by"] == (
        "reconciliation"
    )

    released = await _QuotaRuntime({"svc-a": 5, "svc-b": 5}).availability()
    await container.QUOTA_PUBLICATION.reconciler(lambda: db)(
        CapacityReconcileContext(
            projections=(),
            availability=released,
            delta=CapacityDelta(kind="released", version=2, site="tokens"),
        )
    )

    withdrawn = await db.load_listing(listing_id="L-withdrawn")
    assert (withdrawn["status"], withdrawn["closed_by"]) == ("closed", "seller")
    assert (await db.load_listing(listing_id="L-exhausted"))["status"] == "open"


async def test_a_resource_moved_to_another_pool_does_not_reopen_its_listing(
    db, monkeypatch
):
    """Released quota reopens only a listing whose resource is still in the pool
    it was bound to, even when the new pool declares the same backing."""
    monkeypatch.setattr(container, "_sqlite_client", db)
    await _insert_listing(db, "L-moved", "svc-a", "open")
    exhausted = await _QuotaRuntime({"svc-a": 0}).availability()
    assert await container.QUOTA_PUBLICATION.close_after_capacity_change(db, exhausted) == ["L-moved"]

    monkeypatch.setattr(
        container.QUOTA_CAPACITY, "runtime", lambda factory: _QuotaRuntime({"svc-a": 5}, pool_id="other")
    )
    released = await _QuotaRuntime({"svc-a": 5}).availability()

    assert await container.QUOTA_PUBLICATION.reopen_after_capacity_change(db, released) == []
    assert (await db.load_listing(listing_id="L-moved"))["status"] == "closed"


async def _reconcile_release(db, monkeypatch, runtime):
    """Run the capacity reconciler as the ledger feeds a pool move: a release."""
    monkeypatch.setattr(container, "_sqlite_client", db)
    monkeypatch.setattr(container.QUOTA_CAPACITY, "runtime", lambda factory: runtime)
    await container.QUOTA_PUBLICATION.reconciler(lambda: db)(
        CapacityReconcileContext(
            projections=(),
            availability=await runtime.availability(),
            delta=CapacityDelta(kind="released", version=2, site="tokens"),
        )
    )
    return await db.load_listing(listing_id="L-bound")


@pytest.mark.parametrize(
    "runtime",
    [
        _QuotaRuntime({"svc-a": 5}, backing="unbacked"),
        _QuotaRuntime({"svc-a": 5}, pool_id="other"),
    ],
    ids=["backing-changed", "moved-to-a-pool-with-the-same-backing"],
)
async def test_an_open_listing_whose_source_changed_closes_with_quota_left(
    db, monkeypatch, runtime
):
    await _insert_listing(db, "L-bound", "svc-a", "open")

    listing = await _reconcile_release(db, monkeypatch, runtime)

    assert (listing["status"], listing["closed_by"]) == ("closed", "reconciliation")


async def test_an_unreadable_source_closes_no_open_listing(db, monkeypatch):
    await _insert_listing(db, "L-bound", "svc-a", "open")

    listing = await _reconcile_release(
        db, monkeypatch, _QuotaRuntime({"svc-a": 5}, reachable=False)
    )

    assert listing["status"] == "open"


def _quota_service(db, monkeypatch, runtime):
    monkeypatch.setattr(container, "_sqlite_client", db)
    monkeypatch.setattr(container.QUOTA_CAPACITY, "runtime", lambda factory: runtime)
    return _listing_service(db, _SettlementComposition())


_ALKAHEST_ESCROW = {
    "chain_name": "anvil",
    "escrow_address": "0x" + "11" * 20,
    "literal_fields": {"token": "0x" + "01" * 20},
    "rates": [{"field": "amount", "per": "token", "value": "100"}],
}


async def test_a_listing_is_bound_with_its_pools_backing(db, monkeypatch):
    svc = _quota_service(db, monkeypatch, _QuotaRuntime({"svc-quota": 42}))

    result = await svc.publish_from_quota(
        resource_id="svc-quota",
        service_name="Acme",
        accepted_escrows=[_ALKAHEST_ESCROW],
    )

    binding = await db.load_listing_binding(listing_id=result["listing_id"])
    assert (binding.site_id, binding.pool_id, binding.physical_resource_id) == (
        "tokens",
        "default",
        "svc-quota",
    )
    assert binding.capacity_backing == "backed"
    assert binding.binding.offering_mode == "api_credits"


async def test_two_listings_over_one_quota_resource_each_bind(db, monkeypatch):
    svc = _quota_service(db, monkeypatch, _QuotaRuntime({"svc-quota": 42}))

    first, second = [
        await svc.publish_from_quota(
            resource_id="svc-quota",
            service_name=name,
            accepted_escrows=[_ALKAHEST_ESCROW],
        )
        for name in ("Acme", "Acme Priority")
    ]

    bindings = [
        await db.load_listing_binding(listing_id=result["listing_id"])
        for result in (first, second)
    ]
    assert {binding.physical_resource_id for binding in bindings} == {"svc-quota"}
    assert bindings[0].derivation_key != bindings[1].derivation_key


async def test_an_unbacked_credits_pool_yields_no_listing(db, monkeypatch):
    svc = _quota_service(
        db, monkeypatch, _QuotaRuntime({"svc-quota": 42}, backing="unbacked")
    )

    with pytest.raises(ValueError, match="no settlement option"):
        await svc.publish_from_quota(
            resource_id="svc-quota",
            service_name="Acme",
            accepted_escrows=[_ALKAHEST_ESCROW],
        )

    assert await db.list_listings(status="open", limit=10) == []


async def test_a_database_with_an_unbound_listing_is_refused(tmp_path):
    from apicredits_storefront.container import storefront_sqlite_client

    path = str(tmp_path / "unbound.db")
    db = storefront_sqlite_client(db_path=path)
    await db.upsert_listing(
        listing_id="L-old",
        status="open",
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat(),
        listing_resource={
            "kind": "api_credits.v1",
            "service_name": "Acme",
            "resource_id": "svc-quota",
            "capacity_site_id": "tokens",
            "offering_mode": "api_credits",
        },
        accepted_escrows=[_ALKAHEST_ESCROW],
        fulfillment_resource=None,
        max_duration_seconds=None,
        storefront_url="http://seller:8002",
        seller_principal=SELLER_PRINCIPAL,
    )

    with pytest.raises(RuntimeError, match="L-old.*fresh database"):
        storefront_sqlite_client(db_path=path)


class _PaymentComposition(_SettlementComposition):
    """Publishes one Arkhai payments option, as a payments-composed storefront does."""

    def __init__(self, option: dict) -> None:
        self._option = option

    async def publication_artifacts(self, _facts, _clauses):
        return [], [dict(self._option)], ()


async def test_a_published_payment_option_is_stored_as_its_json_value(db, monkeypatch):
    option = payment_option().model_dump(mode="json")
    monkeypatch.setattr(container, "_sqlite_client", db)
    monkeypatch.setattr(
        container.QUOTA_CAPACITY, "runtime", lambda factory: _QuotaRuntime({"svc-quota": 42})
    )
    svc = _listing_service(db, _PaymentComposition(option))

    result = await svc.publish_from_quota(
        resource_id="svc-quota", service_name="Acme", accepted_escrows=[]
    )

    stored = await db.load_listing(listing_id=result["listing_id"])
    assert stored["settlement_options"] == [option]
    # A buyer reading the stored listing decodes the same typed option.
    assert [SettlementOption.model_validate(item) for item in stored["settlement_options"]] == [
        payment_option()
    ]
