"""``market buy --watchdog`` against the composed VM storefront on a recurring option.

Application integration: the production VM buyer command runs against the VM
storefront served on loopback, with its SQLite persistence and the installed
recurring wiring under a declaration listing ``charged`` and ``returned``
(``tests.recurring_world``), its payments settle path and lifecycle routes
mounted (``settlement``). The buyer negotiates the published on-demand option,
approves its mandate at the in-process payments engine, which both sides read,
and commits; the deal is delivered, and the watchdog the buyer opted into
probes the endpoint its delivery disclosed once the deal is available. The
buy's commit, its settlement wait and the watchdog run on the command's wait
clock, so the buy runs while the site is unreachable and waits for delivery on
a fake clock that advances only by the sleeps it is given: never delivered, the
wait times out in fake time; delivered while the command waits, the same
command reads the deal ready and enters its watchdog.

The buy command's own factories are its seam for the watchdog's probe and
clock (``buy_cli.watchdog_probe``, ``buy_cli.wait_clock``): the probe answers
from a script rather than a socket, and the clock's sleeps return at once,
having advanced its time. The buyer CLI's other collaborators are replaced at
the names it resolves them through, some of them imported names and one inside
core, as the VM buyer CLI's tests do until its command modules own factory
seams (``docs/development/ROADMAP.md`` records that gap):

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

from arkhai_vms import VmConnectionDetails
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
from market_deal_lifecycle_buyer import FileEvidenceStore, WaitClock
from market_deal_servicing import EndSession
from market_deal_servicing.evidence import transaction
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


class FakeWaitClock:
    """The buy command's wait clock in fake time.

    Each sleep advances ``monotonic`` by its seconds and returns at once, after
    awaiting ``on_sleep``. The command awaits its sleeps on event loops of its
    own, in its own threads, so ``on_sleep`` reaches the test's loop through
    ``on_test_loop``.
    """

    def __init__(self, on_sleep=None):
        self.now = 1000.0
        self.slept: list[float] = []
        self.on_sleep = on_sleep

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds
        if self.on_sleep is not None:
            await self.on_sleep()

    def wait_clock(self) -> WaitClock:
        return WaitClock(monotonic=lambda: self.now, sleep=self.sleep)


async def on_test_loop(loop: asyncio.AbstractEventLoop, coroutine) -> None:
    """Run ``coroutine`` on the test's ``loop`` from another loop, and wait for it."""
    await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(coroutine, loop))


def _seams(monkeypatch, answers: list[bool], clock: FakeWaitClock) -> list:
    """Replace the buy command's probe factory with ``answers``, one per probe,
    and its wait clock with ``clock``; return the connection details each built
    probe was given."""
    built: list = []

    def watchdog_probe(connection_details):
        built.append(connection_details)
        remaining = iter(answers)

        async def probe() -> bool:
            return next(remaining)

        return probe

    monkeypatch.setattr(buy_cli, "watchdog_probe", watchdog_probe)
    monkeypatch.setattr(buy_cli, "wait_clock", clock.wait_clock)
    return built


def _buy_arguments(*, timeout: int, interval: int) -> list[str]:
    return [
        "buy", "--yes", "--ssh-public-key", SSH_KEY, "--duration-seconds", "3600",
        # The option's hourly 2.5, in base units: the seller's ask, which the
        # buyer prices per fifteen-minute period.
        "--initial-price", "2500000", "--max-price", "2500000",
        "--registry-urls", REGISTRY_URL,
        "--watchdog", "--watchdog-interval", "1", "--watchdog-threshold", "2",
        "--settlement-timeout", str(timeout), "--poll-interval", str(interval),
    ]


def _events(run_id: str) -> list[dict]:
    return list(read_run(run_id, signer=BUYER_SIGNER))


def _negotiation(run_id: str) -> str:
    return next(
        event["negotiation_id"] for event in _events(run_id) if event["event"] == "payment_approved"
    )


async def test_a_purchase_never_delivered_times_out_in_its_clocks_time(tmp_path, monkeypatch):
    payments = WallClockPayments(signer=PAYMENTS_SERVICE)
    runner = CliRunner()
    clock = FakeWaitClock()
    async with recurring_world(tmp_path) as world, settlement(world, payments=payments) as settled, \
            served(world.app.app) as url:
        await world.publish()
        (summary,) = (await world.app.client.list_listings(status="open")).listings
        listing = _registry_listing(world, summary.listing_id, url)
        _buyer(tmp_path, monkeypatch, listing, payments)
        probed = _seams(monkeypatch, [True], clock)
        # The site stays unreachable, so the deal is never delivered.
        settled.site.unreachable = True

        bought = await asyncio.to_thread(
            runner.invoke, buyer_app, _buy_arguments(timeout=600, interval=30),
        )

        # The commit is accepted and the deal never available: the settle
        # status is read every thirty seconds of the clock's time until the
        # ten minutes run out, and the command exits at its timeout with the
        # opt-in kept and nothing probed. Every pause went to the fake clock.
        assert bought.exit_code == 4, bought.output
        (run,) = list_runs()
        events = _events(run.run_id)
        negotiation_id = _negotiation(run.run_id)
        [submitted] = [event for event in events if event["event"] == "settlement_submitted"]
        assert submitted["body"]["status"] == "committed"
        polls = [event for event in events if event["event"] == "settlement_poll"]
        assert len(polls) == 21 and polls[-1]["body"]["status"] != "ready"
        assert clock.slept == [30] * 20
        assert events[-1]["event"] == "run_ended" and events[-1]["status"] == "timeout"
        assert "Watchdog running" not in bought.output and probed == []
        opted_in = FileEvidenceStore(tmp_path / "buyer" / "evidence").watchdog.state(negotiation_id)
        assert opted_in is not None and opted_in.last_probe_at is None
        await settled.delivered(negotiation_id)


