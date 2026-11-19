"""Quota-backed publish and capacity-driven listing reconcile."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import httpx
import pytest
import yaml
from jsonschema import Draft202012Validator

from core_storefront.auth import signed_response_headers
from core_storefront.capacity import CapacityDelta
from core_storefront.multi_registry_client import RegistryListings
from market_capacity_publication import CapacityReconcileContext
from market_core.schemas import SettlementOption
from registry_client.models import ListingSummary

import apicredits_storefront.container as container_module
from apicredits_storefront.services import capacity_client as cc_module
from apicredits_storefront.services import publication_service as publication_module
from apicredits_storefront.services.capacity_client import _capacity_reconciler
from apicredits_storefront.services.listing_service import ListingService
from apicredits_storefront.services.publication_service import (
    close_order,
    close_token_listings_after_capacity_change,
)
from apicredits_storefront.utils import sqlite_client as sqlite_module
from apicredits_storefront.utils.migrations import migrate_storefront_database
from apicredits_storefront.utils.sqlite_client import refuse_unbound_listings
from market_site_client import SiteCapacityClient
from market_identity import Ed25519Signer, TrustedIdentitySet
from market_settlement_runtime import MechanismReadiness, ReadinessBlocker
from tests._settings_overrides import settings_overrides
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
    """Stands in for settlement: Alkahest ready, so the escrows a request
    supplies publish, and no release condition derived."""

    async def readiness(self, *, accepted_escrows=()) -> tuple[MechanismReadiness, ...]:
        return (
            MechanismReadiness(
                mechanism="alkahest.v1", configured=True, enabled=True, ready=True
            ),
        )

    async def publication_artifacts(
        self,
        _facts,
        _clauses,
    ) -> tuple[list[dict], list[dict], tuple[()]]:
        return [], [], ()

    def release_conditions(self, _accepted_escrows, *, readiness) -> list[dict]:
        return []

    def canonical_mechanism(self, name: str) -> str:
        return name


@pytest.fixture
async def db(tmp_path):
    from apicredits_storefront.utils.sqlite_client import SQLiteClient

    migrate_storefront_database(tmp_path / "publish.db")
    return SQLiteClient(db_path=str(tmp_path / "publish.db"))


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


class _ChainJudgedComposition(_SettlementComposition):
    """Alkahest ready on the clauses' chain and unready on the chains of the
    escrows a request supplies, each readiness reported as the composition
    judges it."""

    _CLAUSE_ESCROW = {
        "chain_name": "anvil",
        "escrow_address": "0x" + "11" * 20,
        "literal_fields": {"token": "0x" + "01" * 20},
        "rates": [{"field": "amount", "per": "token", "value": "100"}],
    }

    async def readiness(self, *, accepted_escrows=()):
        return (
            MechanismReadiness(
                mechanism="alkahest.v1",
                configured=True,
                enabled=True,
                ready=False,
                blockers=(
                    ReadinessBlocker(
                        code="alkahest.chain_unreachable",
                        message="no answer",
                        kind="reachability",
                    ),
                ),
            ),
        )

    async def publication_artifacts(self, _facts, _clauses):
        return (
            [dict(self._CLAUSE_ESCROW)],
            [],
            (
                MechanismReadiness(
                    mechanism="alkahest.v1", configured=True, enabled=True, ready=True
                ),
            ),
        )


async def test_supplied_escrows_are_judged_on_their_own_chains_beside_clauses(
    db, monkeypatch
):
    """An escrow a request supplies publishes only while Alkahest is ready on
    its own chain, whatever the clauses beside it compile."""
    monkeypatch.setattr(sqlite_module, "_sqlite_client", db)
    monkeypatch.setattr(
        cc_module, "build_capacity_runtime", lambda factory: _QuotaRuntime({"svc-quota": 42})
    )
    svc = ListingService(
        sqlite_client=db,
        seller_principal=SELLER_PRINCIPAL,
        settlement_composition=_ChainJudgedComposition(),
    )

    result = await svc.publish_from_quota(
        resource_id="svc-quota",
        service_name="Acme Inference",
        accepted_escrows=[{**_ChainJudgedComposition._CLAUSE_ESCROW, "chain_name": "base"}],
        settlement_clauses=[{"mechanism": "alkahest.v1", "asset": "0x" + "01" * 20}],
        paused=True,
    )

    row = await db.load_listing(listing_id=result["listing_id"])
    escrows = row["accepted_escrows"]
    escrows = json.loads(escrows) if isinstance(escrows, str) else escrows
    assert [escrow["chain_name"] for escrow in escrows] == ["anvil"]


async def test_publish_from_quota_requires_registered_sellable_resource(
    db,
    monkeypatch,
):
    from apicredits_storefront.services import capacity_client as cc_module
    from apicredits_storefront.services.listing_service import ListingService
    from apicredits_storefront.utils import sqlite_client as sqlite_module

    monkeypatch.setattr(sqlite_module, "_sqlite_client", db)
    runtime = _QuotaRuntime({"svc-quota": 42, "svc-empty": 0})
    monkeypatch.setattr(
        cc_module,
        "build_capacity_runtime",
        lambda factory: runtime,
    )

    svc = ListingService(
        sqlite_client=db,
        seller_principal=SELLER_PRINCIPAL,
        settlement_composition=_SettlementComposition(),
    )
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
    from apicredits_storefront.services import capacity_client as cc_module
    from apicredits_storefront.services.listing_service import ListingService

    runtime = _QuotaRuntime({"svc-quota": 42})
    monkeypatch.setattr(
        cc_module,
        "build_capacity_runtime",
        lambda factory: runtime,
    )

    svc = ListingService(
        sqlite_client=db,
        seller_principal=SELLER_PRINCIPAL,
        settlement_composition=_SettlementComposition(),
    )
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
    from apicredits_storefront.services.publication_service import (
        close_token_listings_after_capacity_change,
        reopen_token_listings_after_capacity_change,
    )
    from apicredits_storefront.utils import sqlite_client as sqlite_module

    monkeypatch.setattr(sqlite_module, "_sqlite_client", db)
    from apicredits_storefront.services import publication_service as publication_module

    monkeypatch.setattr(
        publication_module,
        "build_capacity_runtime",
        lambda factory: _QuotaRuntime({"svc-live": 10, "svc-dry": 5}),
    )
    await _insert_listing(db, "L-live", "svc-live", "open")
    await _insert_listing(db, "L-dry", "svc-dry", "open")

    availability = await _QuotaRuntime({"svc-live": 10, "svc-dry": 0}).availability()
    closed = await close_token_listings_after_capacity_change(db, availability)
    assert closed == ["L-dry"]
    assert (await db.load_listing(listing_id="L-dry"))["status"] == "closed"
    assert (await db.load_listing(listing_id="L-live"))["status"] == "open"

    # Quota released → the listing reopens.
    availability = await _QuotaRuntime({"svc-live": 10, "svc-dry": 5}).availability()
    reopened = await reopen_token_listings_after_capacity_change(db, availability)
    assert reopened == ["L-dry"]
    assert (await db.load_listing(listing_id="L-dry"))["status"] == "open"


async def test_capacity_release_does_not_reopen_a_listing_its_seller_closed(
    db, monkeypatch
):
    """The capacity-event reconciler, entered as a released delta, leaves a
    seller's close alone while still reopening a listing quota exhaustion closed."""
    monkeypatch.setattr(sqlite_module, "_sqlite_client", db)
    from apicredits_storefront.services import publication_service as publication_module

    monkeypatch.setattr(
        publication_module,
        "build_capacity_runtime",
        lambda factory: _QuotaRuntime({"svc-a": 5, "svc-b": 5}),
    )
    await _insert_listing(db, "L-withdrawn", "svc-a", "open")
    await _insert_listing(db, "L-exhausted", "svc-b", "open")

    await close_order({"listing_id": "L-withdrawn"})
    exhausted = await _QuotaRuntime({"svc-a": 0, "svc-b": 0}).availability()
    await close_token_listings_after_capacity_change(db, exhausted)
    assert (await db.load_listing(listing_id="L-withdrawn"))["closed_by"] == "seller"
    assert (await db.load_listing(listing_id="L-exhausted"))["closed_by"] == (
        "reconciliation"
    )

    released = await _QuotaRuntime({"svc-a": 5, "svc-b": 5}).availability()
    await _capacity_reconciler(lambda: db)(
        CapacityReconcileContext(
            projections=(),
            availability=released,
            delta=CapacityDelta(kind="released", version=2, site="tokens"),
        )
    )

    withdrawn = await db.load_listing(listing_id="L-withdrawn")
    assert (withdrawn["status"], withdrawn["closed_by"]) == ("closed", "seller")
    assert (await db.load_listing(listing_id="L-exhausted"))["status"] == "open"


