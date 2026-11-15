"""``market bare-metal buy --watchdog`` against the composed storefront on a recurring option.

Application integration: the production buyer commands (``buyer_commands``) run
against the bare-metal app served over loopback with the installed recurring
wiring under a declaration listing ``charged`` and ``returned``
(``recurring_world``); beyond ``buyer_commands``' doubles, the buyer CLI's
``wait_clock`` factory runs its waits in fake time. The buyer approves the on-demand option's mandate at the
in-process payments engine, which both sides read, and commits; end service
refuses the commit of a rate deal while rate servicing is not composed, so the
deal never becomes available. The watchdog's opt-in alone must never read as
protection.

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


async def test_a_watched_purchase_whose_commit_is_refused_is_never_watched(tmp_path, monkeypatch):
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

        bought = buyer.invoke(
            "buy", listing_id, "--option-id", on_demand["option_id"], "--ssh-public-key", SSH_KEY,
            "--duration-seconds", "3600", "--watchdog",
            "--delivery-timeout-seconds", "10", "--poll-interval", "5",
        )

        # The commit is accepted and the deal refused before any capacity, so
        # it never becomes available: the command exits at its timeout, which
        # it waited out in fake time, reading the deal's delivery each poll.
        assert bought.exit_code == 4, bought.output
        assert waits.now == 1010
        purchase, watched = (json.loads(line) for line in bought.stdout.strip().splitlines()[-2:])
        assert purchase["fulfillment"]["status"] == "committed"
        negotiation_id = purchase["fulfillment"]["negotiation_id"]
        assert watched == {"run_id": purchase["run_id"], "negotiation_id": negotiation_id,
                           "available": False, "watchdog": None}
        # No probe ran: the bound is never stated, and no stop reached the engine.
        assert "Watchdog running" not in bought.stderr
        assert payments.count("approve") == 1 and payments.count("submit_event") == 0

        read = buyer.run("delivery", "--run-id", purchase["run_id"])

    # The opt-in is persisted, yet the deal reads unmonitored, never as protected.
    state = FileEvidenceStore(tmp_path / "buyer" / "evidence").watchdog.state(negotiation_id)
    assert state is not None and state.last_probe_at is None and state.stop is None
    assert read["watchdog"] == {"status": "unmonitored", "last_probe_at": None}
    assert read["delivery"]["progress"] != "active" and read["delivery"]["recorded_end"] is None
