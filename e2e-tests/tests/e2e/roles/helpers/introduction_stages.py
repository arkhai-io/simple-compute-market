"""Stages of the compute family's settlement by introduction, defined once.

The scenario: a site's operator declares a capacity-backed pool and an unbacked
one, each at an asking rate, and a storefront pool override offers the unbacked
pool by introduction alone. One rate-bounded buyer query returns both pools'
listings, so unbacked supply is comparable on price with backed supply, and
leaves out a listing that publishes no rate. The buyer negotiates the unbacked
listing's introduction and reveals it through the production ``market`` CLI,
which delivers the seller's contact to the buyer's own file sink; the storefront
delivers the buyer's contact to the seller by SMTP, read back from the lane's
Mailpit.

Each stage here is one every compute domain runs identically. A domain's
scenario module declares the stages in order by subclassing them with an empty
body::

    class TestStage02_Reveal(Stage02_Reveal):
        pass

and inserts its own stages between them, as ``compute_deal_stages.py``'s
domains do; the classes are not named ``Test*``, so pytest collects them only
through those subclasses. What differs reaches a stage through two fixtures
each domain's module provides: ``introduction_state``, an ``IntroductionState``,
and ``introduction_driver``, the domain's ``IntroductionDriver``, which seeds
the supply and speaks the domain's CLI verbs; a driver returns what it did, and
only stages write the state. ``tests/unit/test_introduction_stages.py`` holds
each domain to the shared stages and fields.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from tests.e2e.roles.buyer_cli import BuyerCli
from tests.e2e.roles.helpers.domain_deal import require_state

CONTACT_MECHANISM = "contact-exchange.v1"
#: The asset and period every rate in the scenario is quoted in.
RATE_QUERY = "asking_rate_asset=usd asking_rate_period=hour"
BACKED_RATE = "3.00"
UNBACKED_RATE = "2.50"
#: Admits both pools' rates; a bound below ``UNBACKED_RATE`` admits neither.
RATE_BOUND = "3.00"
BELOW_EVERY_RATE = "2.49"
# Development fixtures on a reserved domain, never to be used on a public network.
BUYER_CONTACT_EMAIL = "buyer@introduction-e2e.invalid"
#: How long seller-side mail may take to arrive: it is sent off the request
#: path, so it is awaited, bounded.
MAIL_DEADLINE_SECONDS = 30.0


@dataclass
class IntroductionState:
    """What the shared stages hand each other, one field per producer.

    Each field is declared with a default that reads as absent, because
    ``require_state`` reads through ``getattr``.
    """

    #: The module's run tag, set when the fixture builds the state.
    run: str = ""
    #: The retention window readiness discloses, before any contact is given.
    disclosure: dict[str, Any] | None = None
    backed_listing: str = ""
    unbacked_listing: str = ""
    #: Listings the scenario published without an asking rate.
    rateless_listings: tuple[str, ...] = ()
    run_id: str = ""
    negotiation_id: str = ""
    obligation_ref: str = ""
    revealed: bool = False


@dataclass(frozen=True)
class SeededSupply:
    """The listings a domain's supply published, which the stage records."""

    backed_listing: str
    unbacked_listing: str
    rateless_listings: tuple[str, ...] = ()


class IntroductionDriver(Protocol):
    """A compute domain's part of the introduction scenario."""

    #: The buyer whose own delivery sink is a file the scenario reads back.
    buyer: BuyerCli
    #: The file the buyer's sink writes each delivered introduction to.
    delivered: Any
    #: The seller contact the storefront reveals for the listing's origin.
    seller_contact_email: str
    #: The lane's Mailpit API, which receives the seller-side delivery.
    mailpit_url: str

    def assert_loops_held(self) -> None:
        """The module's storefront hold, read back through system status."""

    def retention_disclosure(self) -> dict[str, Any] | None:
        """The introduction retention window the storefront's readiness discloses."""

    def seed_supply(self, run: str) -> SeededSupply:
        """Declare the backed and unbacked pools at their rates, named for
        ``run``, offer the unbacked one by introduction, step publication, and
        return the listings it published."""

    def discover(self, query: str) -> set[str]:
        """The listings a buyer finds with resource query ``query``."""

    def listing(self, listing_id: str) -> Any:
        """One listing as the registry serves it to a buyer."""

    def request_introduction_args(self, listing_id: str, option_id: str) -> list[str]:
        """The ``market`` arguments that negotiate one introduction option."""

    def introduce_args(self, run_id: str, contact_email: str) -> list[str]:
        """The ``market`` arguments that reveal a negotiated introduction."""


def _json_line(text: str) -> dict[str, Any]:
    """The JSON object a command printed last."""
    for line in reversed(text.strip().splitlines()):
        if line.startswith("{"):
            return json.loads(line)
    raise AssertionError(f"no JSON object in output: {text[-2000:]}")


class Stage00_DisclosureBeforeCommitment:
    def test_00_readiness_discloses_the_retention_window(
        self, introduction_driver: IntroductionDriver, introduction_state: IntroductionState
    ):
        """A buyer reads the retention window before handing over a contact;
        the module's loops are held, so every publication is a stepped one."""
        introduction_driver.assert_loops_held()
        disclosure = introduction_driver.retention_disclosure()
        assert disclosure and disclosure["scope"] == "introduction_record", disclosure
        introduction_state.disclosure = disclosure


