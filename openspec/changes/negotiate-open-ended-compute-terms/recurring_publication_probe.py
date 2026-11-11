"""Replay mixed compute publication with an explicitly injected proposed helper.

This diagnostic does not install hosted rate servicing or enable a deployed lane.
Its app, SQLite database, token cache and external-boundary doubles are invocation
owned. All signers/accounts/addresses are deterministic public development values;
none may be used on a public network.
"""

from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from fractions import Fraction
import json
import math
import sqlite3

import httpx
from storefront_client import StorefrontClient, StorefrontClientError
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

from market_arkhai_mediation.contract import INTERFACE as MEDIATION_INTERFACE
from market_arkhai_payments.fixtures import dispute_lifecycle
from market_core.schemas import (
    AgreedPrice, RateValue, SettlementOption, SettlementPrice,
    derive_settlement_option_id,
)
from market_deal_lifecycle.configuration import DisputeConfig, DisputeEntry
from market_deal_lifecycle.terms import Adjudication, TermContext, encode_terms
from market_identity import Ed25519Signer, TrustedIdentitySet
from market_pool_overrides import PoolOverrideClient
from market_settlement_runtime import SettlementPublicationClause
from market_settlement_runtime.rate_publication import RatePresetPricing
from market_settlement_runtime.rate_servicing import RateServicing, RateServicingDeclaration, RateServicingUnavailable
from market_storefront_kit.dispute_configuration import RegistryDisputePolicy

ROOT = Path(__file__).resolve().parents[3]
MECHANISM = "arkhai.payments.v1"
PAYEE = "22222222-2222-4222-8222-222222222222"
DISPUTE = "33333333-3333-4333-8333-333333333333"
SERVICE = Ed25519Signer(bytes(range(1, 33)))
END = "2035-01-01T00:00:00Z"
ACCEPTANCE = False
ENTRY = DisputeEntry.model_validate({
    **dispute_lifecycle(DISPUTE)["adjudication"]["dispute"],
    "interface": MEDIATION_INTERFACE,
    "advertisement": {"mechanisms": [MECHANISM],
                      "minimum_dispute_window_seconds": 60,
                      "minimum_case_hold_seconds": None},
})


class ProposedHelper:
    """An injected proposed encoder, not the hosted payment adapter."""

    def __init__(self):
        self.supported = frozenset({"charged", "returned"})
        self.requests = []

    def pricing(self, clause, authorities):
        assert ENTRY in authorities
        seconds = {"PT15M": 900, "PT1M": 60}[clause.recurring.period]
        hourly = Fraction(Decimal(clause.rate)) * 10**6
        quote = AgreedPrice(
            unit="per_period", period=clause.recurring.period, period_seconds=seconds,
            amount=math.ceil(hourly * seconds / 3600), asset=clause.asset,
        )
        return RatePresetPricing(
            quote=quote, approval_window_seconds=300,
            adjudication=Adjudication(version=1, dispute=ENTRY.authority,
                                      dispute_window_seconds=604800, case_hold_max_seconds=None),
            context=TermContext(
                mechanism=clause.mechanism, has_adapter=True,
                dispute_interfaces=frozenset({ENTRY.interface}),
                authority=ENTRY.requirements, supported_partial_periods=self.supported,
            ),
        )

    def build(self, request):
        self.requests.append(request)
        price = SettlementPrice(asset=request.quote.asset, rates=[
            RateValue(field="amount", per="hour",
                      value=int(Decimal(request.clause.rate) * 10**6)),
        ])
        settlement = {
            "schema": request.clause.mechanism, "payee_account": PAYEE, "window": "PT5M",
            "deposit_agreement": False, "period": request.preset.period,
            "reserve_ahead_seconds": request.preset.reserve_ahead_seconds,
        }
        lifecycle = encode_terms(request.lifecycle)
        return SettlementOption(
            option_id=derive_settlement_option_id(price=price, settlement=settlement, lifecycle=lifecycle),
            price=price, settlement=settlement, lifecycle=lifecycle,
        )


def payment_clause(rate="2.5", *, recurring=None):
    return {
        "mechanism": MECHANISM, "asset": "USD/6", "rate": rate, "per": "hour",
        "mechanism_input": {
            "asset": "USD/6", "payee_account": PAYEE, "window": "PT5M",
            "dispute_window_seconds": 604800,
            # Deliberately differs from the effective pool-port value below.
            "delivery_deadline_seconds": 1,
        },
        **({"recurring": recurring} if recurring is not None else {}),
    }


def presets():
    payer = {"period": "PT15M", "reserve_ahead_seconds": 1800}
    return [payment_clause(), payment_clause(recurring=payer),
            payment_clause("1.5", recurring={**payer, "payee_notice_seconds": 120})]


