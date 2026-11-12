"""A VM storefront that publishes recurring payment options, for integration tests.

No deployed composition declares rate servicing or installs a recurring preset
helper, so recurring options are dark in production. This world composes the real
``VmSettlementComposition`` over the publication harness with the pieces a
deployment would supply injected in their place: a servicing declaration, a
fixture preset helper standing where the payment mechanism's encoder would, the
mechanism's term timing and billing projection, and the pool's delivery deadline.
Publication and negotiation then run through the served storefront and its typed
client exactly as they would with those pieces installed.

Every account, key and address here is a deterministic development value; none
may be used on a public network.
"""

from __future__ import annotations

import contextlib
import json
import math
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field, replace
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from market_arkhai_mediation.contract import INTERFACE as MEDIATION_INTERFACE
from market_arkhai_payments.fixtures import dispute_lifecycle
from market_core.schemas import (
    AgreedPrice,
    PriceBasis,
    RateValue,
    SettlementOption,
    SettlementPrice,
    derive_settlement_option_id,
)
from market_deal_lifecycle.configuration import DisputeConfig, DisputeEntry
from market_deal_lifecycle.terms import Adjudication, TermContext, encode_terms
from market_identity import Ed25519Signer
from market_settlement_runtime.horizon import RateTermTiming
from market_settlement_runtime.rate_publication import RatePresetPricing
from market_settlement_runtime.rate_servicing import (
    RateServicing,
    RateServicingDeclaration,
)
from market_storefront_kit.dispute_configuration import RegistryDisputePolicy

from market_storefront.domain_runtime import build_vm_storefront_domain
from market_storefront.settlement_composition import (
    VmSettlementComposition,
    build_storefront_settlement_registry,
)
from market_storefront.utils import config as storefront_config
from tests._settings_overrides import replaced_setting
from tests.publication_app import (
    SELLER_WALLET,
    SETTLEMENT,
    PublicationApp,
    pool,
    publication_app,
    settlement_clause,
)

MECHANISM = "arkhai.payments.v1"
PAYEE = "22222222-2222-4222-8222-222222222222"
_DISPUTE_ACCOUNT = "33333333-3333-4333-8333-333333333333"
_PAYMENTS_SERVICE = Ed25519Signer(bytes(range(1, 33)))
#: The pool's absolute availability bound. Publication and acceptance read the
#: wall clock, so this holds only until 2035; until then the relative bound is
#: the one that limits the default horizon.
AVAILABLE_UNTIL = "2035-01-01T00:00:00Z"
#: The pool's relative bound, which limits the default horizon.
MAX_DURATION_SECONDS = 7200
#: The delivery deadline the pool port reports.
DELIVERY_DEADLINE_SECONDS = 1200
PERIOD = "PT15M"
PERIOD_SECONDS = 900
APPROVAL_WINDOW_SECONDS = 300
#: Both treatments the recurring presets name: the payer's stop charges its
#: started period, and the payee's stop and the term end return the last one.
QUALIFIED = frozenset({"charged", "returned"})
POOL_ID = "bounded"
#: The hourly H100 family rate of a shape-priced pool.
SHAPE_RATE = "2.5"
#: The family rates that make the pool's listing shape-priced.
SHAPE_PRICING = {"gpu": {"H100": {"rates": [{"asset": "USD/6", "rate": SHAPE_RATE, "per": "hour"}]}}}

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
    option the way the mechanism's builder would. A shape-priced listing's clause
    states no rate, its rate coming from the pool's family rates; it is quoted at
    ``SHAPE_RATE``, the one family rate the shape-priced tests set.
    """

    def pricing(self, clause: Any, authorities: Any) -> RatePresetPricing:
        hourly = Fraction(Decimal(clause.rate or SHAPE_RATE)) * 10**6
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
        rate = request.clause.rate
        price = SettlementPrice(asset=request.quote.asset, rates=[
            RateValue(field="amount", per="hour", value=int(Decimal(rate) * 10**6)),
        ] if rate is not None else [])
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
        PERIOD_SECONDS, APPROVAL_WINDOW_SECONDS, replace(_context(), has_stoppable_part=True),
    )


def billing(_option: Any) -> PriceBasis:
    """The mechanism's billing projection: one period of a recurring option."""
    return PriceBasis(unit="per_period", period=PERIOD, period_seconds=PERIOD_SECONDS)


class AcceptedDataPlaceholder:
    """Accepted payment data with nothing in it.

    It stands for the mechanism's seller stage at acceptance, so an Agreement can
    be signed; it is deliberately no authority or mandate adapter.
    """

    def settlement_data(self, _agreement: Any) -> Any:
        return SimpleNamespace(to_wire=lambda: {})