_REGISTRY_URL = "https://registry.example"


class _SweptRegistry:
    """Stands where ``MultiRegistryClient`` wraps the one configured registry.

    Its read of the storefront's open listings returns what a test planted, and
    a close it is sent removes the listing; ``closes`` records each close.
    """

    urls = (_REGISTRY_URL,)

    def __init__(self) -> None:
        self.open: list[ListingSummary] = []
        self.closes: list[str] = []
        self.publisher_reads: list = []

    def plant(self, listing_id: str, offering_mode: str) -> None:
        self.open.append(
            ListingSummary(
                id=listing_id,
                status="open",
                listing_resource={"offering_mode": offering_mode},
            )
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def list_publisher_listings_per_registry(self, principal):
        self.publisher_reads.append(principal)
        return [RegistryListings(_REGISTRY_URL, tuple(self.open))]

    async def update_listing_per_registry(self, *, listing_id, payloads):
        assert {request.to_dict()["status"] for request in payloads.values()} == {"closed"}
        self.closes.append(listing_id)
        self.open = [item for item in self.open if item.id != listing_id]
        return [{"registry_url": url, "success": True} for url in payloads]


async def test_the_sweep_closes_registry_listings_the_storefront_does_not_hold(
    db, monkeypatch
):
    """The sweep each capacity reconciliation ends with, over the storefront's
    database, reads the registry under the storefront's principal: an
    API-credit listing it does not hold closes there, the listing it holds stays
    open, and a VM listing another storefront publishes under the same
    principal is left alone. The registry client is the publication service's
    own factory, replaced on that module."""
    await _insert_listing(db, "L-live", "svc-live", "open")
    registry = _SweptRegistry()
    registry.plant("L-orphaned", "api_credits")
    registry.plant("L-live", "api_credits")
    registry.plant("vm-1", "vm")
    monkeypatch.setattr(publication_module, "_make_registry_client", lambda: registry)
    monkeypatch.setattr(container_module, "resolved_marketplace_signer", _SELLER_SIGNER)

    with settings_overrides(enable_registry_discovery=True, registry__urls=[_REGISTRY_URL]):
        await publication_module.retire_unheld_listings(db)

    assert registry.closes == ["L-orphaned"]
    assert [item.id for item in registry.open] == ["L-live", "vm-1"]
    assert registry.publisher_reads == [SELLER_PRINCIPAL]
    assert (await db.load_listing(listing_id="L-live"))["status"] == "open"


async def test_a_resource_moved_to_another_pool_does_not_reopen_its_listing(
    db, monkeypatch
):
    """Released quota reopens only a listing whose resource is still in the pool
    it was bound to, even when the new pool declares the same backing."""
    monkeypatch.setattr(sqlite_module, "_sqlite_client", db)
    from apicredits_storefront.services import publication_service as publication_module
    from apicredits_storefront.services.publication_service import (
        close_token_listings_after_capacity_change,
        reopen_token_listings_after_capacity_change,
    )

    await _insert_listing(db, "L-moved", "svc-a", "open")
    exhausted = await _QuotaRuntime({"svc-a": 0}).availability()
    assert await close_token_listings_after_capacity_change(db, exhausted) == ["L-moved"]

    monkeypatch.setattr(
        publication_module,
        "build_capacity_runtime",
        lambda factory: _QuotaRuntime({"svc-a": 5}, pool_id="other"),
    )
    released = await _QuotaRuntime({"svc-a": 5}).availability()

    assert await reopen_token_listings_after_capacity_change(db, released) == []
    assert (await db.load_listing(listing_id="L-moved"))["status"] == "closed"


async def _reconcile_release(db, monkeypatch, runtime):
    """Run the capacity reconciler as the ledger feeds a pool move: a release."""
    from apicredits_storefront.services import publication_service as publication_module

    monkeypatch.setattr(sqlite_module, "_sqlite_client", db)
    monkeypatch.setattr(publication_module, "build_capacity_runtime", lambda factory: runtime)
    await _capacity_reconciler(lambda: db)(
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
    from apicredits_storefront.services import capacity_client as cc_module
    from apicredits_storefront.services.listing_service import ListingService

    monkeypatch.setattr(sqlite_module, "_sqlite_client", db)
    monkeypatch.setattr(cc_module, "build_capacity_runtime", lambda factory: runtime)
    return ListingService(
        sqlite_client=db,
        seller_principal=SELLER_PRINCIPAL,
        settlement_composition=_SettlementComposition(),
    )


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
    from apicredits_storefront.utils.sqlite_client import SQLiteClient

    path = str(tmp_path / "unbound.db")
    migrate_storefront_database(path)
    refuse_unbound_listings(path)
    db = SQLiteClient(db_path=path)
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
        refuse_unbound_listings(path)


class _PaymentComposition(_SettlementComposition):
    """Publishes one Arkhai payments option, as a payments-composed storefront does."""

    def __init__(self, option: dict) -> None:
        self._option = option

    async def publication_artifacts(self, _facts, _clauses):
        return [], [dict(self._option)], ()


#: The API-credit registry's own listing schema, as the registry validates a
#: publication against it.
_CREDITS_SPEC = Path(__file__).resolve().parents[5] / "domains/apicredits/registry/filter-spec.yaml"


def _credits_schema_errors(body: dict) -> list[str]:
    shape = yaml.safe_load(_CREDITS_SPEC.read_text())["listing_shape"]
    return [
        f"{list(error.absolute_path)}: {error.message}"
        for error in Draft202012Validator(shape).iter_errors(body)
    ]


class _RecordingRegistry:
    """Stands where ``MultiRegistryClient`` wraps the one configured registry,
    recording each request as the JSON the client would send. While
    ``failing`` the registry refuses every publication."""

    urls = (_REGISTRY_URL,)

    def __init__(self) -> None:
        self.published: list[dict] = []
        self.failing = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def publish_listing_per_registry(self, *, payloads):
        results = []
        for url, request in payloads.items():
            self.published.append(request.to_dict())
            results.append(
                {"registry_url": url, "success": False, "error": "unreachable"}
                if self.failing
                else {"registry_url": url, "success": True, "response": {"ok": True}}
            )
        return results

    async def update_listing_per_registry(self, *, listing_id, payloads):
        return [{"registry_url": url, "success": True, "response": {"ok": True}} for url in payloads]


async def test_every_publication_path_sends_a_document_the_credits_registry_admits(
    db, monkeypatch
):
    """A listing carrying the market's settlement option, as a payments-composed
    storefront publishes it: its first publication, refused by the registry, and
    the repair the next pass makes through the domain's publication candidate
    each send a document the API-credit registry's schema admits. Credits state
    no listing price, so neither carries a ``pricing`` term."""
    option = payment_option().model_dump(mode="json")
    registry = _RecordingRegistry()
    registry.failing = True
    monkeypatch.setattr(publication_module, "_make_registry_client", lambda: registry)
    monkeypatch.setattr(container_module, "resolved_marketplace_signer", _SELLER_SIGNER)
    monkeypatch.setattr(sqlite_module, "_sqlite_client", db)
    monkeypatch.setattr(
        cc_module, "build_capacity_runtime", lambda factory: _QuotaRuntime({"svc-quota": 42})
    )
    svc = ListingService(
        sqlite_client=db,
        seller_principal=SELLER_PRINCIPAL,
        settlement_composition=_PaymentComposition(option),
    )

    with settings_overrides(enable_registry_discovery=True, registry__urls=[_REGISTRY_URL]):
        result = await svc.publish_from_quota(
            resource_id="svc-quota", service_name="Acme", accepted_escrows=[]
        )
        (first,) = registry.published
        registry.failing = False
        repaired = await publication_module.converge_registries(db)

    assert repaired["repaired"] == (result["listing_id"],)
    first, repair = registry.published
    for body in (first, repair):
        assert _credits_schema_errors(body) == []
        assert body["settlement_options"] == [option]
        assert "pricing" not in body
    assert repair == first


async def test_a_published_payment_option_is_stored_as_its_json_value(db, monkeypatch):
    option = payment_option().model_dump(mode="json")
    monkeypatch.setattr(sqlite_module, "_sqlite_client", db)
    monkeypatch.setattr(
        cc_module, "build_capacity_runtime", lambda factory: _QuotaRuntime({"svc-quota": 42})
    )
    svc = ListingService(
        sqlite_client=db,
        seller_principal=SELLER_PRINCIPAL,
        settlement_composition=_PaymentComposition(option),
    )

    result = await svc.publish_from_quota(
        resource_id="svc-quota", service_name="Acme", accepted_escrows=[]
    )

    stored = await db.load_listing(listing_id=result["listing_id"])
    assert stored["settlement_options"] == [option]
    # A buyer reading the stored listing decodes the same typed option.
    assert [SettlementOption.model_validate(item) for item in stored["settlement_options"]] == [
        payment_option()
    ]