def root_configuration(alkahest):
    return {
        "schema_version": 1, "priority": ["alkahest.v1", MECHANISM],
        "alkahest": alkahest,
        "arkhai_payments": {
            "enabled": True, "service_url": "http://127.0.0.1:9",
            "service_identity": SERVICE.identity.model_dump(mode="json"),
            "fee_bps": 250, "development_auth": True,
        },
    }


def seed_token_cache(path, chain_id):
    directory = path / "cache"
    token_directory = directory / "arkhai" / "tokens"
    token_directory.mkdir(parents=True, exist_ok=True)
    token = "0x" + "22" * 20
    (token_directory / f"{chain_id}.json").write_text(json.dumps({
        token: {"symbol": "USDC", "contract_address": token, "decimals": 6, "chain_id": chain_id},
    }))
    return str(directory)


def options(listing):
    return listing.extra["settlement_options"]


def qualify_selector():
    required = {MECHANISM: "fixture-rate-v1"}
    proposed = RateServicingDeclaration(MECHANISM, "fixture-rate-v1", "proposed", "terms-probe")
    published = RateServicingDeclaration(MECHANISM, "fixture-rate-v1", "published")
    for declared, lane, allowed in (
        ({}, None, False), ({MECHANISM: published}, None, True),
        ({MECHANISM: proposed}, None, False),
        ({MECHANISM: proposed}, "another-lane", False),
        ({MECHANISM: proposed}, "terms-probe", True),
        ({MECHANISM: replace(published, contract_revision="different")}, None, False),
        ({MECHANISM: replace(published, mechanism="different")}, None, False),
    ):
        try:
            selected = RateServicing(required, declared, lane).select(MECHANISM)
        except RateServicingUnavailable:
            assert not allowed
        else:
            assert allowed and selected is declared[MECHANISM]
    print("published/proposed/absent/wrong revision/wrong mechanism/exact lane selection: PASS")


def acceptance_snapshot(db):
    with sqlite3.connect(db.db_path) as connection:
        return connection.execute("SELECT * FROM negotiation_threads ORDER BY negotiation_id").fetchall()


async def refuse_cached(buyer, db, identity, option, mode):
    before = acceptance_snapshot(db)
    payload = {"duration_seconds": 3600, "ssh_public_key": "ssh-ed25519 fixture"}
    if mode != "VM":
        payload["access_method"] = "ssh"
    try:
        await buyer.negotiate_new(
            listing_id=identity, initial_amount=1,
            provision_terms={"kind": "compute.v1" if mode == "VM" else "bare_metal.v2", "version": 1, "payload": payload},
            settlement_selection={"option_id": option["option_id"],
                                  "settlement": {"schema": MECHANISM, "payer_account": PAYEE}},
            selection_only=True,
        )
    except StorefrontClientError as exc:
        assert exc.status_code == 409 and "settlement_option_withdrawn_refetch" in str(exc), str(exc)
    else:
        raise AssertionError("undeclared cached rate option was accepted")
    assert acceptance_snapshot(db) == before


