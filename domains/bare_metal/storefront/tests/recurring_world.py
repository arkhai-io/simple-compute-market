"""A bare-metal storefront that publishes recurring payment options, for tests.

No deployed composition declares rate servicing or installs a recurring preset
helper, so recurring options are dark in production. This world composes the
real settlement composition over the running app with the pieces a deployment
would supply injected in their place: a servicing declaration, a fixture preset
helper standing where the payment mechanism's encoder would, the mechanism's term
timing, and the pool's delivery deadline. Publication and negotiation then run
through the app and its typed clients exactly as they would with those pieces
installed.

Every account, key and address here is a deterministic development value; none
may be used on a public network.
"""

from __future__ import annotations

import contextlib
import dataclasses
import math
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any

import httpx
from market_arkhai_mediation.contract import INTERFACE as MEDIATION_INTERFACE
from market_arkhai_payments.fixtures import dispute_lifecycle
from market_core.schemas import (
    AgreedPrice,
    RateValue,
    SettlementOption,
    SettlementPrice,
    derive_settlement_option_id,
)
from market_deal_lifecycle.configuration import DisputeConfig, DisputeEntry
from market_deal_lifecycle.terms import Adjudication, TermContext, encode_terms
from market_identity import Ed25519Signer, TrustedIdentitySet
from market_settlement_runtime import SettlementPublicationClause
from market_settlement_runtime.horizon import RateTermTiming
from market_settlement_runtime.rate_publication import (
    DEFAULT_PREMATURE_STOP_PENALTY_PERIODS,
    RatePresetPricing,
)
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
from test_http_system import SELLER_SIGNER, _admin_client, _app, _derivation_runtime
from test_publication_cycle import Site, member, pool

MECHANISM = "arkhai.payments.v1"
PAYEE = "22222222-2222-4222-8222-222222222222"
_DISPUTE_ACCOUNT = "33333333-3333-4333-8333-333333333333"
_PAYMENTS_SERVICE = Ed25519Signer(bytes(range(1, 33)))
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


def _context() -> TermContext:
    return TermContext(
        mechanism=MECHANISM,
        has_adapter=True,
        dispute_interfaces=frozenset({DISPUTE_ENTRY.interface}),
        authority=DISPUTE_ENTRY.requirements,
        supported_partial_periods=QUALIFIED,
    )


class FixtureRateHelper:
    """Stands where the payment mechanism's recurring encoder would.

    It prices a clause's hourly rate per period, rounding up, and encodes the
    option the way the mechanism's builder would.
    """

    def pricing(self, clause: Any, authorities: Any) -> RatePresetPricing:
        hourly = Fraction(Decimal(clause.rate)) * 10**6
        return RatePresetPricing(
            quote=AgreedPrice(
                unit="per_period",
                period=clause.recurring.period,
                period_seconds=PERIOD_SECONDS,
                amount=math.ceil(hourly * PERIOD_SECONDS / 3600),
                asset=clause.asset,
            ),
            approval_window_seconds=APPROVAL_WINDOW_SECONDS,
            adjudication=Adjudication(
                version=1,
                dispute=DISPUTE_ENTRY.authority,
                dispute_window_seconds=604800,
                case_hold_max_seconds=None,
            ),
            context=_context(),
        )

    def build(self, request: Any) -> SettlementOption:
        price = SettlementPrice(asset=request.quote.asset, rates=[
            RateValue(field="amount", per="hour",
                      value=int(Decimal(request.clause.rate) * 10**6)),
        ])
        settlement = {
            "schema": request.clause.mechanism,
            "payee_account": PAYEE,
            "window": "PT5M",
            "deposit_agreement": False,
            "period": request.preset.period,
            "reserve_ahead_seconds": request.preset.reserve_ahead_seconds,
        }
        lifecycle = encode_terms(request.lifecycle)
        return SettlementOption(
            option_id=derive_settlement_option_id(
                price=price, settlement=settlement, lifecycle=lifecycle
            ),
            price=price,
            settlement=settlement,
            lifecycle=lifecycle,
        )


def term_timing(_option: Any) -> RateTermTiming:
    """The mechanism's period and approval window for a recurring option."""
    return RateTermTiming(
        PERIOD_SECONDS, APPROVAL_WINDOW_SECONDS,
        dataclasses.replace(_context(), has_stoppable_part=True),
    )


def payment_clause(rate: str = "2.5", *, recurring: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """One payments publication clause, recurring when ``recurring`` is given."""
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
        },
        **({"recurring": dict(recurring)} if recurring is not None else {}),
    }


_PAYER = {"period": PERIOD, "reserve_ahead_seconds": 1800}


def payment_clauses() -> list[dict[str, Any]]:
    """A once payment, an on-demand and a spot preset."""
    return [
        payment_clause(),
        payment_clause(recurring=_PAYER),
        payment_clause("1.5", recurring={**_PAYER, "payee_notice_seconds": 120}),
    ]


def _settlement_root(alkahest: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "priority": ["alkahest.v1", MECHANISM],
        "alkahest": dict(alkahest),
        "arkhai_payments": {
            "enabled": True,
            "service_url": "http://127.0.0.1:9",
            "service_identity": _PAYMENTS_SERVICE.identity.model_dump(mode="json"),
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
    #: The composition's declarations, by mechanism. The composition reads them at
    #: each door, so a test that changes them between publication and acceptance
    #: stands for a storefront restarted under a different declaration.
    declarations: dict[str, RateServicingDeclaration]

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
) -> AsyncIterator[RecurringWorld]:
    """The running bare-metal app over one bounded pool, publishing the configured
    Alkahest clause beside the three payment clauses of ``payment_clauses``.

    ``treatments`` is the payments declaration the composition starts with;
    ``None`` declares none, as a deployed composition does.
    ``default_penalty_periods`` is the composition's configured penalty multiple.
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
            rate_servicing=RateServicing(declarations),
            rate_preset_helpers={MECHANISM: FixtureRateHelper()},
            rate_term_projections={MECHANISM: term_timing},
            delivery_deadline_for_pool=lambda _site, _pool: DELIVERY_DEADLINE_SECONDS,
            default_penalty_periods=default_penalty_periods,
        )
        clauses = [
            *(clause.model_dump(mode="json", exclude_none=True) for clause in runtime.publication_clauses),
            *payment_clauses(),
        ]
        runtime = dataclasses.replace(
            runtime,
            settlement_composition=composition,
            publication_clauses=tuple(
                SettlementPublicationClause.model_validate(clause) for clause in clauses
            ),
        )
        app = _app(runtime)
        async with app.router.lifespan_context(app):
            async with _admin_client(app) as admin, StorefrontClient(
                "http://seller",
                signer=BUYER_SIGNER,
                caller_role="buyer",
                expected_publishers=TrustedIdentitySet(identities=(SELLER_SIGNER.identity,)),
                transport=httpx.ASGITransport(app=app),
            ) as buyer:
                world = RecurringWorld(admin, buyer, runtime.db, declarations)
                world.declare(treatments)
                yield world
