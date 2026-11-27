"""Retained listing documents and seller evidence, through the canonical client.

The real registry app and its database, with `RegistryClient` over
`ASGITransport` signing as the maker: what a publisher sends is kept whole and
served as sent, a republication replaces it, refusals leave the stored listing
as it was, a row predating retained documents is rebuilt from its carriers with
no seller evidence, and the seller's publication record verifies against the
publisher keys the registry serves, offline, through ``kit/identity``'s
evidence verifier.

Reserved-name, unsupported-update, and schema refusals are built by the typed
client, which does not refuse them itself, so each is the registry's own
refusal.
"""

from __future__ import annotations

import base64
import json

import pytest
from market_identity import VerificationCode, verify_request_evidence
from market_identity.fixtures.messages import validate_request_record

from registry_client import ListingRequest, RegistryClientError, UpdateListingRequest
from core_registry.db.models import Listing, OrderStatusEnum

pytestmark = pytest.mark.asyncio

_OPTION = {"option_id": "a" * 64, "settlement": {"schema": "example.payment.v1"}}


def _listing(listing_id: str, **extra) -> ListingRequest:
    return ListingRequest(
        listing_id=listing_id,
        listing_resource={"region": "example", "offering_mode": "vm"},
        accepted_escrows=[],
        settlement_options=[_OPTION],
        storefront_url="http://localhost:8001/",
        extra=extra,
    )


async def _found(registry_client, listing_id: str):
    page = await registry_client.list_listings(status=None, limit=100)
    (listing,) = [row for row in page.listings if str(row.id) == listing_id]
    return listing


async def test_admitted_fields_are_served_as_published(registry_client):
    """Unknown properties the schema admits survive, explicit nulls included,
    at the top level and inside the capacity description; detail and search
    serve the same document."""
    request = _listing("kept-1", arbitrary_term={"value": None, "nested": [1, "two"]})
    request.listing_resource["unnamed_attribute"] = None

    await registry_client.publish_listing(request)

    detail = await registry_client.get_listing("kept-1")
    searched = await _found(registry_client, "kept-1")
    for listing in (detail, searched):
        assert listing.extra["arbitrary_term"] == {"value": None, "nested": [1, "two"]}
        assert listing.listing_resource == {
            "region": "example", "offering_mode": "vm", "unnamed_attribute": None,
        }
        assert listing.settlement_options == [_OPTION]


async def test_a_republication_replaces_the_document_whole(registry_client):
    await registry_client.publish_listing(_listing("replaced-1", withdrawn_term="present"))
    first = await registry_client.get_listing("replaced-1")

    await registry_client.publish_listing(_listing("replaced-1", replacement_term="present"))
    second = await registry_client.get_listing("replaced-1")

    # An omitted term disappears; no per-field merge restores it.
    assert "withdrawn_term" not in second.extra
    assert second.extra["replacement_term"] == "present"
    assert (second.id, second.publisher_id, second.created_at) == (
        first.id, first.publisher_id, first.created_at,
    )
    assert (
        second.publication["body_base64"]
        != first.publication["body_base64"]
    )


async def test_registry_owned_names_are_refused_by_name(registry_client):
    request = _listing("reserved-1", publisher_id=1, created_at="2026-01-01T00:00:00")

    with pytest.raises(RegistryClientError) as caught:
        await registry_client.publish_listing(request)

    assert caught.value.status_code == 422
    assert "publisher_id: reserved registry metadata" in caught.value.body
    assert "created_at: reserved registry metadata" in caught.value.body
    with pytest.raises(RegistryClientError) as missing:
        await registry_client.get_listing("reserved-1")
    assert missing.value.status_code == 404


async def test_an_update_refuses_any_key_but_status_and_oracle(registry_client):
    await registry_client.publish_listing(_listing("updated-1"))
    before = await registry_client.get_listing("updated-1")

    with pytest.raises(RegistryClientError) as caught:
        await registry_client.update_listing(
            "updated-1",
            UpdateListingRequest({"status": "closed", "max_duration_seconds": 60}),
        )

    assert caught.value.status_code == 422
    assert "max_duration_seconds" in caught.value.body
    after = await registry_client.get_listing("updated-1")
    # Refused whole: the status it also named is not applied either.
    assert after.status == "open"
    assert after.updates == before.updates == {}


