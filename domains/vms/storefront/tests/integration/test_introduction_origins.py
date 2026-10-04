"""Settlement by introduction on the VM storefront, end to end in one app.

The publication loop publishes a listing from a site, a buyer negotiates it to
acceptance, and the production buyer's ``IntroductionTransport`` reveals it over
loopback HTTP. The contact the reveal carries is the one configured for the site
the listing's durable binding records -- the same site the negotiation inherited
-- and never another site's.
"""

from __future__ import annotations

from dataclasses import replace

import asyncio

import pytest
from arkhai_vms import make_vm_provision_terms
from arkhai_vms_buyer.buyer_client import negotiate_with_seller
from core_buyer.negotiation_client import AuthenticatedHTTPError
from market_core.schemas import SettlementOption, SettlementSelection
from market_identity import TrustedIdentitySet

from tests.introduction_deals import (
    BUYER_CONTACT,
    CONTACT_PUBLISHABLE,
    accept_introduction,
    introduction_transport,
    offer_introduction,
    publish,
)
from tests.fake_site import TEST_MARKETPLACE_SIGNER
from tests.loopback import serving
from tests.publication_app import (
    BUYER_SIGNER,
    SITE,
    SITE_B,
    SITE_CONTACTS,
    pool,
    publication_app,
)

pytestmark = pytest.mark.asyncio


async def test_one_site_governs_publication_negotiation_and_reveal(tmp_path) -> None:
    async with publication_app(
        tmp_path,
        mechanism_fulfillment=CONTACT_PUBLISHABLE,
        contacts={SITE: SITE_CONTACTS[SITE]},
    ) as world:
        world.pools.append(pool("broker-a", backing="unbacked"))
        await offer_introduction(world, SITE, "broker-a")
        listing = (await publish(world))["broker-a"]

        published = await world.db.load_listing_binding(listing_id=listing["listing_id"])
        negotiation_id, obligation_ref = await accept_introduction(world, listing)
        inherited = await world.db.load_thread_binding(negotiation_id=negotiation_id)
        with serving(world.app) as base_url:
            revealed = introduction_transport(base_url).start(
                negotiation_id=negotiation_id,
                obligation_ref=obligation_ref,
                contact_payload=dict(BUYER_CONTACT),
            )
            reread = introduction_transport(base_url).read(obligation_ref=obligation_ref)

        assert published.site_id == inherited.site_id == SITE
        assert revealed["counterparty_contact"] == SITE_CONTACTS[SITE]
        assert reread["counterparty_contact"] == SITE_CONTACTS[SITE]
        assert revealed["obligation_ref"] == obligation_ref


async def test_each_site_reveals_its_own_sellers_contact(tmp_path) -> None:
    async with publication_app(
        tmp_path,
        mechanism_fulfillment=CONTACT_PUBLISHABLE,
        second_site=True,
        contacts=SITE_CONTACTS,
    ) as world:
        world.pools.append(pool("broker-a", backing="unbacked"))
        world.pools_b.append(pool("broker-b", backing="unbacked"))
        await offer_introduction(world, SITE, "broker-a")
        await offer_introduction(world, SITE_B, "broker-b")
        listings = await publish(world)

        revealed = {}
        with serving(world.app) as base_url:
            for pool_id, site in (("broker-a", SITE), ("broker-b", SITE_B)):
                negotiation_id, obligation_ref = await accept_introduction(world, listings[pool_id])
                revealed[site] = introduction_transport(base_url).start(
                    negotiation_id=negotiation_id,
                    obligation_ref=obligation_ref,
                    contact_payload=dict(BUYER_CONTACT),
                )

        assert revealed[SITE]["counterparty_contact"] == SITE_CONTACTS[SITE]
        assert revealed[SITE_B]["counterparty_contact"] == SITE_CONTACTS[SITE_B]


async def test_a_site_without_a_contact_offers_and_reveals_no_introduction(tmp_path) -> None:
    async with publication_app(
        tmp_path,
        mechanism_fulfillment=CONTACT_PUBLISHABLE,
        second_site=True,
        contacts={SITE: SITE_CONTACTS[SITE]},
    ) as world:
        world.pools.append(pool("broker-a", backing="unbacked"))
        world.pools_b.append(pool("broker-b", backing="unbacked"))
        await offer_introduction(world, SITE, "broker-a")
        await offer_introduction(world, SITE_B, "broker-b")
        listings = await publish(world)

        # Site B has no contact, so its unbacked pool has nothing to offer.
        assert "broker-b" not in listings
        assert "broker-a" in listings


