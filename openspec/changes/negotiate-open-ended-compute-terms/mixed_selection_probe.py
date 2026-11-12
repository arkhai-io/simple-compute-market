"""First-use replay of published mixed options through the buyer commands.

Only proposed mechanism ports and external discovery/effect seams are replaced.
Publication and cached refusal use invocation-owned ASGI apps and SQLite.
Public deterministic development identities must never be used on public networks.
"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import ExitStack
from dataclasses import replace
from fractions import Fraction
import json
import math
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import uuid

from market_arkhai_payments import create_arkhai_payments_registration
from market_core.schemas import AgreedPrice, PriceBasis, SettlementOption
from market_identity import Ed25519Signer, TrustedIdentitySet
from market_deal_lifecycle.configuration import DisputeEntry
from market_deal_lifecycle.selection import AuthoritySelection
from market_settlement_runtime.buyer_terms import BuyerTermsAdmission
from typer.testing import CliRunner
from market_settlement_runtime import SettlementConfigurationRegistry
from market_settlement_runtime.presentation import PaymentPresentation, amount_rate_quote

MECHANISM = "arkhai.payments.v1"
PAYEE = "22222222-2222-4222-8222-222222222222"
END = "2035-01-01T00:00:00Z"

ROOT = Path(__file__).resolve().parents[3]
SIGNER = Ed25519Signer(bytes(range(32)))
IDENTITY = SimpleNamespace(profile_id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
                           signer=SIGNER, principal=SIGNER.identity)
URL = "https://registry.example"


class SelectionObserved(Exception):
    """Stop immediately after the command's selected terms, before effects."""


def billing(option):
    if "period" in option.settlement_params:
        return PriceBasis(unit="per_period", period="PT15M", period_seconds=900)
    return PriceBasis(unit="total")


def presentation(option, duration, accepted):
    basis = billing(option)
    if basis.unit == "total":
        quote = accepted or amount_rate_quote(option, duration, basis)
    else:
        quote = accepted or AgreedPrice(
            **basis.model_dump(), asset=option.price_asset,
            amount=math.ceil(Fraction(option.price_rates[0].value, 4)),
        )
    return PaymentPresentation(quote=quote, setup_once=0,
                               initial_reserve=quote.amount * 2 if basis.unit == "per_period" else 0)