async def test_a_schema_refusal_leaves_the_stored_listing_unchanged(registry_client):
    await registry_client.publish_listing(_listing("refused-1", term="first"))
    before = await registry_client.get_listing("refused-1")
    invalid = _listing("refused-1", term="second")
    invalid.listing_resource["gpu_interconnect"] = "carrier-pigeon"

    with pytest.raises(RegistryClientError) as caught:
        await registry_client.publish_listing(invalid)

    assert caught.value.status_code == 422
    assert "listing_resource.gpu_interconnect" in caught.value.body
    after = await registry_client.get_listing("refused-1")
    assert after.extra["term"] == "first"
    assert after.listing_resource == before.listing_resource
    assert after.publication == before.publication
    assert after.updated_at == before.updated_at


async def test_a_legacy_row_is_rebuilt_with_no_seller_evidence(registry_client, open_order):
    """A row stored before documents were retained is served from its carrier
    columns, with null publication evidence; its seller's next valid
    republication establishes the document and the proof together."""
    legacy = await registry_client.get_listing(open_order.listing_id)

    assert legacy.listing_resource == open_order.listing_resource
    assert legacy.accepted_escrows == open_order.accepted_escrows
    assert legacy.max_duration_seconds == 3600
    assert legacy.storefront_url == "http://localhost:8001/"
    assert legacy.publication is None
    assert legacy.updates == {}

    await registry_client.publish_listing(_listing(open_order.listing_id, term="retained"))
    republished = await registry_client.get_listing(open_order.listing_id)

    assert republished.extra["term"] == "retained"
    assert republished.listing_resource == {"region": "example", "offering_mode": "vm"}
    assert republished.publication["body_base64"]
    assert republished.created_at == legacy.created_at


async def test_a_legacy_row_is_bounded_by_rate_only_once_republished(
    registry_client, db_session, maker_publisher
):
    """A legacy row whose carriers held a rate inside the capacity description
    is rebuilt with no `pricing`, so a rate bound excludes it until its seller
    republishes the rate in `pricing`."""
    rate ={"amount": "2.00", "asset": "usd", "period": "hour"}
    db_session.add(
        Listing(
            listing_id="legacy-rated",
            publisher_id=maker_publisher.publisher_id,
            listing_resource={"region": "example", "asking_rate": rate},
            settlement_options=[_OPTION],
            status=OrderStatusEnum.open,
        )
    )
    db_session.commit()
    bound = {"asking_rate_max": "5", "asking_rate_asset": "usd", "asking_rate_period": "hour"}

    before = await registry_client.list_listings(**bound)
    legacy = await registry_client.get_listing("legacy-rated")
    await registry_client.publish_listing(_listing("legacy-rated", pricing={"asking_rate": rate}))
    after = await registry_client.list_listings(**bound)

    assert "pricing" not in legacy.extra
    assert legacy.listing_resource["asking_rate"] == rate
    assert [str(row.id) for row in before.listings] == []
    assert [str(row.id) for row in after.listings] == ["legacy-rated"]


async def test_update_evidence_is_kept_apart_and_reset_by_republication(registry_client):
    await registry_client.publish_listing(_listing("evidence-1"))
    published = await registry_client.get_listing("evidence-1")
    publication = published.publication

    await registry_client.update_listing(
        "evidence-1", UpdateListingRequest({"oracle_address": "oracle-example"})
    )
    await registry_client.update_listing(
        "evidence-1", UpdateListingRequest({"status": "closed"})
    )
    updated = await registry_client.get_listing("evidence-1")

    # Each update keeps its own signed request; the publication proof is untouched.
    assert updated.publication == publication
    updates = updated.updates
    assert set(updates) == {"oracle_address", "status"}
    assert updates["oracle_address"]["request"]["operation"] == "listing.update"
    assert json.loads(base64.b64decode(updates["status"]["body_base64"])) == {"status": "closed"}
    assert updated.extra["oracle_address"] == "oracle-example"
    assert updated.status == "closed"

    # A republication stating no status keeps the status and its evidence, and
    # replaces the commercial content, so the oracle update's evidence goes.
    await registry_client.publish_listing(_listing("evidence-1", term="republished"))
    republished = await registry_client.get_listing("evidence-1")
    assert set(republished.updates) == {"status"}
    assert republished.status == "closed"
    assert republished.publication != publication

    # One stating a status replaces that evidence too.
    await registry_client.publish_listing(_listing("evidence-1", status="open"))
    reopened = await registry_client.get_listing("evidence-1")
    assert reopened.updates == {}
    assert reopened.status == "open"


