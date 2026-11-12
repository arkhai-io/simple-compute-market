"""Asking rates through the bare-metal storefront app and its typed clients.

The real app, database, held projection state, and composition run, the loops
held from the start; publication is the administrator's step route, after a
``site-projections`` step wherever the site changed. Each site and the registry
are the in-process doubles the cycle tests use, standing where this codebase
wraps those services. A declared rate
and a storefront override are each read back as the published listing a buyer
fetches, and each refreshes the same listing in place.
"""

from __future__ import annotations

import contextlib
import copy
import dataclasses
from pathlib import Path

import httpx
import pytest
import yaml
from core_storefront.publication_runner import PublicationPayload
from jsonschema import Draft202012Validator
from market_arkhai_mediation.contract import INTERFACE as MEDIATION_INTERFACE
from market_arkhai_payments.fixtures import dispute_lifecycle
from market_core.schemas import derive_settlement_option_id
from market_deal_lifecycle.configuration import DisputeConfig, DisputeEntry
from market_identity import Ed25519Signer, TrustedIdentitySet
from market_pool_overrides import PoolOverrideClient
from market_settlement_runtime import SettlementPublicationClause
from market_storefront_kit.dispute_configuration import RegistryDisputePolicy
from storefront_client import StorefrontClient

from arkhai_bare_metal_storefront.domain_runtime import get_market_domain_contract
from arkhai_bare_metal_storefront.publication import BareMetalPublicationCycle
from arkhai_bare_metal_storefront.server import build_bare_metal_storefront_registry
from arkhai_bare_metal_storefront.settlement_composition import (
    build_bare_metal_settlement_registry,
)
from arkhai_bare_metal_storefront.site_clients import BareMetalSiteBinding
from held_loops import held_loop_controller
from test_http_system import (
    ADMIN_SIGNER,
    SELLER_SIGNER,
    _admin_client,
    _app,
    _derivation_runtime,
    _runtime,
)
from test_publication_cycle import (
    CONFIGURED_CLAUSES_RAW,
    DEFAULT_GPU_MODEL,
    REGISTRY_URL,
    RecordingRegistries,
    Site,
    member,
    pool,
    projections_over,
    Terms,
    _priced,
    _rate,
)

pytestmark = pytest.mark.asyncio

SITE = "site-a"


class _Sites:
    def __init__(self, site: Site) -> None:
        self._site = site

    def site(self, site_id: str) -> Site:
        assert site_id == SITE
        return self._site


@contextlib.asynccontextmanager
async def _storefront(
    tmp_path,
    site: Site,
    *,
    default_max_duration_seconds: int | None = 3600,
    registries: RecordingRegistries | None = None,
    build_payload: Terms | None = None,
):
    """The running app over ``site``, its database under ``tmp_path``.

    ``default_max_duration_seconds`` is the configured
    ``[pricing].default_max_duration_seconds``; the runtime reads it when it is
    composed, so a configuration change is a second storefront over the same
    database, as a restart is. ``registries`` records what the registry is
    sent, for a test that reads it; ``build_payload`` stands for the configured
    settlement terms.
    """
    registries = registries if registries is not None else RecordingRegistries()
    terms = build_payload if build_payload is not None else Terms()

    def cycle(runtime):
        return BareMetalPublicationCycle(
            sqlite_client=runtime.db,
            registry=build_bare_metal_storefront_registry(domain=get_market_domain_contract()),
            site_projections=runtime.site_projections,
            site_ids=[SITE],
            registry_client_factory=registries,
            registry_urls=(REGISTRY_URL,),
            storefront_url=runtime.storefront_url,
            seller_principal=runtime.seller_principal,
            build_payload=terms,
            default_max_duration_seconds=runtime.default_max_duration_seconds,
        )

    runtime = dataclasses.replace(
        _runtime(str(tmp_path / "storefront.db")),
        site_bindings=(
            BareMetalSiteBinding(
                site_id=SITE,
                service_peer=f"{SITE}-peer",
                authority_url="http://site-a",
            ),
        ),
        capacity_client=_Sites(site),
        # The storefront's held projection of the site, which startup loads.
        site_projections=projections_over({SITE: site}),
        loop_controller_factory=held_loop_controller,
        publication_cycle_factory=cycle,
        default_max_duration_seconds=default_max_duration_seconds,
    )
    app = _app(runtime)
    async with app.router.lifespan_context(app):
        async with StorefrontClient(
            "http://seller",
            signer=ADMIN_SIGNER,
            caller_role="admin",
            expected_publishers=TrustedIdentitySet(identities=(SELLER_SIGNER.identity,)),
            transport=httpx.ASGITransport(app=app),
        ) as admin, StorefrontClient(
            "http://seller", transport=httpx.ASGITransport(app=app)
        ) as public:
            yield admin, public


