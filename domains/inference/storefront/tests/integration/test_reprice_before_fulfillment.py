"""A seller reprices between acceptance and fulfillment; the key carries the terms the buyer accepted.

The buyer negotiates, settles, and reads its result through the storefront's
typed client, and the seller reprices through its own. Beyond the storefront,
the chain is scripted at the Alkahest stage's injected escrow verifier and the
attestation client it is handed, and the inference authority at its HTTP
boundary; the quota site and registries are the other integration tests'.
Every key and address is a deterministic development value, never used on a
public network.
"""

from __future__ import annotations

from arkhai_api.issuance import accepted_terms_digest
from arkhai_inference.listings import InferenceModelCard, accepted_terms
from arkhai_inference.schema import InferenceMaterialization
from storefront_client.settlement_routes import SETTLE

from inference_storefront import container
from tests.integration.deal_parties import (
    ATTESTATION_UID,
    BUYER_SIGNER,
    BUYER_WALLET,
    QUANTITY,
    ScriptedChain,
    open_negotiation,
    publish_request,
    running,
)
from tests.integration.issuance_authority import ESCROW_UID, ScriptedAuthority


async def test_the_key_is_issued_on_the_accepted_terms_after_the_seller_reprices(
    storefront, registries, monkeypatch
):
    chain = ScriptedChain()
    authority = ScriptedAuthority()
    async with running(monkeypatch, chain, authority) as parties:
        accepted_listing = await parties.public.get_listing(
            (await parties.listings.publish_from_quota(publish_request(3))).listing_id
        )
        opened = await open_negotiation(parties, accepted_listing)
        assert opened["action"] == "accept"

        # The seller reprices through its routes: it withdraws the accepted
        # listing and publishes its quota again at another rate. The stored
        # row of the accepted listing is then rewritten at the new rate too,
        # which no route does, so only the acceptance record still holds 3.
        await parties.seller.close_listing(accepted_listing.listing_id)
        repriced = await parties.public.get_listing(
            (await parties.listings.publish_from_quota(publish_request(9))).listing_id
        )
        await container.resolved_sqlite_client.update_listing(
            listing_id=accepted_listing.listing_id,
            listing_resource={
                **accepted_listing.listing_resource,
                "rate_card": repriced.listing_resource["rate_card"],
            },
        )
        rewritten = await parties.public.get_listing(accepted_listing.listing_id)

        await parties.buyer.authenticated_request(
            "POST",
            SETTLE.path(ESCROW_UID),
            role=SETTLE.role,
            operation=SETTLE.operation,
            resource=ESCROW_UID,
            body={
                "negotiation_id": opened["negotiation_id"],
                "buyer_principal": BUYER_SIGNER.identity.model_dump(mode="json"),
                "buyer_evm_address": BUYER_WALLET,
                "chain_name": "anvil",
            },
        )
        settled = await parties.admin.wait_for_settlement(ESCROW_UID, timeout=10)
        status = await parties.buyer.get_settle_status(ESCROW_UID)

    assert (settled.ready, settled.status) == (True, "ready")
    assert repriced.listing_resource["rate_card"]["request_credits"] == "9"
    assert rewritten.listing_resource["rate_card"]["request_credits"] == "9"
    # Verified against the plan committed at acceptance, which the reprice
    # does not touch.
    (verified,) = chain.verified_against
    assert verified["obligations"]
    (body,) = authority.requests
    terms = accepted_terms(InferenceModelCard.model_validate(accepted_listing.listing_resource))
    assert body["accepted_terms"] == terms
    assert body["terms_digest"] == accepted_terms_digest(terms)
    assert body["request_charge"] == 3
    assert body["quantity"] == QUANTITY
    assert chain.attestations == [ESCROW_UID]
    assert status.status == "ready"
    materialization = InferenceMaterialization.model_validate(
        status.tenant_credentials["materialization"]
    )
    assert materialization.rate_card.request_credits == 3
    assert materialization.listing_resource.model_dump(mode="json") == accepted_listing.listing_resource