def consume(domain, path):
    listing = json.loads(path.read_text())
    entry = DisputeEntry.model_validate(listing.pop("_diagnostic_authority"))
    options = [SettlementOption.model_validate(item) for item in listing["settlement_options"]]
    alkahest = next(option for option in options if option.settlement_schema == "alkahest.v1")
    hosted = [option for option in options if option.settlement_schema == MECHANISM]
    once = next(option for option in hosted if billing(option).unit == "total")
    rates = [option for option in hosted if billing(option).unit == "per_period"]
    on_demand = next(option for option in rates if "payee" not in option.lifecycle["early_termination"]["entitlements"])
    spot = next(option for option in rates if option != on_demand)
    installed = create_arkhai_payments_registration()
    proposed = replace(installed, project_billing=billing, present_payment=presentation,
                       buyer_compatibility=lambda *_: True)
    if domain == "vm":
        from arkhai_vms_buyer import buy_cli as cli, common  # Lazy: only the VM buyer installs this composition.
        from arkhai_vms_buyer import settlement_composition as composition  # Lazy: VM-only environment.
        from arkhai_vms_buyer.cli import app  # Lazy: VM-only environment.
        from core_buyer.settlement import BuyerSettlementPolicy  # Lazy: needed by the VM selection mode only.
        registry = SettlementConfigurationRegistry((proposed, *[
            entry for entry in composition.buyer_settlement_registry().registrations
            if entry.mechanism_id != MECHANISM
        ]))
    else:
        from arkhai_bare_metal_buyer import cli, settlement_composition as composition  # Lazy: bare-metal-only environment.
        app = cli.bare_metal_app
        registry = SettlementConfigurationRegistry((proposed,))

    original_context = composition.buyer_term_context

    def context(mechanism, **kwargs):
        value = original_context(mechanism, **kwargs)
        return replace(value, has_stoppable_part=True,
                       supported_partial_periods=frozenset({"charged", "returned"})) if mechanism == MECHANISM else value

    rights = BuyerTermsAdmission(AuthoritySelection(
        {URL: (entry,)}, contexts={MECHANISM: context(MECHANISM)},
    ))
    for option in options:
        rights.rank(option, registry_url=URL)
    no_promise = dict(composition.buyer_lifecycle_disclosure(alkahest))
    assert "no delivery promise" in str(no_promise).lower(), no_promise
    print(domain, "Alkahest lifecycle absent: admitted by default rights policy; disclosure:", no_promise)
    if domain == "bare":
        print("Bare-metal Alkahest purchase is not installed; rights/disclosure only, not a claimed purchase.")

    def stop(*args, **kwargs):
        raise SelectionObserved()

    for name, selected, duration in (
        *((("Alkahest reserved", alkahest, 3600),) if domain == "vm" else ()),
        ("reserved", once, 3600), ("on-demand", on_demand, None),
        ("on-demand shorter", on_demand, 2401), ("spot", spot, None),
        ("spot shorter", spot, 2401),
    ):
        with ExitStack() as stack:
            stack.enter_context(patch.object(composition, "buyer_settlement_registry", return_value=registry))
            stack.enter_context(patch.object(composition, "buyer_term_context", side_effect=context))
            if domain == "vm":
                config = registry.resolve({"schema_version": 1, "priority": ["alkahest.v1", MECHANISM], "alkahest": {"enabled": True},
                                           "arkhai_payments": {"enabled": True}}, role="buyer")
                # Exact option ID is a fixture choice, not a new product class filter.
                policy = BuyerSettlementPolicy(
                    config=config, registry=registry, stages=composition.buyer_settlement_stages(),
                    option_preference=lambda option, source: rights(option, source) if option == selected else None,
                )
                for attr, value in {
                    "resolve_fresh_buyer_identity": lambda: IDENTITY,
                    "resolve_ssh_public_key": lambda **_: "ssh-ed25519 public-development-fixture",
                    "resolve_indexer_urls": lambda **_: [URL],
                    "resolve_registry_authorities": lambda _: {URL: object()},
                    "resolve_indexer_urls_for_schema": lambda *_, **__: [URL],
                    "resolve_registry_api_keys": lambda: {},
                    "resolve_discovery_timeout": lambda **_: 1,
                }.items():
                    stack.enter_context(patch.object(common, attr, value))
                stack.enter_context(patch.object(cli, "resolve_buyer_settlement_policy", return_value=policy))
                stack.enter_context(patch.object(cli, "query_registry_for_matches_multi", return_value=[listing]))
                stack.enter_context(patch.object(cli, "buyer_stage", return_value=SimpleNamespace(prepare_selection=lambda choice: choice)))
                emit = cli.emit_lifecycle_disclosure
                def observed(rows, **kwargs):
                    emit(rows, **kwargs)
                    stop()
                stack.enter_context(patch.object(cli, "emit_lifecycle_disclosure", side_effect=observed))
                args = ["buy", "--yes"]
                if duration is not None:
                    args += ["--duration-hours", str(duration / 3600)]
            else:
                config = SimpleNamespace(
                    payer_account=PAYEE, arkhai_payments=SimpleNamespace(enabled=True),
                    disputes=SimpleNamespace(use_registry_dispute_authorities=False),
                    dispute_authorities_by_registry={URL: (entry,)}, registry_url=URL,
                )
                config.model_copy = lambda **_: config
                client = SimpleNamespace(get_listing=lambda _: SimpleNamespace(
                    **listing, publisher_principals=TrustedIdentitySet(identities=(SIGNER.identity,)),
                ))
                stack.enter_context(patch.object(cli, "load_bare_metal_buyer_config", return_value=config))
                stack.enter_context(patch.object(cli, "fresh_identity", return_value=IDENTITY))
                transport = stack.enter_context(patch.object(cli, "registry_client"))
                transport.return_value.__enter__.return_value = client
                stack.enter_context(patch.object(cli, "authorities_by_registry", return_value={URL: (entry,)}))
                stack.enter_context(patch.object(cli, "buyer_settlement_registry", return_value=registry))
                stack.enter_context(patch.object(cli, "payment_approval", side_effect=stop))
                args = ["buy", listing["listing_id"], "--option-id", selected.option_id,
                        "--ssh-public-key", "ssh-ed25519 public-development-fixture"]
                if duration is not None:
                    args += ["--duration-seconds", str(duration)]
            result = CliRunner().invoke(app, args)
            assert isinstance(result.exception, SelectionObserved), (result.output, repr(result.exception))
            output = result.output
            assert "per_period" in output if selected in rates else "total" in output
            assert ("spot" if selected == spot else "on-demand" if selected in rates else "reserved") in output
            assert "7200 seconds" in output and END in output, (listing, output)
            assert "loss cap" in output
            if selected == alkahest:
                assert "no delivery promise" in output.lower()
            else:
                assert "1200 seconds" in output
            if selected in rates:
                assert "last_boundary" in output and "started_period" in output
                assert "Omitted;" in output if duration is None else "2401 seconds" in output
            print(f"\n{domain} CLI {name}: stopped before approval/negotiation effects\n{output}")
    print(domain, "mixed published selection: PASS; proposed ports only, no hosted approval or rate servicing")


async def publish(domain, path):
    # Publication-only dependencies are intentionally absent from buyer environments.
    import recurring_publication_probe as publication

    original = publication.exercise

    async def exercise(admin, state, **kwargs):
        await admin.get_system_status()
        await admin.admin_run_lifecycle_cycle("site-projections")
        await admin.admin_run_lifecycle_cycle("publication")
        (summary,) = (await admin.list_listings(status="open")).listings
        listing = await admin.get_listing(summary.listing_id)
        document = {**listing.extra, "listing_id": listing.listing_id,
                    "max_duration_seconds": listing.max_duration_seconds,
                    "storefront_url": "https://seller.example", "source_registry_url": URL,
                    "_diagnostic_authority": publication.ENTRY.model_dump(mode="json")}
        fixture = path / "published.json"
        fixture.write_text(json.dumps(document))
        python = ROOT / ("domains/vms/buyer" if domain == "vm" else "domains/bare_metal/buyer") / ".venv/bin/python"
        replay = subprocess.run([str(python), str(Path(__file__)), domain, "--consume", str(fixture)],
                                text=True, capture_output=True)
        print(replay.stdout)
        if replay.returncode:
            raise RuntimeError(replay.stderr)
        await original(admin, state, **kwargs)
    publication.exercise = exercise
    publication.ACCEPTANCE = True
    await (publication.vm if domain == "vm" else publication.bare)(path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("domain", choices=("vm", "bare"))
    parser.add_argument("--consume", type=Path)
    args = parser.parse_args()
    if args.consume:
        consume(args.domain, args.consume)
    else:
        with TemporaryDirectory(prefix="mixed-selection-") as directory:
            asyncio.run(publish(args.domain, Path(directory)))
