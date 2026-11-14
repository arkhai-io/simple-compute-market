"""A VM storefront that publishes recurring payment options, for integration tests.

This world composes the real ``VmSettlementComposition`` over the publication
harness. The composition installs the payments kit's recurring preset helper and
term timing itself, and the negotiation runtime projects billing through the
settlement registry by default. The composition builds no payments seller stage of
its own, so the world builds one with ``servicing_stage`` over the composition's
servicing declaration, as ``build_vm_settlement_composition`` does. Beyond that,
the world supplies only what a deployment configures: the servicing declaration,
the penalty multiple, and the pool's delivery deadline. Publication and
negotiation then run through the served storefront and its typed client.

Every account, key and address here is a deterministic development value; none
may be used on a public network.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import patch

from market_arkhai_mediation.contract import INTERFACE as MEDIATION_INTERFACE
from market_arkhai_payments.fixtures import dispute_lifecycle
from market_arkhai_payments.seller import servicing_stage
from market_deal_lifecycle.configuration import DisputeConfig, DisputeEntry
from market_identity import Ed25519Signer
from market_settlement_runtime.rate_publication import DEFAULT_PREMATURE_STOP_PENALTY_PERIODS
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
#: The approval window each payment clause configures, ``PT5M``.
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


def payment_clause(
    rate: str | None = "2.5",
    *,
    recurring: Mapping[str, Any] | None = None,
    delivery_deadline_seconds: int | None = None,
) -> dict[str, Any]:
    """One payments publication clause, recurring when ``recurring`` is given,
    stating no rate of its own when ``rate`` is ``None``, and configuring
    ``delivery_deadline_seconds`` when it is given."""
    return {
        "mechanism": MECHANISM,
        "asset": "USD/6",
        **({"rate": rate, "per": "hour"} if rate is not None else {}),
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


def clauses(*, delivery_deadline_seconds: int | None = None) -> list[dict[str, Any]]:
    """A reserved Alkahest clause, a once payment, an on-demand and a spot preset,
    each payment clause configuring ``delivery_deadline_seconds`` when it is given."""
    deadline = {"delivery_deadline_seconds": delivery_deadline_seconds}
    return [
        settlement_clause("1"),
        payment_clause(**deadline),
        payment_clause(recurring=_PAYER, **deadline),
        payment_clause("1.5", recurring={**_PAYER, "payee_notice_seconds": 120}, **deadline),
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
    #: The composition's declarations, by mechanism. Publication, acceptance and
    #: the payments stage read them at each door, so a test that changes them
    #: between publication and acceptance stands for a storefront restarted under
    #: a different declaration.
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
    default_penalty_periods: int = DEFAULT_PREMATURE_STOP_PENALTY_PERIODS,
    pool_deadline: int | None = DELIVERY_DEADLINE_SECONDS,
) -> AsyncIterator[RecurringWorld]:
    """The VM storefront with one bounded pool publishing ``published``, by
    default the four clauses of ``clauses``.

    ``treatments`` is the payments declaration the composition starts with;
    ``None`` declares none, as a composition configuring no
    ``[Settlement].rate_servicing`` does. ``pricing`` is the pool's family rates,
    which make its listing shape-priced. ``default_penalty_periods`` is the
    composition's configured penalty multiple. ``pool_deadline`` is the pool's
    effective delivery deadline, ``None`` where the pool supplies none, as in a
    deployed composition, which wires no pool port.
    """
    declarations: dict[str, RateServicingDeclaration] = {}
    # One declaration object for every door: the composition's publication and
    # acceptance and the stage's materialization read the same mapping.
    servicing = RateServicing(declarations)
    root = _settlement_root()

    def composition(_fulfillment: Mapping[str, bool]) -> VmSettlementComposition:
        registry = build_storefront_settlement_registry()
        config = registry.resolve(root, role="seller")
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
            settlement_config=config,
            mechanism_resources={
                "wallet": SELLER_WALLET,
                "chains": dict(storefront_config.CHAINS),
                "clients": {"anvil": object()},
            },
            disputes=RegistryDisputePolicy(DisputeConfig(entries=[DISPUTE_ENTRY])),
            rate_servicing=servicing,
            arkhai_payments_stage=servicing_stage(
                config.mechanism_config("arkhai_payments"), rate_servicing=servicing,
            ),
            delivery_deadline_for_pool=lambda _site, _pool: pool_deadline,
            default_penalty_periods=default_penalty_periods,
        )

    with patch.dict("os.environ", {"XDG_CACHE_HOME": _token_cache(tmp_path)}), \
            replaced_setting("pricing.defaults", {}):
        async with publication_app(
            tmp_path,
            negotiation=True,
            settlement_configuration=root,
            settlement_composition_factory=composition,
            # Payments builds no accepted obligation: this is the entry the
            # composition's own dispatch gives it.
            negotiation_options={"accepted_obligation_dispatch": {MECHANISM: None}},
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
            world = RecurringWorld(app, declarations)
            world.declare(treatments)
            await app.client.get_system_status()
            yield world