async def exercise(admin, state, *, buyer, db, mode, clauses, address):
    await admin.get_system_status()
    await admin.admin_run_lifecycle_cycle("site-projections")
    report = await admin.admin_run_lifecycle_cycle("publication")
    listings = (await admin.list_listings(status="open")).listings
    assert len(listings) == 1, report
    (listing,) = listings
    identity = listing.listing_id
    built = options(await admin.get_listing(identity))
    assert len(built) == 4, (built, report)
    hosted = [item for item in built if item["settlement"]["schema"] == MECHANISM]
    assert len(hosted) == 3
    assert all(item["lifecycle"]["delivery_deadline_seconds"] == 1200 for item in hosted)
    assert all("lifecycle" not in item for item in built if item not in hosted)
    rates = [item for item in hosted if "period" in item["settlement"]]
    on_demand = next(item for item in rates if "payee" not in item["lifecycle"]["early_termination"]["entitlements"])
    assert on_demand["lifecycle"]["early_termination"]["premature_stop_penalty"] == "15000000"
    assert state["helper"].requests[-1].default_horizon_seconds == 7200
    print(mode, "typed publication: one capacity identity, reserved + hosted once + independently priced on-demand/spot: PASS")

    if ACCEPTANCE:
        from horizon_probe import exercise as horizons  # Lazy: optional acceptance diagnostic.
        reserved = next(item for item in hosted if "period" not in item["settlement"])
        await horizons(buyer, db, identity, on_demand, mode, state.get("preview"), reserved)

    declaration = state["declarations"][MECHANISM]
    for invalid in (None, replace(declaration, contract_revision="different"),
                    replace(declaration, lane_identity="another-lane")):
        if invalid is None:
            state["declarations"].clear()
        else:
            state["declarations"][MECHANISM] = invalid
        await refuse_cached(buyer, db, identity, on_demand, mode)
        report = await admin.admin_run_lifecycle_cycle("publication")
        assert len(options(await admin.get_listing(identity))) == 2
        assert sum(item.get("reason") == "rate_servicing_undeclared" for item in report["actions"]) == 2
        state["declarations"][MECHANISM] = declaration
        await admin.admin_run_lifecycle_cycle("publication")
    print(mode, "absent/wrong revision/wrong lane: cached signed 409/refetch with no negotiation writes; publication keeps reserved identity: PASS")
    state["declarations"][MECHANISM] = RateServicingDeclaration(MECHANISM, "fixture-rate-v1", "published")
    await admin.admin_run_lifecycle_cycle("publication")
    assert len(options(await admin.get_listing(identity))) == 4
    state["declarations"][MECHANISM] = declaration
    print(mode, "matching published declaration also permits recurring publication: PASS")

    overrides = PoolOverrideClient(admin)
    adjusted = deepcopy(clauses)
    adjusted[-2]["recurring"]["premature_stop_penalty"] = "0"
    await overrides.put_pool_override({**address, "settlements": adjusted})
    report = await admin.admin_run_lifecycle_cycle("publication")
    assert any(item.get("reason") == "default_buyer_refusal" and "penalty" in item["detail"] for item in report["actions"])
    assert len(options(await admin.get_listing(identity))) == 4
    print(mode, "seller penalty override publishes with the default-buyer diagnostic: PASS")

    state["deadline"] = 1800
    await admin.admin_run_lifecycle_cycle("publication")
    refreshed = options(await admin.get_listing(identity))
    assert next(item["option_id"] for item in refreshed if item["settlement"]["schema"] == MECHANISM) != hosted[0]["option_id"]
    state["deadline"] = 1200
    await overrides.delete_pool_override(**address)

    state["helpers"].clear()
    report = await admin.admin_run_lifecycle_cycle("publication")
    assert len(options(await admin.get_listing(identity))) == 2
    assert sum(item.get("reason") == "rate_helper_missing" for item in report["actions"]) == 2
    state["helpers"][MECHANISM] = state["helper"]
    print(mode, "missing encoder omits recurring peers, keeps reserved identity: PASS")

    await overrides.put_pool_override({**address, "terms": {"max_duration_seconds": 1500}})
    report = await admin.admin_run_lifecycle_cycle("publication")
    assert len(options(await admin.get_listing(identity))) == 2
    assert any(item.get("reason") == "recurring_horizon_no_runway" and "2400" in item["detail"] for item in report["actions"])
    await overrides.delete_pool_override(**address)
    print(mode, "default horizon fails runway without hiding valid reserved peers: PASS")

    state["helper"].supported = frozenset({"charged"})
    report = await admin.admin_run_lifecycle_cycle("publication")
    assert len(options(await admin.get_listing(identity))) == 2
    assert any(item.get("reason") == "recurring_preset_unusable" for item in report["actions"])
    state["helper"].supported = frozenset({"charged", "returned"})

    setup = deepcopy(clauses)
    setup[-2]["recurring"]["setup_amount"] = "100"
    await overrides.put_pool_override({**address, "settlements": setup})
    report = await admin.admin_run_lifecycle_cycle("publication")
    assert len(options(await admin.get_listing(identity))) == 3
    assert any(item.get("reason") == "setup_delivery_end_unsupported" for item in report["actions"])
    await overrides.delete_pool_override(**address)
    print(mode, "unsupported returned treatment and unvendored setup fail closed: PASS")

    state["deadline"] = None
    report = await admin.admin_run_lifecycle_cycle("publication")
    assert len(options(await admin.get_listing(identity))) == 4
    assert sum(item.get("reason") == "default_buyer_refusal" and "no delivery deadline" in item["detail"] for item in report["actions"]) == 3
    state["deadline"] = 1200
    await admin.admin_run_lifecycle_cycle("publication")
    assert (await admin.list_listings(status="open")).listings[0].listing_id == identity
    print(mode, "absent effective port does not reuse a raw clause deadline; diagnostics persist: PASS")

    state["set_bounds"]({"max_duration_seconds": 0})
    await admin.admin_run_lifecycle_cycle("site-projections")
    report = await admin.admin_run_lifecycle_cycle("publication")
    assert any(item.get("reason") == "recurring_horizon_unbounded" for item in report["actions"])
    if mode == "VM":
        assert len(options(await admin.get_listing(identity))) == 2
    else:
        assert (await admin.get_listing(identity)).status == "closed"
    state["set_bounds"]({"max_duration_seconds": 0, "available_until_utc": END})
    await admin.admin_run_lifecycle_cycle("site-projections")
    await admin.admin_run_lifecycle_cycle("publication")
    absolute_only = await admin.get_listing(identity)
    assert absolute_only.status == "open"
    assert len(options(absolute_only)) == (4 if mode == "VM" else 2)
    assert absolute_only.extra["available_until_utc"] == END
    state["set_bounds"]({"max_duration_seconds": 7200, "available_until_utc": END})
    await admin.admin_run_lifecycle_cycle("site-projections")
    await admin.admin_run_lifecycle_cycle("publication")
    assert len(options(await admin.get_listing(identity))) == 4
    print(mode, "unbounded recurrence omitted; absolute-only recurrence keeps identity and reserved admission rule: PASS")