def _listing_id(report: dict) -> str:
    (published,) = [item for item in report["actions"] if item["action"] == "publish"]
    return str(published["listing_id"])


async def test_a_declared_rate_and_an_override_reach_the_listing_a_buyer_reads(tmp_path):
    site = Site(_priced(_rate("12.50")))
    async with _storefront(tmp_path, site) as (admin, public):
        listing_id = _listing_id(await admin.admin_run_lifecycle_cycle("publication"))
        declared = await public.get_listing(listing_id)

        await PoolOverrideClient(admin).put_pool_override(
            {"site_id": SITE, "pool_id": "pool-1", "offering_mode": "bare_metal",
             "asking_rates": [_rate("9.00")]}
        )
        await admin.admin_run_lifecycle_cycle("publication")
        overridden = await public.get_listing(listing_id)

        await PoolOverrideClient(admin).put_pool_override(
            {"site_id": SITE, "pool_id": "pool-1", "offering_mode": "bare_metal",
             "asking_rates": []}
        )
        await admin.admin_run_lifecycle_cycle("publication")
        withheld = await public.get_listing(listing_id)

    assert declared.listing_resource["asking_rate"] == {
        "amount": "12.50", "asset": "usd", "period": "hour",
    }
    assert overridden.listing_resource["asking_rate"]["amount"] == "9.00"
    assert "asking_rate" not in withheld.listing_resource
    assert withheld.status == "open"


#: The compute registry's own listing schema, which a bare-metal registry
#: serves and validates a publication against.
_COMPUTE_SPEC = (
    Path(__file__).resolve().parents[4] / "core/registry/src/core_registry/filter-spec.yaml"
)


def _compute_schema_errors(body: dict) -> list[str]:
    shape = yaml.safe_load(_COMPUTE_SPEC.read_text())["listing_shape"]
    return [
        f"{list(error.absolute_path)}: {error.message}"
        for error in Draft202012Validator(shape).iter_errors(body)
    ]


_OPTION_SETTLEMENT = {"schema": "arkhai.payments.v1"}


class _OneOptionTerms(Terms):
    """Configured terms publishing one rateless settlement option, standing for
    a composed mechanism: the compute schema admits no listing that offers
    neither an option nor an escrow, and the option's content is the
    mechanism's, not this domain's."""

    async def __call__(self, candidate: dict) -> PublicationPayload:
        option = {
            "option_id": derive_settlement_option_id(settlement=_OPTION_SETTLEMENT),
            "settlement": dict(_OPTION_SETTLEMENT),
        }
        return PublicationPayload(
            settlement_options=(option,), max_duration_seconds=self.max_duration_seconds
        )