class Stage01_BackedAndUnbackedSupply:
    def test_01_both_pools_publish_at_an_asking_rate(
        self, introduction_driver: IntroductionDriver, introduction_state: IntroductionState
    ):
        supply = introduction_driver.seed_supply(introduction_state.run)
        assert supply.backed_listing and supply.unbacked_listing, supply
        introduction_state.backed_listing = supply.backed_listing
        introduction_state.unbacked_listing = supply.unbacked_listing
        introduction_state.rateless_listings = supply.rateless_listings

    def test_02_one_rate_bounded_query_returns_both(
        self, introduction_driver: IntroductionDriver, introduction_state: IntroductionState
    ):
        require_state(introduction_state, "unbacked_listing", "backed_listing")
        both = {introduction_state.backed_listing, introduction_state.unbacked_listing}
        found = introduction_driver.discover(f"asking_rate<={RATE_BOUND} {RATE_QUERY}")
        assert both <= found, found
        # A bound below the unbacked rate excludes it and keeps nothing above it.
        cheaper = introduction_driver.discover(
            f"asking_rate<={BELOW_EVERY_RATE} {RATE_QUERY}"
        )
        assert not both & cheaper, cheaper
        # A listing that publishes no rate is never returned for a rate bound,
        # and every listing that is returned publishes one.
        assert not set(introduction_state.rateless_listings) & found
        for listing_id in found:
            listing = introduction_driver.listing(listing_id)
            assert listing.listing_resource.get("asking_rate"), listing_id

    def test_03_the_unbacked_listing_offers_only_an_introduction(
        self, introduction_driver: IntroductionDriver, introduction_state: IntroductionState
    ):
        require_state(introduction_state, "unbacked_listing")
        listing = introduction_driver.listing(introduction_state.unbacked_listing)
        mechanisms = [dict(option)["mechanism"] for option in listing.settlement_options]
        assert mechanisms == [CONTACT_MECHANISM], listing.settlement_options


class Stage02_Reveal:
    def test_04_the_buyer_cli_negotiates_and_reveals(
        self, introduction_driver: IntroductionDriver, introduction_state: IntroductionState
    ):
        require_state(introduction_state, "unbacked_listing")
        (option,) = [
            dict(option)
            for option in introduction_driver.listing(
                introduction_state.unbacked_listing
            ).settlement_options
        ]
        buyer = introduction_driver.buyer

        negotiated = buyer.run(
            introduction_driver.request_introduction_args(
                introduction_state.unbacked_listing, option["option_id"]
            ),
            timeout=120.0,
        )
        assert negotiated.returncode == 0, negotiated.stdout()[-2000:]
        accepted = _json_line(negotiated.stdout())
        assert accepted.get("status") == "agreed", accepted
        introduction_state.run_id = accepted["run_id"]
        introduction_state.negotiation_id = str(accepted.get("negotiation_id") or "")
        introduction_state.obligation_ref = accepted["obligation_ref"]

        revealed = buyer.run(
            introduction_driver.introduce_args(
                introduction_state.run_id, BUYER_CONTACT_EMAIL
            ),
            timeout=120.0,
        )
        assert revealed.returncode == 0, revealed.stdout()[-2000:]
        projection = _json_line(revealed.stdout())
        assert projection["revealed"] is True
        assert projection["counterparty_contact"] == {
            "email": introduction_driver.seller_contact_email
        }
        assert projection["retention"] == introduction_state.disclosure
        # The buyer's own sink holds the seller's contact, in an event naming as
        # its counterparty the seller the accepted Agreement names.
        events = [
            json.loads(line)
            for line in introduction_driver.delivered.read_text().splitlines()
            if line
        ]
        (event,) = [
            event
            for event in events
            if event.get("obligation_ref") == introduction_state.obligation_ref
        ]
        seller = accepted["agreement"]["seller"]
        assert event["role"] == "buyer", event
        assert event["contact"] == {"email": introduction_driver.seller_contact_email}
        assert event["counterparty"] == f"{seller['scheme']}:{seller['identifier']}", event
        introduction_state.revealed = True


class Stage03_SellerDelivery:
    def test_05_the_seller_is_mailed_the_buyers_contact(
        self, introduction_driver: IntroductionDriver, introduction_state: IntroductionState
    ):
        """Seller-side delivery runs off the request path, so it is awaited, bounded."""
        require_state(introduction_state, "revealed")
        mailpit = introduction_driver.mailpit_url
        deadline = time.monotonic() + MAIL_DEADLINE_SECONDS
        while True:
            listing = httpx.get(f"{mailpit}/api/v1/messages", timeout=10).json()
            matching = [
                message
                for message in listing.get("messages") or []
                if introduction_state.obligation_ref in str(message.get("Subject", ""))
            ]
            if matching:
                break
            assert time.monotonic() < deadline, listing
            time.sleep(0.5)
        (message,) = matching
        recipients = {entry.get("Address") for entry in message.get("To") or []}
        assert recipients == {introduction_driver.seller_contact_email}, message
        body = httpx.get(f"{mailpit}/api/v1/message/{message['ID']}", timeout=10).json()
        assert BUYER_CONTACT_EMAIL in str(body.get("Text", "")), body
