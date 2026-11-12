"""Replay signed pricing pins and archived recovery without authority service I/O."""

from __future__ import annotations

import asyncio
import base64
import json
import runpy
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from arkhai_vms import make_vm_provision_terms
from arkhai_vms_buyer.negotiation_amounts import amount_codec
from arkhai_vms_buyer.pricing_record import (
    retained_pricing_record, verify_pricing_acceptance, verify_recovered_pricing,
)
from arkhai_vms_buyer.settlement_composition import buyer_settlement_registry
from arkhai_vms_negotiation.amounts import rate_structure_digest
from market_core.schemas import Agreement, PriceBasis, SettlementOption, derive_settlement_option_id
from market_deal_lifecycle_buyer import FileEvidenceStore
from market_identity import (
    CapturedEnvelope, Ed25519Signer, RequestEnvelope, ResponseEnvelope,
    TrustedIdentitySet, canonical_body_hash, sign_request, sign_response,
)


def refuses(call, fragment):
    try:
        call()
    except (ValueError, RuntimeError) as exc:
        assert fragment in str(exc), str(exc)
    else:
        raise AssertionError("expected refusal: " + fragment)


def main():
    source = runpy.run_path(str(Path(__file__).with_name("codec_probe.py")))
    original, _, publication = source["probe"]()
    seller = source["SELLER"]
    # Deterministic development identity; never use on a public network.
    buyer = Ed25519Signer(bytes(range(2, 34)))
    trust = TrustedIdentitySet(identities=(seller.identity,))
    publication.update({
        "seller_principal": seller.identity.model_dump(mode="json"),
        "listing_resource": {
            "vcpu_count": 4, "region": "California, US", "sla": 99.9,
            "pool_id": "public-development-pool",
        },
        "rate_structure": {"cpu": [{"asset": "USD/6", "rate": "2.5", "per": "hour"}]},
    })
    terms = make_vm_provision_terms(
        duration_seconds=7200, ssh_public_key="ssh-ed25519 public-development-fixture",
        compute_resource={"vcpu_count": 4},
    )
    installed = buyer_settlement_registry()
    for period, amount in ((None, 5000000), ("PT1M", 41667)):
        option = original.agreement.settlement
        projection = installed.project_billing
        if period is not None:
            fields = option.model_dump(mode="json", exclude_none=True)
            fields.pop("option_id")
            fields["settlement"]["period"] = period
            option = SettlementOption(option_id=derive_settlement_option_id(**fields), **fields)
            projection = lambda option: PriceBasis(unit="per_period", period="PT1M", period_seconds=60)
        publication["settlement_options"] = [option.model_dump(mode="json")]
        publication_request = sign_request(signer=seller, envelope=RequestEnvelope(
            principal=seller.identity, role="seller", method="POST", operation="listing.publish",
            resource="listings", request_id="public-development-publication", timestamp=1793966340,
            body_hash=canonical_body_hash(publication),
        ))
        record = retained_pricing_record({
            **deepcopy(publication), "seller_principal": seller.identity.model_dump(mode="json"),
            "publisher_principals": trust.model_dump(mode="json"),
            "publisher_publication": {
                "body_base64": base64.b64encode(json.dumps(publication).encode()).decode(),
                "request": publication_request.model_dump(mode="json"),
            },
        })
        digest = rate_structure_digest(publication)
        proposal = {"fields": {"amount": "10000"}, "settlement_selection": {
            "option_id": option.option_id, "settlement": {"schema": option.settlement_schema},
        }}
        codec = amount_codec(record, proposal, project_billing=projection)
        raw = original.agreement.model_dump(mode="json")
        raw.update(
            buyer=buyer.identity.model_dump(mode="json"), settlement=option.model_dump(mode="json"),
            amount=str(amount), provision_terms=terms.model_dump(mode="json"),
        )
        agreement = Agreement.model_validate(raw)
        agreement_bytes = base64.b64encode(agreement.model_dump_json().encode()).decode()
        reply = {
            "negotiation_id": agreement.negotiation_id, "action": "accept", "proposal": proposal,
            "buyer_principal": agreement.buyer, "seller_principal": agreement.seller,
            "agreement": agreement.model_dump(mode="json"), "agreement_bytes": agreement_bytes,
            "rate_structure_digest": digest, "pricing_pin": {
                "multiplier": "10000", "rate_structure_digest": digest,
            },
        }
        codec.validate_reply({"action": "counter", "rate_structure_digest": digest})
        codec.validate_accepted(SimpleNamespace(agreement=agreement, negotiated_scalar=10000), reply)
        assert codec.payment_from_scalar(10000, terms) == amount
        for changed, fragment in (
            ({**reply, "rate_structure_digest": "0" * 64}, "rate-structure identity"),
            ({**reply, "pricing_pin": None}, "matching signed pricing pin"),
            ({**reply, "pricing_pin": {**reply["pricing_pin"], "multiplier": "9999"}}, "differs from transcript"),
        ):
            refuses(lambda: codec.validate_accepted(
                SimpleNamespace(agreement=agreement, negotiated_scalar=10000), changed,
            ), fragment)
        for key in ("listing_id", "listing_resource", "rate_structure", "settlement_options"):
            changed = deepcopy(record)
            changed[key] = "substituted"
            refuses(lambda: verify_pricing_acceptance(
                changed, agreement, reply, multiplier=10000, project_billing=projection,
            ), "differs from seller publication")
        changed = deepcopy(record)
        changed["publisher_publication"]["request"]["operation"] = "listing.update"
        refuses(lambda: verify_pricing_acceptance(
            changed, agreement, reply, multiplier=10000, project_billing=projection,
        ), "publication verification failed")
        altered_amount = agreement.model_copy(update={"amount": amount + 1})
        refuses(lambda: verify_pricing_acceptance(
            record, altered_amount, reply, multiplier=10000, project_billing=projection,
        ), "monetary amount differs")

        with TemporaryDirectory() as directory:
            store = FileEvidenceStore(Path(directory))
            request_body = {
                "listing_id": agreement.listing_id, "buyer_principal": agreement.buyer,
                "proposal": proposal, "provision_terms": terms.model_dump(mode="json"),
            }
            request = sign_request(signer=buyer, envelope=RequestEnvelope(
                principal=buyer.identity, role="buyer", method="POST", operation="negotiate_new",
                resource=agreement.listing_id, request_id="public-development-opening",
                timestamp=1793966341, body_hash=canonical_body_hash(request_body),
            ))
            response = sign_response(signer=seller, envelope=ResponseEnvelope(
                principal=seller.identity, role="seller", method="POST", operation="negotiate_new",
                resource=agreement.listing_id, request_id=request.request_id, timestamp=1793966342,
                status=200, body_hash=canonical_body_hash(reply),
            ))
            store.capture(CapturedEnvelope(response, json.dumps(reply).encode(), {}, response.timestamp, trust))
            store.capture(CapturedEnvelope(
                request, json.dumps(request_body).encode(), {}, request.timestamp,
                TrustedIdentitySet(identities=(buyer.identity,)),
            ))
            evidence = asyncio.run(FileEvidenceStore(Path(directory)).read(agreement.negotiation_id))
            verify_recovered_pricing(record, agreement, agreement_bytes, evidence, project_billing=projection)
            continued = FileEvidenceStore(Path(directory) / "continued")
            counter = {key: value for key, value in reply.items() if key not in {
                "agreement", "agreement_bytes", "pricing_pin",
            }}
            counter["action"] = "counter"
            counter_response = sign_response(signer=seller, envelope=ResponseEnvelope(
                **{**response.model_dump(exclude={"proof"}), "body_hash": canonical_body_hash(counter)},
            ))
            continued.capture(CapturedEnvelope(counter_response, json.dumps(counter).encode(), {}, response.timestamp, trust))
            continued.capture(CapturedEnvelope(
                request, json.dumps(request_body).encode(), {}, request.timestamp,
                TrustedIdentitySet(identities=(buyer.identity,)),
            ))
            accept_body = {"action": "accept", "buyer_principal": agreement.buyer}
            accept_request = sign_request(signer=buyer, envelope=RequestEnvelope(
                principal=buyer.identity, role="buyer", method="POST", operation="negotiate_continue",
                resource=agreement.negotiation_id, request_id="public-development-accept",
                timestamp=1793966343, body_hash=canonical_body_hash(accept_body),
            ))
            accepted_reply = {key: value for key, value in reply.items() if key != "proposal"}
            accepted_response = sign_response(signer=seller, envelope=ResponseEnvelope(
                principal=seller.identity, role="seller", method="POST", operation="negotiate_continue",
                resource=agreement.negotiation_id, request_id=accept_request.request_id, timestamp=1793966344,
                status=200, body_hash=canonical_body_hash(accepted_reply),
            ))
            continued.capture(CapturedEnvelope(accepted_response, json.dumps(accepted_reply).encode(), {}, accepted_response.timestamp, trust))
            continued.capture(CapturedEnvelope(
                accept_request, json.dumps(accept_body).encode(), {}, accept_request.timestamp,
                TrustedIdentitySet(identities=(buyer.identity,)),
            ))
            verify_recovered_pricing(
                record, agreement, agreement_bytes, asyncio.run(continued.read(agreement.negotiation_id)),
                project_billing=projection,
            )
            tampered = json.loads(evidence.model_dump_json())
            stored_reply = json.loads(base64.b64decode(tampered["items"][0]["body"]))
            stored_reply["pricing_pin"]["multiplier"] = "9999"
            tampered["items"][0]["body"] = base64.b64encode(json.dumps(stored_reply).encode()).decode()
            altered = type(evidence).model_validate(tampered)
            refuses(lambda: verify_recovered_pricing(
                record, agreement, agreement_bytes, altered, project_billing=projection,
            ), "signature/context is invalid")
            refuses(lambda: verify_recovered_pricing(
                record, agreement, agreement_bytes, replace_empty(evidence), project_billing=projection,
            ), "requires retained signed acceptance evidence")
        print(f"publication -> live codec pin -> archived signed acceptance recovery ({period or 'total'}={amount}): PASS")
    print("changed rate identity, proof context, inputs, multiplier, money and archived signature refused: PASS")
    print("LIMIT: PT1M projection is injected; no hosted rate materialization, approval, deployment or E2E")


def replace_empty(evidence):
    return evidence.model_copy(update={"items": []})


if __name__ == "__main__":
    main()
