"""A bare-metal storefront that publishes recurring payment options, for tests.

This world composes the real settlement composition over the running app with
what the composition installs itself: the payments kit's recurring preset helper
and term timing, and the payments seller stage built over the composition's own
servicing declaration. Only what a deployment configures is supplied here: the
servicing declaration, the penalty multiple, and the pool's delivery deadline.
Publication and negotiation then run through the app and its typed clients.

Every account, key and address here is a deterministic development value; none
may be used on a public network.
"""

from __future__ import annotations

import contextlib
import dataclasses
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from market_arkhai_mediation.contract import INTERFACE as MEDIATION_INTERFACE
from market_arkhai_payments.fixtures import FakePaymentsClient, dispute_lifecycle
from market_deal_lifecycle.configuration import DisputeConfig, DisputeEntry
from market_deal_lifecycle_client import LifecycleClient
from market_identity import Ed25519Signer, TrustedIdentitySet
from market_settlement_runtime import SettlementPublicationClause
from market_settlement_runtime.rate_publication import DEFAULT_PREMATURE_STOP_PENALTY_PERIODS
from market_settlement_runtime.rate_servicing import (
    RateServicing,
    RateServicingDeclaration,
)
from market_storefront_kit.dispute_configuration import RegistryDisputePolicy
from pytest import MonkeyPatch
from storefront_client import StorefrontClient

from arkhai_bare_metal_storefront.settlement_composition import (
    build_bare_metal_settlement_registry,
)
from loopback import serving
from test_http_system import ADMIN_SIGNER, SELLER_SIGNER, _admin_client, _app, _derivation_runtime
from test_publication_cycle import Site, member, pool

MECHANISM = "arkhai.payments.v1"
PAYEE = "22222222-2222-4222-8222-222222222222"
_DISPUTE_ACCOUNT = "33333333-3333-4333-8333-333333333333"
#: The payments service's receipt and snapshot signer.
PAYMENTS_SERVICE = Ed25519Signer(bytes(range(1, 33)))
#: The buyer's request signer.
BUYER_SIGNER = Ed25519Signer(bytes(range(2, 34)))
SITE = "site-a"
POOL_ID = "pool-1"
#: The pool's absolute availability bound. Publication and acceptance read the
#: wall clock, so this holds only until 2035; until then the relative bound is
#: the one that limits the default horizon.
AVAILABLE_UNTIL = "2035-01-01T00:00:00Z"
MAX_DURATION_SECONDS = 7200
DELIVERY_DEADLINE_SECONDS = 1200
PERIOD = "PT15M"
PERIOD_SECONDS = 900
#: The approval window each payment clause configures, ``PT5M``.
APPROVAL_WINDOW_SECONDS = 300
#: Both treatments the recurring presets name: the payer's stop charges its
#: started period, and the payee's stop and the term end return the last one.
QUALIFIED = frozenset({"charged", "returned"})

DISPUTE_ENTRY = DisputeEntry.model_validate({
    **dispute_lifecycle(_DISPUTE_ACCOUNT)["adjudication"]["dispute"],
    "interface": MEDIATION_INTERFACE,
    "advertisement": {
        "mechanisms": [MECHANISM],
        "minimum_dispute_window_seconds": 60,
        "minimum_case_hold_seconds": None,
    },
})


def payment_clause(
    rate: str = "2.5",
    *,
    recurring: Mapping[str, Any] | None = None,
    delivery_deadline_seconds: int | None = None,
) -> dict[str, Any]:
    """One payments publication clause, recurring when ``recurring`` is given,
    configuring ``delivery_deadline_seconds`` when it is given."""
    return {
        "mechanism": MECHANISM,
        "asset": "USD/6",
        "rate": rate,
        "per": "hour",
        "mechanism_input": {
            "asset": "USD/6",
            "payee_account": PAYEE,
            "window": "PT5M",
            "dispute_window_seconds": 604800,
            **({"delivery_deadline_seconds": delivery_deadline_seconds}
               if delivery_deadline_seconds is not None else {}),
        },
        **({"recurring": dict(recurring)} if recurring is not None else {}),
    }


_PAYER = {"period": PERIOD, "reserve_ahead_seconds": 1800}


def payment_clauses(*, delivery_deadline_seconds: int | None = None) -> list[dict[str, Any]]:
    """A once payment, an on-demand and a spot preset, each configuring
    ``delivery_deadline_seconds`` when it is given."""
    deadline = {"delivery_deadline_seconds": delivery_deadline_seconds}
    return [
        payment_clause(**deadline),
        payment_clause(recurring=_PAYER, **deadline),
        payment_clause("1.5", recurring={**_PAYER, "payee_notice_seconds": 120}, **deadline),
    ]


def _settlement_root(alkahest: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "priority": ["alkahest.v1", MECHANISM],
        "alkahest": dict(alkahest),
        "arkhai_payments": {
            "enabled": True,
            "service_url": "http://127.0.0.1:9",
            "service_identity": PAYMENTS_SERVICE.identity.model_dump(mode="json"),
            "fee_bps": 250,
            "development_auth": True,
        },
    }


class _OneSite:
    """The capacity client over the world's one site."""

    def __init__(self, site: Site) -> None:
        self._site = site

    def site(self, site_id: str) -> Site:
        assert site_id == SITE
        return self._site