async def vm(path):
    sys.path.insert(0, str(ROOT / "domains/vms/storefront"))
    import tests.conftest  # Lazy: install only the selected app's configuration.
    from tests.publication_app import publication_app, pool, SETTLEMENT, SELLER_WALLET, settlement_clause  # Lazy: VM fixture only.
    from market_storefront.domain_runtime import build_vm_storefront_domain  # Lazy: VM environment only.
    from market_storefront.settlement_composition import VmSettlementComposition, build_storefront_settlement_registry  # Lazy: VM environment only.
    from market_storefront.utils import config  # Lazy: VM configuration only.
    from tests._settings_overrides import replaced_setting  # Lazy: VM environment only.

    from horizon_probe import timing, billing, ProposedPayments  # Lazy: selected VM diagnostic.
    helper = ProposedHelper()
    declarations = {MECHANISM: RateServicingDeclaration(MECHANISM, "fixture-rate-v1", "proposed", "terms-probe")}
    state = {"helper": helper, "helpers": {MECHANISM: helper}, "deadline": 1200,
             "declarations": declarations,
             "servicing": RateServicing({MECHANISM: "fixture-rate-v1"}, declarations, "terms-probe")}
    raw = root_configuration({**SETTLEMENT["alkahest"], "release_models": ["recipient"]})

    def factory(_fulfillment):
        registry = build_storefront_settlement_registry()
        return VmSettlementComposition(
            domain=build_vm_storefront_domain(), repository=None, runtime=None,
            coordinator=None, worker=None, local_principal=SERVICE.identity,
            mechanism_clients={}, evidence_clients={},
            configuration_registry=registry, settlement_config=registry.resolve(raw, role="seller"),
            mechanism_resources={"wallet": SELLER_WALLET, "chains": dict(config.CHAINS),
                                 "clients": {"anvil": object()}},
            disputes=RegistryDisputePolicy(DisputeConfig(entries=[ENTRY])),
            rate_servicing=state["servicing"],
            rate_preset_helpers=state["helpers"],
            rate_term_projections={MECHANISM: timing},
            delivery_deadline_for_pool=lambda site, pool: state["deadline"],
        )

    with patch.dict("os.environ", {"XDG_CACHE_HOME": seed_token_cache(path, 31337)}), \
         replaced_setting("pricing.defaults", {}):
        async with publication_app(
            path, negotiation=True, settlement_configuration=raw, settlement_composition_factory=factory,
            negotiation_options={"project_billing": billing,
                                 "arkhai_payments_stage": ProposedPayments(),
                                 "accepted_obligation_dispatch": {MECHANISM: None}},
        ) as app:
            clauses = [settlement_clause("1"), *presets()]
            app.set_settlement_clauses(clauses)
            projected = pool("bounded", backing="backed", capacity_bounds={"vm": {
                "max_duration_seconds": 7200, "available_until_utc": END,
            }})
            app.pools.append(projected)
            state["set_bounds"] = lambda bounds: projected["pool_metadata"]["policy_tags"].update(capacity_bounds={"vm": bounds})
            await exercise(app.client, state, buyer=app.buyer, db=app.db, mode="VM", clauses=clauses,
                           address={"site_id": "site-a", "pool_id": "bounded", "offering_mode": "vm"})


