"""The VM buyer's acceptance-bound pricing record and its archived evidence.

The record keeps the seller-signed publication beside the inputs the amount codec
reads, and every one of those inputs must equal what the seller signed. A resumed
run verifies accepted pricing again from the signed exchange it archived: the
seller's acceptance, made at once or answering the buyer's accept of a counter,
and the buyer's request it answered.

Every key and identity here is a deterministic development value; none may be
used on a public network.
"""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path

import pytest
from market_deal_lifecycle_buyer import FileEvidenceStore
from market_identity import (
    CapturedEnvelope,
    RequestEnvelope,
    ResponseEnvelope,
    TrustedIdentitySet,
    canonical_body_hash,
    sign_request,
    sign_response,
)

from arkhai_vms_buyer.pricing_record import (
    verified_pricing_publication,
    verify_pricing_acceptance,
    verify_recovered_pricing,
)
from identity_helpers import BUYER_SIGNER, SELLER_SIGNER, SELLER_TRUST
from test_per_period_acceptance import (
    PERIOD_PRICE,
    QUARTER_HOUR,
    _accepting_reply,
    _agreement,
    _signed_record,
)

_BUYER_TRUST = TrustedIdentitySet(identities=(BUYER_SIGNER.identity,))


def _project(_option):
    return QUARTER_HOUR


@pytest.mark.parametrize("key", [
    "listing_id", "storefront_url", "listing_resource", "pricing", "settlement_options",
    "rate_structure",
])
def test_a_record_input_differing_from_the_signed_publication_is_refused(key):
    """``rate_structure`` is the codec's copy of ``pricing.rate_structure``; it is
    held to the signed one like every input the seller published."""
    record = _signed_record()
    record[key] = "substituted"
    with pytest.raises(ValueError, match=f"retained pricing differs from seller publication: {key}$"):
        verified_pricing_publication(record)


def test_a_publication_proof_for_another_operation_or_publisher_is_refused():
    record = _signed_record()
    record["publisher_publication"]["request"]["operation"] = "listing.update"
    with pytest.raises(ValueError, match="seller publication verification failed"):
        verified_pricing_publication(record)
    record = _signed_record()
    record["publisher_principals"] = _BUYER_TRUST.model_dump(mode="json")
    with pytest.raises(ValueError, match="seller publication verification failed"):
        verified_pricing_publication(record)


def test_a_record_that_kept_no_publication_proof_fails_closed():
    record = {key: value for key, value in _signed_record().items()
              if key not in {"publisher_publication", "publisher_principals"}}
    with pytest.raises(ValueError, match="requires retained seller publication proof and trust"):
        verified_pricing_publication(record)


@pytest.mark.parametrize(("pin", "refusal"), [
    ({"multiplier": "9999"}, "signed pricing multiplier differs from transcript"),
    ({"rate_structure_digest": "0" * 64}, "accepted pricing requires a matching signed pricing pin"),
    ({"multiplier": "010000"}, "signed pricing pin has an invalid multiplier"),
])
def test_an_acceptance_pinning_another_multiplier_or_structure_is_refused(pin, refusal):
    record = _signed_record()
    reply = _accepting_reply(record)
    reply["pricing_pin"] = {**reply["pricing_pin"], **pin}
    with pytest.raises(ValueError, match=refusal):
        verify_pricing_acceptance(
            record, _agreement(record, PERIOD_PRICE), reply,
            multiplier=10_000, project_billing=_project,
        )


