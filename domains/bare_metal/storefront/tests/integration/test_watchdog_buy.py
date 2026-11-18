"""``market bare-metal buy --watchdog`` against the composed storefront on a recurring option.

Application integration: the production buyer commands (``buyer_commands``) run
against the bare-metal app served over loopback with the installed recurring
wiring under a declaration listing ``charged`` and ``returned``
(``recurring_world``); beyond ``buyer_commands``' doubles, the buyer CLI's
``wait_clock`` factory runs its waits in fake time, and its ``watchdog_probe``
factory, given the access the buyer read from the storefront, answers from a
script rather than a socket. The buyer approves the on-demand option's mandate
at the in-process payments engine, which both sides read, and commits; the
deal is delivered, and the watchdog the buyer opted into probes it from the
moment it is available.

Every account, key and address here is a deterministic development value; none
may be used on a public network.
"""

import json
import time
from types import SimpleNamespace

from arkhai_bare_metal_buyer import cli as buyer_cli
from market_arkhai_payments.fixtures import FakePaymentsClient
from market_deal_lifecycle_buyer import FileEvidenceStore, WaitClock
from market_identity import TrustedIdentitySet

from buyer_commands import BuyerCommands
from recurring_world import (
    AVAILABLE_UNTIL, BUYER_SIGNER, DISPUTE_ENTRY, MAX_DURATION_SECONDS, PAYMENTS_SERVICE, recurring_world,
)
from test_http_system import ADMIN_SIGNER, SELLER_SIGNER

#: Fixture payer account; never a real account.
PAYER = "11111111-1111-4111-8111-111111111111"
#: A placeholder key, never a credential.
SSH_KEY = "ssh-ed25519 AAAAPLACEHOLDER"


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


class FakeWaits:
    """The buyer command's waits in fake time: sleeping advances the clock at once."""

    def __init__(self) -> None:
        self.now = 1000.0

    async def sleep(self, seconds: float) -> None:
        self.now += seconds

    def clock(self) -> WaitClock:
        return WaitClock(now=lambda: int(self.now), monotonic=lambda: self.now, sleep=self.sleep)


def buyer_settings() -> str:
    """The buyer's payer, payments service and accepted dispute authority."""
    service = PAYMENTS_SERVICE.identity.model_dump(mode="json")
    dispute = DISPUTE_ENTRY.model_dump(mode="json")
    return (
        f'payer_account = "{PAYER}"\n'
        "[bare_metal.arkhai_payments]\n"
        "enabled = true\n"
        'service_url = "http://127.0.0.1:9"\n'
        f'service_identity = {{scheme = "{service["scheme"]}", identifier = "{service["identifier"]}"}}\n'
        "fee_bps = 250\n"
        "development_auth = true\n"
        "[[Dispute]]\n"
        f'interface = "{dispute["interface"]}"\n'
        f'origin = "{dispute["origin"]}"\n'
        f'account = "{dispute["account"]}"\n'
        f'record_key = "{dispute["record_key"]}"\n'
        "params = {}\n"
        "[Dispute.advertisement]\n"
        'mechanisms = ["arkhai.payments.v1"]\n'
        "minimum_dispute_window_seconds = 60\n"
    )


def scripted_probe(monkeypatch, answers: list[bool]) -> list[dict]:
    """Replace the buyer CLI's probe factory with ``answers``, one per probe;
    return the access each built probe was given."""
    built: list[dict] = []

    def watchdog_probe(access):
        built.append(dict(access))
        remaining = iter(answers)

        async def probe() -> bool:
            return next(remaining)

        return probe

    monkeypatch.setattr(buyer_cli, "watchdog_probe", watchdog_probe)
    return built


async def test_a_watched_purchase_is_monitored_from_available(tmp_path, monkeypatch):
    payments = WallClockPayments(signer=PAYMENTS_SERVICE)
    async with recurring_world(tmp_path, payments=payments, serve=True) as world:
        report = await world.publish()
        (listing_id,) = [item["listing_id"] for item in report["actions"] if item["action"] == "publish"]
        options = (await world.admin.get_listing(listing_id)).extra["settlement_options"]
        on_demand = next(
            option for option in options
            if "period" in option["settlement"]
            and "payee" not in option["lifecycle"]["early_termination"]["entitlements"]
        )
        buyer = BuyerCommands(
            monkeypatch, tmp_path, signer=BUYER_SIGNER,
            registry_principal=ADMIN_SIGNER.identity, settings=buyer_settings(),
        )
        buyer.pay_through(payments)
        buyer.serve(SimpleNamespace(
            listing_id=listing_id, storefront_url=world.url, publisher_id="publisher-1",
            publisher_principals=TrustedIdentitySet(identities=(SELLER_SIGNER.identity,)),
            settlement_options=[on_demand],
            max_duration_seconds=MAX_DURATION_SECONDS, available_until_utc=AVAILABLE_UNTIL,
        ))

        waits = FakeWaits()
        monkeypatch.setattr(buyer_cli, "wait_clock", waits.clock)
        # The endpoint answers once, then stops answering for the threshold.
        probed = scripted_probe(monkeypatch, [True, False, False])

        bought = buyer.invoke(
            "buy", listing_id, "--option-id", on_demand["option_id"], "--ssh-public-key", SSH_KEY,
            "--duration-seconds", "3600",
            "--watchdog", "--watchdog-interval", "1", "--watchdog-threshold", "2",
            "--delivery-timeout-seconds", "10", "--poll-interval", "5",
        )

        assert bought.exit_code == 0, bought.output
        purchase, watched = (json.loads(line) for line in bought.stdout.strip().splitlines()[-2:])
        negotiation_id = purchase["fulfillment"]["negotiation_id"]
        # The availability wait that precedes the watchdog answered available;
        # the watchdog stated its bound, probed the run's deal and, after the
        # threshold of failures, sent the buyer's stop, which the payments
        # engine accepted.
        assert watched == {"run_id": purchase["run_id"], "negotiation_id": negotiation_id,
                           "available": True, "watchdog": "stopped"}
        # The probe was built from the access the buyer read from the
        # storefront's access route for the deal while it was active: the
        # endpoint the provisioning double's fulfillment result delivers. The
        # route serves nothing once the stop has ended the lease.
        [access] = probed
        assert access["negotiation_id"] == negotiation_id and access["method"] == "ssh"
        assert (access["host"], access["port"], access["username"]) == ("203.0.113.25", 2222, "tenant-a")
        refused = buyer.invoke("access", "--run-id", purchase["run_id"])
        assert refused.exit_code != 0 and "outside an active lease" in str(refused.exception)
        assert "Watchdog running" in bought.stderr
        assert payments.count("approve") == 1 and payments.count("submit_event") == 2

        read = buyer.run("delivery", "--run-id", purchase["run_id"])

    # The last probe is journaled, and the stop with the two failures it rests on.
    state = FileEvidenceStore(tmp_path / "buyer" / "evidence").watchdog.state(negotiation_id)
    assert state is not None and state.stop is not None
    assert [probe.detail for probe in state.stop.probes] == ["access did not answer"] * 2
    assert state.last_probe_at == state.stop.probes[-1].at
    assert read["watchdog"]["status"] == "stopped"