async def test_a_reveal_whose_site_lost_its_contact_is_refused_before_anything(
    tmp_path,
) -> None:
    """A deal accepted while its site had a contact, revealed after the site's
    contact was removed from the running configuration."""
    async with publication_app(
        tmp_path,
        mechanism_fulfillment=CONTACT_PUBLISHABLE,
        second_site=True,
        contacts=SITE_CONTACTS,
    ) as world:
        world.pools_b.append(pool("broker-b", backing="unbacked"))
        await offer_introduction(world, SITE_B, "broker-b")
        listing = (await publish(world))["broker-b"]
        negotiation_id, obligation_ref = await accept_introduction(world, listing)

        settlement = world.composition.settlement_config
        contact = settlement.mechanism_config("contact")
        world.composition.settlement_config = replace(
            settlement,
            mechanisms={
                **settlement.mechanisms,
                "contact": contact.model_copy(
                    update={"origins": {SITE: contact.origins[SITE]}}
                ),
            },
        )

        with serving(world.app) as base_url:
            with pytest.raises(AuthenticatedHTTPError) as refused:
                introduction_transport(base_url).start(
                    negotiation_id=negotiation_id,
                    obligation_ref=obligation_ref,
                    contact_payload=dict(BUYER_CONTACT),
                )

        assert "seller_contact_unavailable" in str(refused.value)
        assert await world.contact_exchange.store.load(obligation_ref) is None
        assert await world.composition.repository.load_settlement_obligation(
            obligation_ref
        ) is None


async def test_a_reveal_against_another_obligation_is_refused_with_no_payload(
    tmp_path,
) -> None:
    async with publication_app(
        tmp_path,
        mechanism_fulfillment=CONTACT_PUBLISHABLE,
        contacts={SITE: SITE_CONTACTS[SITE]},
    ) as world:
        world.pools.append(pool("broker-a", backing="unbacked"))
        await offer_introduction(world, SITE, "broker-a")
        listing = (await publish(world))["broker-a"]
        negotiation_id, obligation_ref = await accept_introduction(world, listing)
        with serving(world.app) as base_url:
            with pytest.raises(AuthenticatedHTTPError) as refused:
                introduction_transport(base_url).start(
                    negotiation_id=negotiation_id,
                    obligation_ref="0" * 64,
                    contact_payload=dict(BUYER_CONTACT),
                )

        assert "404" in str(refused.value)
        assert SITE_CONTACTS[SITE]["email"] not in str(refused.value)
        assert await world.contact_exchange.store.load(obligation_ref) is None
        assert await world.contact_exchange.store.load("0" * 64) is None


async def test_the_vm_buyer_accepts_an_introduction_the_seller_accepts_at_once(
    tmp_path,
) -> None:
    """The VM buyer's own negotiation client, as ``request-introduction`` runs it:
    the seller accepts the unpriced selection at the opening, and the buyer takes
    the deal with no amount and the seller's plan."""
    async with publication_app(
        tmp_path,
        mechanism_fulfillment=CONTACT_PUBLISHABLE,
        contacts={SITE: SITE_CONTACTS[SITE]},
    ) as world:
        world.pools.append(pool("broker-a", backing="unbacked"))
        await offer_introduction(world, SITE, "broker-a")
        listing = (await publish(world))["broker-a"]
        (raw,) = listing["settlement_options"]
        option = SettlementOption.model_validate(raw)
        rounds: list[tuple[int, str | None]] = []
        with serving(world.app) as base_url:
            outcome = await asyncio.to_thread(
                lambda: negotiate_with_seller(
                    seller_url=base_url,
                    principal=BUYER_SIGNER.identity,
                    signer=BUYER_SIGNER,
                    listing_id=listing["listing_id"],
                    resolve_seller_principals=lambda: TrustedIdentitySet(
                        identities=(TEST_MARKETPLACE_SIGNER.identity,)
                    ),
                    initial_price=0.0,
                    max_price=0.0,
                    provision_terms=make_vm_provision_terms(
                        duration_seconds=3600, ssh_public_key=""
                    ),
                    settlement_selection=SettlementSelection(
                        mechanism=option.mechanism,
                        option_id=option.option_id,
                        expiration_unix=1_900_000_000,
                    ),
                    policy_params={
                        "_selected_settlement_option": option.model_dump(mode="json")
                    },
                    max_rounds=10,
                    on_round=lambda number, _ours, theirs: rounds.append(
                        (number, theirs.get("action"))
                    ),
                )
            )

        assert outcome.status == "agreed", outcome
        assert outcome.agreed_amount is None
        assert rounds == [(0, "accept")]
        (obligation,) = outcome.settlement_plan.obligations
        assert obligation.mechanism == "contact-exchange.v1"

