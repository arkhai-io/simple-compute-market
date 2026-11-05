"""Try authenticated surrender and site evidence through an injected domain verifier."""

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from market_deal_lifecycle.adapters import PaymentSelector
from market_identity import (
    Ed25519Signer, RequestEnvelope, TrustedIdentitySet, canonical_body_hash,
    canonical_json, sign_request, verify_request, AuthenticatedRequest,
)

from market_deal_servicing import (
    Classification, DeliveryIngress, DeliveryRecord, EndService, EndSession, PhysicalResult,
    SellerDeal, SellerSession, VerifiedSiteEnd,
)
from market_deal_servicing.evidence import transaction


class DemoDelivery:
    def __init__(self):
        self.effects = set()

    async def apply_end(self, negotiation_id, *, terminate, at, operation_key):
        self.effects.add(operation_key)
        return PhysicalResult(progress="tearing_down", done=True)


async def main():
    # Public deterministic development identities; never use on a public network.
    buyer, seller, site = (Ed25519Signer(bytes([n]) * 32) for n in (1, 2, 3))
    now = [150]
    physical = DemoDelivery()
    with TemporaryDirectory(prefix="seller-ingress-") as root:
        path = Path(root) / "storefront.sqlite"
        end = EndService(path, physical, clock=lambda: now[0])
        with transaction(path) as conn:
            for negotiation in ("surrender", "site"):
                EndSession(conn).register(DeliveryRecord(
                    negotiation_id=negotiation, commitment_ref="fixture-commitment", seller=seller.identity,
                    start_at=200, term_end=1000, committed_at=100,
                ))
                SellerSession(conn).register(SellerDeal(
                    negotiation_id=negotiation, commitment_ref="fixture-commitment", domain="fixture",
                    buyer=buyer.identity, payment=PaymentSelector("fixture-no-payment-adapter"), once_only=True,
                ))

        # A domain verifies its own report codec and reservation/site bindings. This
        # demo uses market envelopes; production compute uses its signed report codec.
        def verify_site(negotiation, body, headers):
            value = json.loads(body)
            envelope = AuthenticatedRequest.model_validate_json(headers["demo-envelope"])
            result = verify_request(
                envelope, body=value, now=envelope.timestamp, max_skew=0,
                expected_role="service", expected_method="POST", expected_operation="lease_ended",
                expected_resource="fixture-reservation", expected_principals=TrustedIdentitySet(
                    identities=(site.identity,),
                ),
            )
            if not result.verified or negotiation != "site" or value["reservation"] != "fixture-reservation":
                raise ValueError("site signature or reservation binding failed")
            return VerifiedSiteEnd(
                event_id=value["event_id"], capacity_reservation_id=value["reservation"],
                ended_at=value["at"], actor=site.identity, cause=value["cause"],
            )

        def ingress():
            return DeliveryIngress(
                path, clock=lambda: now[0], verify_site=verify_site,
                classify_site=lambda report, _: Classification(
                    kind="provisioning_failure", evidence_refs=["site-event:" + report.event_id],
                ),
            )

        request = {"kind": "end_delivery", "negotiation_id": "surrender", "operation_key": "end-now"}
        body = canonical_json(request)
        envelope = sign_request(signer=buyer, envelope=RequestEnvelope(
            role="buyer", principal=buyer.identity, method="POST", operation="lifecycle_peer",
            resource="surrender", request_id="surrender-1", timestamp=now[0], body_hash=canonical_body_hash(request),
        ))
        first = ingress().end_delivery(envelope, body=body, headers={"demo-envelope": envelope.model_dump_json()})
        await end.drive_physical("surrender")
        now[0] = 160
        replay = ingress().end_delivery(envelope, body=body, headers={"demo-envelope": envelope.model_dump_json()})
        await end.drive_physical("surrender")

        site_body = canonical_json({
            "event_id": "failure", "reservation": "fixture-reservation", "at": 140, "cause": "start_failed",
        })
        site_envelope = sign_request(signer=site, envelope=RequestEnvelope(
            role="service", principal=site.identity, method="POST", operation="lease_ended",
            resource="fixture-reservation", request_id="site-failure", timestamp=now[0],
            body_hash=canonical_body_hash(json.loads(site_body)),
        ))
        headers = {"demo-envelope": site_envelope.model_dump_json()}
        ingress().site_report("site", body=site_body, headers=headers)
        await end.drive_physical("site")
        now[0] = 170
        ingress().site_report("site", body=site_body, headers=headers)
        await end.drive_physical("site")
        with transaction(path) as conn:
            session = EndSession(conn)
            filing = next(intent for intent in session.intents("site") if intent.kind == "filing")
            assert first.receipt_at == replay.receipt_at == 150
            assert not any(intent.kind == "filing" for intent in session.intents("surrender"))
            assert len(session.requests("site")) == 1
            assert session.view("site").site_reports[0].body == site_body
            assert filing.payload["payload"]["ended_at"] == filing.not_before == 200
            assert len(physical.effects) == 2
            print(json.dumps({
                "receipt_preserved": first.receipt_at == replay.receipt_at == 150,
                "surrender_progress": replay.delivery.progress,
                "surrender_has_no_filing": not any(intent.kind == "filing" for intent in session.intents("surrender")),
                "site_source_count": len(session.requests("site")),
                "kept_exact_site_body": session.view("site").site_reports[0].body == site_body,
                "deferred_claim_at": filing.payload["payload"]["ended_at"],
                "not_before": filing.not_before,
                "one_effect_per_deal": len(physical.effects),
            }))


if __name__ == "__main__":
    asyncio.run(main())