async def test_every_publication_path_sends_a_document_the_compute_registry_admits(tmp_path):
    """A priced machine's first publication, which the registry refuses, and the
    repair the next step makes through the domain's publication candidate each
    send a document the compute registry's schema admits, the asking rate in
    its ``pricing`` and not in the machine's description, while the listing a
    buyer reads from the storefront keeps the rate beside the shape."""
    registries = RecordingRegistries()
    registries.failing = {("publish", REGISTRY_URL)}
    site = Site(_priced(_rate("12.50")))
    async with _storefront(
        tmp_path, site, registries=registries, build_payload=_OneOptionTerms()
    ) as (admin, public):
        listing_id = _listing_id(await admin.admin_run_lifecycle_cycle("publication"))
        # The refused first publication, then the cycle's own convergence retry.
        refused = [body for operation, _, _, body in registries.sent if operation == "publish"]
        registries.failing.clear()
        registries.sent.clear()
        repaired = await admin.admin_run_lifecycle_cycle("publication")
        (repair,) = [body for operation, _, _, body in registries.sent if operation == "publish"]
        local = await public.get_listing(listing_id)

    assert [item["listing_id"] for item in repaired["actions"] if item["action"] == "converge"] == [
        listing_id
    ]
    first = refused[0]
    for body in (*refused, repair):
        assert _compute_schema_errors(body) == []
        assert body["pricing"] == {
            "asking_rate": {"amount": "12.50", "asset": "usd", "period": "hour"},
        }
        assert "asking_rate" not in body["listing_resource"]
        assert body == first
    assert local.listing_resource["asking_rate"]["amount"] == "12.50"


def _holds(report: dict) -> set[str]:
    return {item["reason"] for item in report["actions"] if item["action"] == "hold"}


async def test_an_unreadable_rate_holds_the_listing_a_buyer_reads(tmp_path):
    """Fail closed through the running app: the step reports the hold, and the
    buyer still reads the listing as it was last published."""
    site = Site(_priced(_rate("12.50")))
    async with _storefront(tmp_path, site) as (admin, public):
        listing_id = _listing_id(await admin.admin_run_lifecycle_cycle("publication"))

        site.serve(_priced({**_rate("11.00"), "period": "month"}))
        await admin.admin_run_lifecycle_cycle("site-projections")
        report = await admin.admin_run_lifecycle_cycle("publication")
        held = await public.get_listing(listing_id)

    assert _holds(report) == {"asking_rates_unreadable"}
    assert held.status == "open"
    assert held.listing_resource["asking_rate"]["amount"] == "12.50"


async def test_a_bound_conflict_after_the_write_holds_rather_than_fails(tmp_path):
    """An override minimum accepted under one configured maximum; the storefront
    then restarts with a configured maximum below it. The next step holds the
    pool instead of publishing an unordered pair or failing the run."""
    site = Site(_priced(_rate("12.50")))
    async with _storefront(tmp_path, site, default_max_duration_seconds=10800) as (admin, _):
        listing_id = _listing_id(await admin.admin_run_lifecycle_cycle("publication"))
        await PoolOverrideClient(admin).put_pool_override(
            {"site_id": SITE, "pool_id": "pool-1", "offering_mode": "bare_metal",
             "terms": {"min_duration_seconds": 7200}}
        )

    async with _storefront(tmp_path, site, default_max_duration_seconds=3600) as (
        admin,
        public,
    ):
        report = await admin.admin_run_lifecycle_cycle("publication")
        held = await public.get_listing(listing_id)

    assert _holds(report) == {"pool_override_terms_conflict"}
    assert held.status == "open"
    assert "min_duration_seconds" not in held.listing_resource


@contextlib.asynccontextmanager
async def _composed(tmp_path, monkeypatch, site: Site, **changes):
    """The running app over ``site``, each cycle composed from the runtime as
    production composes it, under the configured Alkahest settlement."""
    app = _app(_derivation_runtime(tmp_path, monkeypatch, {SITE: site}, **changes))
    async with app.router.lifespan_context(app):
        async with _admin_client(app) as admin:
            yield admin


async def test_a_reserved_option_publishes_with_no_relative_maximum(tmp_path, monkeypatch):
    """With no maximum lease duration from any tier, the pool is not held: its
    listing publishes its reserved escrow with no relative maximum. Spec
    scenarios "A bare-metal pool states no maximum duration" (its publication
    half) and "A bare-metal pool resolves no lease bound"."""
    site = Site(pool("pool-1", member("r1", "pool-1")))
    async with _composed(tmp_path, monkeypatch, site, default_max_duration_seconds=None) as admin:
        report = await admin.admin_run_lifecycle_cycle("publication")
        listing = await admin.get_listing(_listing_id(report))

    assert _holds(report) == set()
    assert listing.status == "open"
    assert listing.max_duration_seconds is None
    assert listing.extra["accepted_escrows"]