class _Exchange:
    """The signed requests and responses of one negotiation, archived as the
    buyer's evidence store keeps them."""

    def __init__(self, path: Path) -> None:
        self.store = FileEvidenceStore(path)
        self.record = _signed_record()
        self.agreement = _agreement(self.record, PERIOD_PRICE)
        self.agreement_bytes = base64.b64encode(self.agreement.model_dump_json().encode()).decode()
        self._timestamp = 1_793_966_341

    def acceptance(self, **changes) -> dict:
        return {
            **_accepting_reply(self.record),
            "negotiation_id": self.agreement.negotiation_id,
            "buyer_principal": self.agreement.buyer,
            "seller_principal": self.agreement.seller,
            "agreement": self.agreement.model_dump(mode="json"),
            "agreement_bytes": self.agreement_bytes,
            **changes,
        }

    def counter(self) -> dict:
        reply = _accepting_reply(self.record)
        return {
            "action": "counter", "negotiation_id": self.agreement.negotiation_id,
            "rate_structure_digest": reply["rate_structure_digest"],
            "proposal": {"fields": {"amount": "10000"}},
        }

    def exchange(self, operation: str, request_body: dict, reply: dict, *, archive_request: bool = True) -> None:
        resource = self.agreement.listing_id if operation == "negotiate_new" else self.agreement.negotiation_id
        request_id = f"exchange-{self._timestamp}"
        request = sign_request(signer=BUYER_SIGNER, envelope=RequestEnvelope(
            principal=BUYER_SIGNER.identity, role="buyer", method="POST", operation=operation,
            resource=resource, request_id=request_id, timestamp=self._timestamp,
            body_hash=canonical_body_hash(request_body),
        ))
        response = sign_response(signer=SELLER_SIGNER, envelope=ResponseEnvelope(
            principal=SELLER_SIGNER.identity, role="seller", method="POST", operation=operation,
            resource=resource, request_id=request_id, timestamp=self._timestamp + 1, status=200,
            body_hash=canonical_body_hash(reply),
        ))
        self._timestamp += 2
        self.store.capture(CapturedEnvelope(
            response, json.dumps(reply).encode(), {}, response.timestamp, SELLER_TRUST,
        ))
        if archive_request:
            self.store.capture(CapturedEnvelope(
                request, json.dumps(request_body).encode(), {}, request.timestamp, _BUYER_TRUST,
            ))

    def opening(self, multiplier: str = "10000") -> dict:
        return {
            "listing_id": self.agreement.listing_id, "buyer_principal": self.agreement.buyer,
            "proposal": {"fields": {"amount": multiplier}},
        }

    def verify(self, evidence=None) -> None:
        verify_recovered_pricing(
            self.record, self.agreement, self.agreement_bytes,
            evidence if evidence is not None else self.evidence(), project_billing=_project,
        )

    def evidence(self):
        return asyncio.run(self.store.read(self.agreement.negotiation_id))


def test_an_immediate_acceptance_verifies_from_its_archived_exchange(tmp_path):
    archive = _Exchange(tmp_path)
    archive.exchange("negotiate_new", archive.opening(), archive.acceptance(
        proposal={"fields": {"amount": "10000"}},
    ))
    archive.verify()


def test_an_accepted_counter_verifies_at_the_multiplier_the_seller_countered(tmp_path):
    """The seller's acceptance of the buyer's accept carries no proposal: the
    multiplier it pins is the one the seller's signed counter offered."""
    archive = _Exchange(tmp_path)
    archive.exchange("negotiate_new", archive.opening("9000"), archive.counter())
    archive.exchange(
        "negotiate_continue", {"action": "accept", "buyer_principal": archive.agreement.buyer},
        archive.acceptance(),
    )
    archive.verify()


def test_an_archived_acceptance_altered_after_signing_is_refused(tmp_path):
    archive = _Exchange(tmp_path)
    archive.exchange("negotiate_new", archive.opening(), archive.acceptance(
        proposal={"fields": {"amount": "10000"}},
    ))
    raw = json.loads(archive.evidence().model_dump_json())
    for item in raw["items"]:
        body = json.loads(base64.b64decode(item["body"]))
        if item["kind"] == "signed_response":
            body["pricing_pin"]["multiplier"] = "9999"
            item["body"] = base64.b64encode(json.dumps(body).encode()).decode()
    altered = type(archive.evidence()).model_validate(raw)
    with pytest.raises(ValueError, match="retained pricing response signature/context is invalid"):
        archive.verify(altered)


def test_an_acceptance_without_its_archived_buyer_request_is_refused(tmp_path):
    archive = _Exchange(tmp_path)
    archive.exchange("negotiate_new", archive.opening(), archive.acceptance(
        proposal={"fields": {"amount": "10000"}},
    ), archive_request=False)
    with pytest.raises(ValueError, match="has no matching signed buyer request"):
        archive.verify()


def test_an_archive_without_the_signed_acceptance_is_refused(tmp_path):
    archive = _Exchange(tmp_path)
    archive.exchange("negotiate_new", archive.opening(), archive.counter())
    with pytest.raises(ValueError, match="requires retained signed acceptance evidence"):
        archive.verify()