async def bare(path):
    sys.path.insert(0, str(ROOT / "domains/bare_metal/storefront/tests"))
    from pytest import MonkeyPatch  # Lazy: bare-metal fixture construction only.
    from test_publication_cycle import Site, pool, member  # Lazy: bare-metal fixture only.
    from test_http_system import _derivation_runtime, _app, _admin_client, SELLER_SIGNER  # Lazy: bare-metal app only.
    from test_http_publication_rates import _Sites  # Lazy: bare-metal site facade only.
    from arkhai_bare_metal_storefront.settlement_composition import build_bare_metal_settlement_registry  # Lazy: bare-metal environment only.

    from horizon_probe import timing, ProposedSellerStage  # Lazy: selected bare-metal diagnostic.
    from market_core import SettlementStageTable  # Lazy: bare-metal fixture composition.
    helper = ProposedHelper()
    declarations = {MECHANISM: RateServicingDeclaration(MECHANISM, "fixture-rate-v1", "proposed", "terms-probe")}
    state = {"helper": helper, "helpers": {MECHANISM: helper}, "deadline": 1200,
             "declarations": declarations,
             "servicing": RateServicing({MECHANISM: "fixture-rate-v1"}, declarations, "terms-probe")}
    site = Site(pool("pool-1", member("r1", "pool-1"), policy_tags={"capacity_bounds": {
        "bare_metal": {"max_duration_seconds": 7200, "available_until_utc": END},
    }}))
    state["set_bounds"] = lambda bounds: site.serve(pool("pool-1", member("r1", "pool-1"), policy_tags={
        "capacity_bounds": {"bare_metal": bounds},
    }))
    with MonkeyPatch.context() as patches:
        runtime = _derivation_runtime(path, patches, {"site-a": site}, capacity_client=_Sites(site))
        original = runtime.settlement_composition
        registry = build_bare_metal_settlement_registry()
        raw = root_configuration(original.config.mechanisms["alkahest"].model_dump(mode="json"))
        composition = replace(
            original, registry=registry, config=registry.resolve(raw, role="seller"),
            disputes=RegistryDisputePolicy(DisputeConfig(entries=[ENTRY])),
            rate_servicing=state["servicing"],
            rate_preset_helpers=state["helpers"],
            rate_term_projections={MECHANISM: timing},
            seller_stages=SettlementStageTable({**original.seller_stages,
                MECHANISM: ProposedSellerStage(original.seller_stages[MECHANISM])}),
            delivery_deadline_for_pool=lambda site, pool: state["deadline"],
        )
        clauses = [item.model_dump(mode="json", exclude_none=True) for item in runtime.publication_clauses] + presets()
        runtime = replace(runtime, settlement_composition=composition, publication_clauses=tuple(
            SettlementPublicationClause.model_validate(item) for item in clauses
        ))
        async def preview(identity, option, duration):
            payload = {"ssh_public_key": "ssh-ed25519 fixture", "access_method": "ssh"}
            if duration is not None:
                payload["duration_seconds"] = duration
            plan = await runtime.negotiation_runtime._plan_opening(
                repository=runtime.db, listing_id=identity,
                buyer_principal=SERVICE.identity, seller_principal=runtime.seller_principal,
                proposal={"fields": {"amount": "625000"}, "settlement_selection": {
                    "option_id": option["option_id"], "expiration_unix": 2147483647,
                    "settlement": {"schema": MECHANISM, "payer_account": PAYEE},
                }},
                terms={"kind": "bare_metal.v2", "version": 1, "payload": payload},
                negotiation_id="preview",
            )
            assert plan.accepted
            assert plan.acceptance.policy_state["exact_selection"]["bare_metal_terms"]["duration_seconds"] == plan.acceptance.agreement.duration_seconds
            return {"agreement": plan.artifacts["agreement"].model_dump(mode="json", exclude_none=True)}
        state["preview"] = preview
        app = _app(runtime)
        async with app.router.lifespan_context(app):
            async with _admin_client(app) as admin, StorefrontClient(
                "http://seller", signer=SERVICE, caller_role="buyer",
                expected_publishers=TrustedIdentitySet(identities=(SELLER_SIGNER.identity,)),
                transport=httpx.ASGITransport(app=app),
            ) as buyer:
                await exercise(admin, state, buyer=buyer, db=runtime.db, mode="bare metal", clauses=clauses,
                               address={"site_id": "site-a", "pool_id": "pool-1", "offering_mode": "bare_metal"})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("surface", choices=("vm", "bare"))
    parser.add_argument("--acceptance", action="store_true")
    args = parser.parse_args()
    ACCEPTANCE = args.acceptance
    qualify_selector()
    with TemporaryDirectory(prefix="recurring-publication-") as directory:
        asyncio.run((vm if args.surface == "vm" else bare)(Path(directory)))
    print("LIMIT: proposed injected encoder/timing/data fixtures; no hosted rate authority, approval, mandate, materialization or deployed site deadline.")