def payment_clause(
    rate: str | None = "2.5", *, recurring: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """One payments publication clause, recurring when ``recurring`` is given,
    stating no rate of its own when ``rate`` is ``None``."""
    return {
        "mechanism": MECHANISM,
        "asset": "USD/6",
        **({"rate": rate, "per": "hour"} if rate is not None else {}),
        "mechanism_input": {
            "asset": "USD/6",
            "payee_account": PAYEE,
            "window": "PT5M",
            "dispute_window_seconds": 604800,
        },
        **({"recurring": dict(recurring)} if recurring is not None else {}),
    }


_PAYER = {"period": PERIOD, "reserve_ahead_seconds": 1800}


def clauses() -> list[dict[str, Any]]:
    """A reserved Alkahest clause, a once payment, an on-demand and a spot preset."""
    return [
        settlement_clause("1"),
        payment_clause(),
        payment_clause(recurring=_PAYER),
        payment_clause("1.5", recurring={**_PAYER, "payee_notice_seconds": 120}),
    ]


def _settlement_root() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "priority": ["alkahest.v1", MECHANISM],
        "alkahest": {**SETTLEMENT["alkahest"], "release_models": ["recipient"]},
        "arkhai_payments": {
            "enabled": True,
            "service_url": "http://127.0.0.1:9",
            "service_identity": _PAYMENTS_SERVICE.identity.model_dump(mode="json"),
            "fee_bps": 250,
            "development_auth": True,
        },
    }


def _token_cache(path: Path) -> str:
    """The token cache payments readiness reads the development chain's asset from."""
    directory = path / "cache"
    tokens = directory / "arkhai" / "tokens"
    tokens.mkdir(parents=True, exist_ok=True)
    token = "0x" + "22" * 20
    (tokens / "31337.json").write_text(json.dumps({
        token: {"symbol": "USDC", "contract_address": token, "decimals": 6, "chain_id": 31337},
    }))
    return str(directory)


@dataclass
class RecurringWorld:
    app: PublicationApp
    helper: FixtureRateHelper
    #: The composition's declarations, by mechanism. The composition reads them at
    #: each door, so a test that changes them between publication and acceptance
    #: stands for a storefront restarted under a different declaration.
    declarations: dict[str, RateServicingDeclaration] = field(default_factory=dict)

    def declare(self, treatments: frozenset[str] | None, *, setup: bool = False) -> None:
        """Declare ``treatments`` for payments, or withdraw its declaration."""
        self.declarations.clear()
        if treatments is not None:
            self.declarations[MECHANISM] = RateServicingDeclaration(MECHANISM, treatments, setup)

    async def publish(self) -> dict[str, Any]:
        """Poll the site, run one publication cycle, and return its report."""
        await self.app.client.admin_run_lifecycle_cycle("site-projections")
        return await self.app.client.admin_run_lifecycle_cycle("publication")


def undeclared(report: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """The cycle's refusals for undeclared rate servicing."""
    return [item for item in report["actions"] if item.get("reason") == "rate_servicing_undeclared"]


@contextlib.asynccontextmanager
async def recurring_world(
    tmp_path: Path,
    *,
    treatments: frozenset[str] | None = QUALIFIED,
    pricing: Mapping[str, Any] | None = None,
    published: list[dict[str, Any]] | None = None,
) -> AsyncIterator[RecurringWorld]:
    """The VM storefront with one bounded pool publishing ``published``, by
    default the four clauses of ``clauses``.

    ``treatments`` is the payments declaration the composition starts with;
    ``None`` declares none, as a deployed composition does. ``pricing`` is the
    pool's family rates, which make its listing shape-priced.
    """
    helper = FixtureRateHelper()
    declarations: dict[str, RateServicingDeclaration] = {}
    root = _settlement_root()

    def composition(_fulfillment: Mapping[str, bool]) -> VmSettlementComposition:
        registry = build_storefront_settlement_registry()
        return VmSettlementComposition(
            domain=build_vm_storefront_domain(),
            repository=None,
            runtime=None,
            coordinator=None,
            worker=None,
            local_principal=_PAYMENTS_SERVICE.identity,
            mechanism_clients={},
            evidence_clients={},
            configuration_registry=registry,
            settlement_config=registry.resolve(root, role="seller"),
            mechanism_resources={
                "wallet": SELLER_WALLET,
                "chains": dict(storefront_config.CHAINS),
                "clients": {"anvil": object()},
            },
            disputes=RegistryDisputePolicy(DisputeConfig(entries=[DISPUTE_ENTRY])),
            rate_servicing=RateServicing(declarations),
            rate_preset_helpers={MECHANISM: helper},
            rate_term_projections={MECHANISM: term_timing},
            delivery_deadline_for_pool=lambda _site, _pool: DELIVERY_DEADLINE_SECONDS,
        )

    with patch.dict("os.environ", {"XDG_CACHE_HOME": _token_cache(tmp_path)}), \
            replaced_setting("pricing.defaults", {}):
        async with publication_app(
            tmp_path,
            negotiation=True,
            settlement_configuration=root,
            settlement_composition_factory=composition,
            negotiation_options={
                "project_billing": billing,
                "arkhai_payments_stage": AcceptedDataPlaceholder(),
                "accepted_obligation_dispatch": {MECHANISM: None},
            },
        ) as app:
            app.set_settlement_clauses(published if published is not None else clauses())
            app.pools.append(pool(
                POOL_ID, backing="backed",
                **({"pricing": dict(pricing)} if pricing is not None else {}),
                capacity_bounds={"vm": {
                    "max_duration_seconds": MAX_DURATION_SECONDS,
                    "available_until_utc": AVAILABLE_UNTIL,
                }},
            ))
            world = RecurringWorld(app, helper, declarations)
            world.declare(treatments)
            await app.client.get_system_status()
            yield world