async def test_a_watched_purchase_is_monitored_from_available(tmp_path, monkeypatch):
    payments = WallClockPayments(signer=PAYMENTS_SERVICE)
    runner = CliRunner()
    loop = asyncio.get_running_loop()
    async with recurring_world(tmp_path) as world, settlement(world, payments=payments) as settled, \
            served(world.app.app) as url:
        await world.publish()
        (summary,) = (await world.app.client.list_listings(status="open")).listings
        listing = _registry_listing(world, summary.listing_id, url)
        _buyer(tmp_path, monkeypatch, listing, payments)
        delivered_at: list[int] = []

        async def deliver() -> None:
            # The first delivery drive, held back by the unreachable site, has
            # returned; the site answers again and a settle drives the delivery
            # to its end: the deal is available and billing started.
            (run,) = list_runs()
            negotiation_id = _negotiation(run.run_id)
            await settled.delivered(negotiation_id)
            settled.site.unreachable = False
            await world.app.buyer.settle_agreement(negotiation_id)
            await settled.delivered(negotiation_id)
            with transaction(world.app.db.db_path) as conn:
                assert EndSession(conn).read(negotiation_id).available_at is not None
            assert payments.count("submit_event") == 1

        async def deliver_after_two_polls() -> None:
            (run,) = list_runs()
            polls = [event for event in _events(run.run_id) if event["event"] == "settlement_poll"]
            if len(polls) == 2 and not delivered_at:
                delivered_at.append(len(clock.slept))
                await on_test_loop(loop, deliver())

        clock = FakeWaitClock(on_sleep=deliver_after_two_polls)
        # The endpoint answers once, then stops answering for the threshold.
        probed = _seams(monkeypatch, [True, False, False], clock)
        # The site is unreachable while the buy starts, so its delivery waits.
        settled.site.unreachable = True

        bought = await asyncio.to_thread(
            runner.invoke, buyer_app, _buy_arguments(timeout=600, interval=30),
        )

        # The command waited for delivery on its clock, two settle reads
        # finding the deal not yet available; delivered during its second
        # pause, the deal reads ready, and the same command enters the
        # watchdog it opted into: it states its bound, probes the endpoint
        # the delivery disclosed, and after the threshold of failures sends
        # the buyer's stop.
        assert bought.exit_code == 0, bought.output
        assert delivered_at == [2] and clock.slept[:2] == [30, 30]
        assert "Watchdog running" in bought.output
        (run,) = list_runs()
        negotiation_id = _negotiation(run.run_id)
        [details] = probed
        endpoint = (VmConnectionDetails.model_validate_json(details) if isinstance(details, str)
                    else VmConnectionDetails.model_validate(details))
        # The endpoint ``vm_fulfillment_result`` delivers by default.
        assert (endpoint.host, endpoint.port) == ("203.0.113.10", 2222)
        events = _events(run.run_id)
        polls = [event for event in events if event["event"] == "settlement_poll"]
        assert len(polls) == 3 and polls[-1]["body"]["status"] == "ready"
        [exited] = [event for event in events if event["event"] == "watchdog_exited"]
        assert exited["reason"] == "stopped"
        # The watchdog paused on the same clock after the settle wait, between
        # its one-second probes.
        watchdog_pauses = clock.slept[2:]
        assert watchdog_pauses and all(0 < pause <= 1 for pause in watchdog_pauses)
        # The rate start, then the watchdog's stop.
        assert payments.count("submit_event") == 2

        read = await asyncio.to_thread(runner.invoke, buyer_app, ["delivery", "--run", run.run_id])
        assert read.exit_code == 0, read.output

    # The last probe is journaled, and the stop with the two failures it rests on.
    state = FileEvidenceStore(tmp_path / "buyer" / "evidence").watchdog.state(negotiation_id)
    assert state is not None and state.stop is not None
    assert [probe.detail for probe in state.stop.probes] == ["access did not answer"] * 2
    assert state.last_probe_at == state.stop.probes[-1].at
    view = json.loads(read.stdout.strip().splitlines()[-1])
    assert view["watchdog"]["status"] == "stopped"
