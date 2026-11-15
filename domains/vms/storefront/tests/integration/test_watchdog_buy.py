"""``market buy --watchdog`` against the composed VM storefront on a recurring option.

Application integration: the production VM buyer command runs against the VM
storefront served on loopback, with its SQLite persistence and the installed
recurring wiring under a declaration listing ``charged`` and ``returned``
(``tests.recurring_world``), its payments settle path and lifecycle routes
mounted (``settlement``). The buyer negotiates the published on-demand option,
approves its mandate at the in-process payments engine, which both sides read,
and commits; end service refuses the commit of a rate deal while rate servicing
is not composed, so the deal never becomes available. The watchdog's opt-in
alone must never read as protection.

The buyer CLI's collaborators are replaced at the names it resolves them
through, some of them imported names and one inside core, as the VM buyer CLI's
tests do until its command modules own factory seams (``docs/development/ROADMAP.md``
records that gap):

* its identity (``common.resolve_fresh_buyer_identity`` and
  ``resolve_recovery_buyer_identity``), resolving to the world's buyer signer;
* registry configuration and discovery (``common.resolve_indexer_urls``,
  ``resolve_indexer_urls_for_schema``, ``resolve_registry_authorities`` and
  ``resolve_registry_api_keys``; ``buy_cli.query_registry_for_matches_multi``),
  serving the listing the storefront published, with its storefront URL the
  served one;
* the registry read behind the publisher-trust refresh (``fetch_listing_dict``
  in ``core_buyer.orchestrator`` and ``core_buyer.orchestration``), serving
  the same listing;
* the payments service behind the buyer's approval (``payment_buyer`` in
  ``arkhai_payments`` and ``settlement_stages``), the world's payments engine
  through the approval's ``client_for_owner``.

The buyer's configuration is a real ``buyer.toml`` under a temporary
``XDG_CONFIG_HOME``, and its run logs and evidence live under ``tmp_path``.

Every account, key and address here is a deterministic development value; none
may be used on a public network.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid

from arkhai_vms_buyer import arkhai_payments, buy_cli, common, settlement_stages
from arkhai_vms_buyer.cli import app as buyer_app
from arkhai_vms_buyer.run_log import list_runs, read_run
from core_buyer import orchestration, orchestrator
from core_buyer.buyer_config import ResolvedBuyerIdentity
from core_buyer.profile_service import PROFILE_STORE_ENV
from core_buyer.registry_config import RegistryAuthority
from market_arkhai_payments import ArkhaiPaymentsConfig, PaymentApproval
from market_arkhai_payments.fixtures import FakePaymentsClient
from market_arkhai_payments.models import AccountId
from market_config.config_loader import load_user_config
from market_deal_lifecycle_buyer import FileEvidenceStore
from market_identity import TrustedIdentitySet
from typer.testing import CliRunner

from tests.fake_site import TEST_MARKETPLACE_SIGNER
from tests.loopback import served
from tests.publication_app import REGISTRY_SIGNER
from tests.recurring_world import (
    BUYER_SIGNER, DISPUTE_ENTRY, MECHANISM, PAYMENTS_SERVICE, recurring_world, settlement,
)

#: The buyer's payer account.
PAYER = "11111111-1111-4111-8111-111111111111"
#: A placeholder key, never a credential.
SSH_KEY = "ssh-ed25519 AAAAPLACEHOLDER"
#: The registry the buyer discovers through, on a reserved domain; nothing calls it.
REGISTRY_URL = "https://registry.invalid"
REGISTRY_AUTHORITY = "registry-a"
_IDENTITY = ResolvedBuyerIdentity(
    profile_id=uuid.UUID("44444444-4444-4444-8444-444444444444"),
    principal=BUYER_SIGNER.identity,
    signer=BUYER_SIGNER,
    source="fresh",
)


class WallClockPayments(FakePaymentsClient):
    """Approves at the engine's clock, set to the wall clock, as the payments service does.

    The kit fake's own approval signs at a fixed instant, which lies past a
    mandate accepted now and expiring after its five-minute approval window.
    """

    def approve(self, mandate, *, agreement=None):
        self.calls.append(("approve", agreement is not None))
        self.observed_at = int(time.time())
        self.engine.fund(PAYER, "USD/6", 10**12)
        self.receipt = self.engine.approve(mandate, account=PAYER)
        return self.receipt


def _buyer_config(tmp_path, monkeypatch) -> None:
    """The buyer's ``buyer.toml``: its payments mechanism, payer and dispute authority."""
    service = PAYMENTS_SERVICE.identity.model_dump(mode="json")
    dispute = DISPUTE_ENTRY.model_dump(mode="json")
    directory = tmp_path / "buyer-config" / "arkhai"
    directory.mkdir(parents=True)
    (directory / "buyer.toml").write_text(
        "[Settlement]\n"
        "schema_version = 1\n"
        f'priority = ["{MECHANISM}"]\n'
        "[Settlement.arkhai_payments]\n"
        "enabled = true\n"
        'service_url = "http://127.0.0.1:9"\n'
        f'service_identity = {{scheme = "{service["scheme"]}", identifier = "{service["identifier"]}"}}\n'
        "fee_bps = 250\n"
        "development_auth = true\n"
        "[vms]\n"
        f'payer_account = "{PAYER}"\n'
        "[[Dispute]]\n"
        f'interface = "{dispute["interface"]}"\n'
        f'origin = "{dispute["origin"]}"\n'
        f'account = "{dispute["account"]}"\n'
        f'record_key = "{dispute["record_key"]}"\n'
        "params = {}\n"
        "[Dispute.advertisement]\n"
        f'mechanisms = ["{MECHANISM}"]\n'
        "minimum_dispute_window_seconds = 60\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(directory.parent))


def _buyer(tmp_path, monkeypatch, listing: dict, payments: FakePaymentsClient) -> None:
    """Replace the buyer CLI's identity, registry and payments service, as the module says."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    # The buyer keeps its evidence beside its profile store; here, the test's.
    monkeypatch.setenv(PROFILE_STORE_ENV, str(tmp_path / "buyer" / "profiles.json"))
    _buyer_config(tmp_path, monkeypatch)
    monkeypatch.setattr(common, "resolve_fresh_buyer_identity", lambda: _IDENTITY)
    monkeypatch.setattr(common, "resolve_recovery_buyer_identity", lambda _run_id: _IDENTITY)
    registry = RegistryAuthority(
        authority=REGISTRY_AUTHORITY,
        principals=TrustedIdentitySet(identities=(REGISTRY_SIGNER.identity,)),
    )
    monkeypatch.setattr(common, "resolve_indexer_urls", lambda **_kw: [REGISTRY_URL])
    monkeypatch.setattr(common, "resolve_indexer_urls_for_schema", lambda *_a, **_kw: [REGISTRY_URL])
    monkeypatch.setattr(common, "resolve_registry_authorities", lambda urls: {url: registry for url in urls})
    monkeypatch.setattr(common, "resolve_registry_api_keys", lambda: {})
    monkeypatch.setattr(buy_cli, "query_registry_for_matches_multi", lambda *_a, **_kw: [dict(listing)])
    for module in (orchestrator, orchestration):
        monkeypatch.setattr(module, "fetch_listing_dict", lambda *_a, **_kw: dict(listing))

    def payment_buyer(policy) -> PaymentApproval:
        preference = getattr(policy, "option_preference", None)
        return PaymentApproval(
            ArkhaiPaymentsConfig.model_validate(policy.config.mechanism_config("arkhai_payments")),
            AccountId.model_validate(load_user_config()["vms"]["payer_account"]).root,
            client_for_owner=payments, terms_policy=preference,
        )

    for module in (arkhai_payments, settlement_stages):
        monkeypatch.setattr(module, "payment_buyer", payment_buyer)


def _registry_listing(world, listing_id: str, storefront_url: str) -> dict:
    """The listing as the registry serves it: the body the storefront published,
    offering only its on-demand option, with its publisher and source registry."""
    published = world.app.registries.to("publish", listing_id)[0][1]
    return {
        **published,
        "listing_id": listing_id,
        "storefront_url": storefront_url,
        "publisher_id": "publisher-1",
        "source_registry_url": REGISTRY_URL,
        "source_registry_authority": REGISTRY_AUTHORITY,
        "publisher_principals": TrustedIdentitySet(
            identities=(TEST_MARKETPLACE_SIGNER.identity,)
        ).model_dump(mode="json"),
        "settlement_options": [_on_demand(published)],
    }


def _on_demand(listing: dict) -> dict:
    return next(
        option for option in listing["settlement_options"]
        if "period" in option["settlement"]
        and "payee" not in option["lifecycle"]["early_termination"]["entitlements"]
    )


async def test_a_watched_purchase_whose_commit_is_refused_is_never_watched(tmp_path, monkeypatch):
    payments = WallClockPayments(signer=PAYMENTS_SERVICE)
    runner = CliRunner()
    async with recurring_world(tmp_path) as world, settlement(world, payments=payments), \
            served(world.app.app) as url:
        await world.publish()
        (summary,) = (await world.app.client.list_listings(status="open")).listings
        listing = _registry_listing(world, summary.listing_id, url)
        _buyer(tmp_path, monkeypatch, listing, payments)

        bought = await asyncio.to_thread(runner.invoke, buyer_app, [
            "buy", "--yes", "--ssh-public-key", SSH_KEY, "--duration-seconds", "3600",
            # The option's hourly 2.5, in base units: the seller's ask, which
            # the buyer prices per fifteen-minute period.
            "--initial-price", "2500000", "--max-price", "2500000",
            "--registry-urls", REGISTRY_URL, "--watchdog",
            # A deadline of now: the settle status is read once, then the
            # wait has run out, as it would after any longer timeout.
            "--settlement-timeout", "0", "--poll-interval", "0.2",
        ])

        # The commit is accepted and the deal refused before any capacity, so
        # it never becomes available: the command exits at its timeout.
        assert bought.exit_code == 4, bought.output
        (run,) = list_runs()
        events = {event["event"]: event for event in read_run(run.run_id, signer=BUYER_SIGNER)}
        assert "payment_approved" in events, (bought.output, events)
        negotiation_id = events["payment_approved"]["negotiation_id"]
        assert events["settlement_submitted"]["body"]["status"] == "committed"
        # The refused deal's delivery stays deferred, so settlement never ends.
        assert events["settlement_poll"]["body"]["status"] == "provisioning"
        assert events["run_ended"]["status"] == "timeout"
        # No probe ran: the bound is never stated, and no stop reached the engine.
        assert "Watchdog running" not in bought.output
        assert payments.count("approve") == 1 and payments.count("submit_event") == 0

        read = await asyncio.to_thread(runner.invoke, buyer_app, ["delivery", "--run", run.run_id])
        assert read.exit_code == 0, read.output

    # The opt-in is persisted, yet the deal reads unmonitored, never as protected.
    state = FileEvidenceStore(tmp_path / "buyer" / "evidence").watchdog.state(negotiation_id)
    assert state is not None and state.last_probe_at is None and state.stop is None
    view = json.loads(read.stdout.strip().splitlines()[-1])
    assert view["watchdog"] == {"status": "unmonitored", "last_probe_at": None}
    assert view["delivery"]["progress"] != "active" and view["delivery"]["recorded_end"] is None