async def test_pool_level_clauses_publish_below_a_model_hint(tmp_path, monkeypatch):
    """With no configured clause, a pool's ``pricing.settlements`` hint publishes
    its clauses for each machine whose GPU model has no hint of its own, while a
    model hint -- here an empty list, which withholds every option -- wins for
    its model's machine. Spec scenarios "A bare-metal pool states pool-level
    clauses" and "A pool-level hint below a model hint"."""
    site = Site(pool(
        "pool-1",
        member("r1", "pool-1"),
        member("r2", "pool-1", attributes={"gpu_model": "A100"}),
        policy_tags={"pricing": {
            "settlements": list(CONFIGURED_CLAUSES_RAW),
            "gpu": {DEFAULT_GPU_MODEL: {"settlements": []}},
        }},
    ))
    async with _composed(tmp_path, monkeypatch, site, publication_clauses=()) as admin:
        report = await admin.admin_run_lifecycle_cycle("publication")
        listing = await admin.get_listing(_listing_id(report))

    assert listing.listing_resource["gpu_model"] == "A100"
    assert listing.extra["accepted_escrows"]
    refused = [item for item in report["actions"] if item["action"] == "refuse"]
    assert [(item["physical_resource_id"], item["reason"]) for item in refused] == [
        ("r1", "no_settlement_option")
    ]


_HINT_END = "2035-01-02T00:00:00Z"
_OVERRIDE_END = "2035-01-01T00:00:00Z"
_DEFAULT_END = "2035-01-03T00:00:00Z"


async def test_each_capacity_bound_resolves_from_its_own_tier_onto_the_published_listing(
    tmp_path, monkeypatch,
):
    """An override stating only the availability end replaces the hint's end and
    keeps its relative bound; both travel as top-level listing terms, never in the
    listing resource. A malformed hint holds the listing as it stood, reporting
    its bounds unreadable, rather than guessing a default."""
    hinted = pool("pool-1", member("r1", "pool-1"), policy_tags={"capacity_bounds": {
        "bare_metal": {"max_duration_seconds": 7200, "available_until_utc": _HINT_END},
    }})
    site = Site(hinted)
    runtime = _derivation_runtime(
        tmp_path, monkeypatch, {SITE: site},
        default_max_duration_seconds=86400, default_available_until_utc=_DEFAULT_END,
        capacity_client=_Sites(site),
    )
    app = _app(runtime)
    async with app.router.lifespan_context(app):
        async with _admin_client(app) as admin:
            listing_id = _listing_id(await admin.admin_run_lifecycle_cycle("publication"))
            declared = await admin.get_listing(listing_id)

            await PoolOverrideClient(admin).put_pool_override({
                "site_id": SITE, "pool_id": "pool-1", "offering_mode": "bare_metal",
                "terms": {"available_until_utc": _OVERRIDE_END},
            })
            await admin.admin_run_lifecycle_cycle("publication")
            overridden = await admin.get_listing(listing_id)
            sent = runtime.registry_configuration.recording.sent[-1][3]

            broken = copy.deepcopy(hinted)
            broken["pool_metadata"]["policy_tags"]["capacity_bounds"]["bare_metal"][
                "available_until_utc"
            ] = "not-a-date"
            site.serve(broken)
            await admin.admin_run_lifecycle_cycle("site-projections")
            held = await admin.admin_run_lifecycle_cycle("publication")
            after = await admin.get_listing(listing_id)

    assert (declared.max_duration_seconds, declared.extra["available_until_utc"]) == (7200, _HINT_END)
    assert (overridden.max_duration_seconds, overridden.extra["available_until_utc"]) == (
        7200, _OVERRIDE_END,
    )
    assert sent["available_until_utc"] == _OVERRIDE_END
    assert "available_until_utc" not in sent["listing_resource"]
    assert "max_duration_seconds" not in sent["listing_resource"]
    assert any(item.get("reason") == "capacity_bounds_unreadable" for item in held["actions"])
    assert after == overridden