async def test_the_seller_s_publication_record_verifies_with_the_publisher_keys(registry_client, maker_signer):
    """registry-discovery "A consumer verifies a listing's commercial term": a
    buyer decodes the retained body and verifies the seller's request record
    against it offline, with no freshness, under the publisher keys the registry
    serves, and reads the terms from the verified body."""
    pricing = {"asking_rate": {"amount": "2.50", "asset": "usd", "period": "hour"}}
    await registry_client.publish_listing(_listing("proof-1", pricing=pricing))
    listing = await registry_client.get_listing("proof-1")

    body = base64.b64decode(listing.publication["body_base64"])
    record = listing.publication["request"]
    validate_request_record(record, resource=False)
    verification = verify_request_evidence(
        record,
        body=body,
        trusted=listing.publisher_principals,
        expected_role="seller",
        expected_operation="listing.publish",
        expected_resource=None,
    )

    assert verification.code is VerificationCode.VERIFIED
    assert record["query"] == "?"
    assert record["principal"] == f"eip191:{maker_signer.identity.identifier}"
    assert json.loads(body)["listing_id"] == "proof-1"
    assert json.loads(body)["pricing"] == pricing == listing.extra["pricing"]

    # The same record does not cover a body the seller did not sign: the digest
    # the verifier computes from it is not the one the signature covers.
    forged = json.loads(body)
    forged["pricing"]["asking_rate"]["amount"] = "0.01"
    assert verify_request_evidence(
        record, body=json.dumps(forged).encode(), trusted=listing.publisher_principals
    ).code is VerificationCode.INVALID_PROOF


async def test_an_update_s_record_names_its_listing(registry_client):
    await registry_client.publish_listing(_listing("update-record"))
    await registry_client.update_listing("update-record", UpdateListingRequest({"status": "closed"}))
    listing = await registry_client.get_listing("update-record")

    record = listing.updates["status"]["request"]
    validate_request_record(record, resource=True)
    verification = verify_request_evidence(
        record,
        body=base64.b64decode(listing.updates["status"]["body_base64"]),
        trusted=listing.publisher_principals,
        expected_operation="listing.update",
        expected_resource="update-record",
    )
    assert verification.verified


@pytest.mark.parametrize("name", ["publication", "updates", "publisher_publication", "publisher_updates"])
async def test_a_seller_term_named_like_the_evidence_is_refused_by_name(registry_client, name):
    """registry-discovery "A seller publishes a term named like the evidence"."""
    with pytest.raises(RegistryClientError) as caught:
        await registry_client.publish_listing(_listing(f"named-{name}", **{name: {"seller": "term"}}))

    assert caught.value.status_code == 422
    assert f"{name}: reserved registry metadata" in caught.value.body


async def test_a_publication_kept_under_version_2_is_read_as_kept(registry_client, db_session, maker_publisher):
    """registry-discovery "A listing published before the cutover is read": the
    row the migration carried, its version 2 envelope as its record, is served as
    stored, for a consumer to verify by its protocol."""
    v2_publication = {
        "body_base64": base64.b64encode(b'{"listing_id":"before-cutover"}').decode(),
        "request": {
            "protocol": "arkhai.market-request-signature.v2",
            "role": "seller",
            "principal": {"scheme": "eip191", "identifier": "0x" + "33" * 20},
            "method": "POST",
            "operation": "listing.publish",
            "resource": "listings",
            "request_id": "v2-publication",
            "timestamp": 1_790_000_000,
            "body_hash": "a" * 64,
            "proof": {"scheme": "eip191", "value": "0x" + "00" * 65},
        },
    }
    db_session.add(
        Listing(
            listing_id="before-cutover",
            publisher_id=maker_publisher.publisher_id,
            published_document=_listing("before-cutover").to_dict(),
            publication=v2_publication,
            updates={"status": v2_publication},
            listing_resource={},
            status=OrderStatusEnum.open,
        )
    )
    db_session.commit()

    listing = await registry_client.get_listing("before-cutover")

    assert listing.publication == v2_publication
    assert listing.updates == {"status": v2_publication}