@dataclass
class RecurringWorld:
    admin: StorefrontClient
    buyer: StorefrontClient
    db: Any
    #: The composition's declarations, by mechanism. Publication, acceptance and
    #: the payments stage read them at each door, so a test that changes them
    #: between publication and acceptance stands for a storefront restarted under
    #: a different declaration.
    declarations: dict[str, RateServicingDeclaration]
    #: The buyer's typed client of the app's lifecycle routes.
    buyer_lifecycle: LifecycleClient
    #: The app's loopback base URL when it is served, for a buyer's own commands.
    url: str | None = None

    def declare(self, treatments: frozenset[str] | None, *, setup: bool = False) -> None:
        """Declare ``treatments`` for payments, or withdraw its declaration."""
        self.declarations.clear()
        if treatments is not None:
            self.declarations[MECHANISM] = RateServicingDeclaration(MECHANISM, treatments, setup)

    async def publish(self) -> dict[str, Any]:
        """Run one publication cycle and return its report."""
        return await self.admin.admin_run_lifecycle_cycle("publication")


def undeclared(report: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """The cycle's refusals for undeclared rate servicing."""
    return [item for item in report["actions"] if item.get("reason") == "rate_servicing_undeclared"]


@contextlib.asynccontextmanager
async def recurring_world(
    tmp_path: Path,
    *,
    treatments: frozenset[str] | None = QUALIFIED,
    default_penalty_periods: int = DEFAULT_PREMATURE_STOP_PENALTY_PERIODS,
    pool_deadline: int | None = DELIVERY_DEADLINE_SECONDS,
    clause_deadline: int | None = None,
    payments: FakePaymentsClient | None = None,
    clock: Callable[[], int] | None = None,
    serve: bool = False,
) -> AsyncIterator[RecurringWorld]:
    """The running bare-metal app over one bounded pool, publishing the configured
    Alkahest clause beside the three payment clauses of ``payment_clauses``.

    ``treatments`` is the payments declaration the composition starts with;
    ``None`` declares none, as a composition configuring no
    ``[Settlement].rate_servicing`` does. ``default_penalty_periods`` is the
    composition's configured penalty multiple. ``pool_deadline`` is the pool's
    effective delivery deadline, ``None`` where the pool supplies none, as in a
    deployed composition, which wires no pool port; ``clause_deadline`` is the one
    each payment clause configures. ``payments`` is the payments service the
    composition's stage reads receipts and snapshots from, the in-process
    engine a buyer approves at, so a deal can settle through the app; a test
    restarting the app over the same ``tmp_path`` passes the same one, since the
    payments service outlives a storefront restart. ``clock`` is the runtime's
    lifecycle clock, wall time unless given. ``serve`` runs the app on a
    loopback port, its lifespan uvicorn's, so a buyer's own commands reach it
    over HTTP; the world's clients then use that port too.
    """
    declarations: dict[str, RateServicingDeclaration] = {}
    site = Site(pool(POOL_ID, member("r1", POOL_ID), policy_tags={"capacity_bounds": {
        "bare_metal": {
            "max_duration_seconds": MAX_DURATION_SECONDS,
            "available_until_utc": AVAILABLE_UNTIL,
        },
    }}))
    with MonkeyPatch.context() as patches:
        runtime = _derivation_runtime(tmp_path, patches, {SITE: site}, capacity_client=_OneSite(site))
        configured = runtime.settlement_composition
        registry = build_bare_metal_settlement_registry()
        root = _settlement_root(configured.config.mechanisms["alkahest"].model_dump(mode="json"))
        composition = dataclasses.replace(
            configured,
            registry=registry,
            config=registry.resolve(root, role="seller"),
            disputes=RegistryDisputePolicy(DisputeConfig(entries=[DISPUTE_ENTRY])),
            # One declaration object for every door: publication, acceptance and
            # the payments stage the composition builds over it.
            rate_servicing=RateServicing(declarations),
            # Reinstalled over this composition's dispute policy: the configured
            # composition's wiring reads the authorities it was built with.
            rate_preset_helpers=None,
            rate_term_projections=None,
            delivery_deadline_for_pool=lambda _site, _pool: pool_deadline,
            default_penalty_periods=default_penalty_periods,
            payments_client_for_owner=payments,
        )
        clauses = [
            *(clause.model_dump(mode="json", exclude_none=True) for clause in runtime.publication_clauses),
            *payment_clauses(delivery_deadline_seconds=clause_deadline),
        ]
        runtime = dataclasses.replace(
            runtime,
            settlement_composition=composition,
            publication_clauses=tuple(
                SettlementPublicationClause.model_validate(clause) for clause in clauses
            ),
            **({"lifecycle_clock": clock} if clock is not None else {}),
        )
        app = _app(runtime)
        publisher = TrustedIdentitySet(identities=(SELLER_SIGNER.identity,))
        if serve:
            with serving(app) as url:
                async with StorefrontClient(
                    url, signer=ADMIN_SIGNER, caller_role="admin", expected_publishers=publisher,
                ) as admin, StorefrontClient(
                    url, signer=BUYER_SIGNER, caller_role="buyer", expected_publishers=publisher,
                ) as buyer, LifecycleClient(url, BUYER_SIGNER, publisher) as buyer_lifecycle:
                    world = RecurringWorld(admin, buyer, runtime.db, declarations, buyer_lifecycle, url)
                    world.declare(treatments)
                    yield world
            return
        async with app.router.lifespan_context(app):
            async with _admin_client(app) as admin, StorefrontClient(
                "http://seller",
                signer=BUYER_SIGNER,
                caller_role="buyer",
                expected_publishers=publisher,
                transport=httpx.ASGITransport(app=app),
            ) as buyer, LifecycleClient(
                "http://seller", BUYER_SIGNER, publisher,
                transport=httpx.ASGITransport(app=app),
            ) as buyer_lifecycle:
                world = RecurringWorld(admin, buyer, runtime.db, declarations, buyer_lifecycle)
                world.declare(treatments)
                yield world