# A once payment option's delivery deadline, through the running app's settlement
# composition with Arkhai payments added to its configuration: the real registry
# resolves the seller's payments configuration, its once builder builds the
# option, and a dispute authority is configured. No rate servicing is declared,
# no recurring encoder is installed, and the pool port supplies no deadline, as in
# every deployed composition, so the deadline can come only from the clause. Every
# account, key and address here is a deterministic development value; none may be
# used on a public network.

_PAYMENTS = "arkhai.payments.v1"
_PAYEE = "22222222-2222-4222-8222-222222222222"
_PAYMENTS_SERVICE = Ed25519Signer(bytes(range(1, 33)))
_DISPUTE_ENTRY = DisputeEntry.model_validate({
    **dispute_lifecycle("33333333-3333-4333-8333-333333333333")["adjudication"]["dispute"],
    "interface": MEDIATION_INTERFACE,
    "advertisement": {
        "mechanisms": [_PAYMENTS],
        "minimum_dispute_window_seconds": 60,
        "minimum_case_hold_seconds": None,
    },
})


def _payments_settlement(alkahest: dict) -> dict:
    return {
        "schema_version": 1,
        "priority": ["alkahest.v1", _PAYMENTS],
        "alkahest": alkahest,
        "arkhai_payments": {
            "enabled": True,
            "service_url": "http://127.0.0.1:9",
            "service_identity": _PAYMENTS_SERVICE.identity.model_dump(mode="json"),
            "fee_bps": 250,
            "development_auth": True,
        },
    }


def _once_payment_clause(delivery_deadline_seconds: int | None) -> SettlementPublicationClause:
    return SettlementPublicationClause.model_validate({
        "mechanism": _PAYMENTS,
        "asset": "USD/6",
        "rate": "2.5",
        "per": "hour",
        "mechanism_input": {
            "asset": "USD/6",
            "payee_account": _PAYEE,
            "window": "PT5M",
            "dispute_window_seconds": 604800,
            **({"delivery_deadline_seconds": delivery_deadline_seconds}
               if delivery_deadline_seconds is not None else {}),
        },
    })


@pytest.mark.parametrize(("clause_deadline", "refused"), [(900, 0), (None, 1)],
                         ids=["clause-configured", "neither"])
async def test_a_once_payment_option_publishes_its_clause_s_deadline_where_the_pool_supplies_none(
    tmp_path, monkeypatch, clause_deadline, refused,
):
    """With no pool deadline, a once payment option publishes the deadline its
    clause configures and no default buyer's refusal is reported; a clause
    configuring none publishes no deadline, and the option is reported as refused
    by a default buyer for lacking one."""
    site = Site(pool("pool-1", member("r1", "pool-1")))
    runtime = _derivation_runtime(tmp_path, monkeypatch, {SITE: site}, capacity_client=_Sites(site))
    configured = runtime.settlement_composition
    registry = build_bare_metal_settlement_registry()
    settlement = _payments_settlement(configured.config.mechanisms["alkahest"].model_dump(mode="json"))
    runtime = dataclasses.replace(
        runtime,
        settlement_composition=dataclasses.replace(
            configured,
            registry=registry,
            config=registry.resolve(settlement, role="seller"),
            disputes=RegistryDisputePolicy(DisputeConfig(entries=[_DISPUTE_ENTRY])),
        ),
        publication_clauses=(*runtime.publication_clauses, _once_payment_clause(clause_deadline)),
    )
    app = _app(runtime)
    async with app.router.lifespan_context(app):
        async with _admin_client(app) as admin:
            report = await admin.admin_run_lifecycle_cycle("publication")
            published = (await admin.get_listing(_listing_id(report))).extra["settlement_options"]

    (payment,) = [option for option in published if option["settlement"]["schema"] == _PAYMENTS]
    assert "period" not in payment["settlement"]
    assert payment["lifecycle"].get("delivery_deadline_seconds") == clause_deadline
    refusals = [item for item in report["actions"] if item.get("reason") == "default_buyer_refusal"]
    assert len(refusals) == refused
    assert all(item["detail"].endswith("no delivery deadline") for item in refusals)
