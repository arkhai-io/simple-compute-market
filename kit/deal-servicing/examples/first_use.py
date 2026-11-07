"""Explore seller evidence with public development identities and an isolated database."""

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from market_arkhai_mediation.fixtures.authority import MediationContractFake
from market_deal_lifecycle.evidence import CommitmentAttempt
from market_deal_lifecycle.terms import LifecycleTerms
from market_identity import (
    Ed25519Signer, RequestEnvelope, TrustedIdentitySet, canonical_body_hash,
    sign_request, verify_request,
)

from market_deal_servicing.evidence import (
    EvidenceSession, RetentionObservation, SQLiteEvidenceStore, transaction,
)


async def main():
    # Public deterministic development identities; never use on a public network.
    buyer = Ed25519Signer(bytes([1]) * 32)
    seller = Ed25519Signer(bytes([2]) * 32)
    admin = Ed25519Signer(bytes([3]) * 32)
    peer = MediationContractFake()
    terms = LifecycleTerms.model_validate({
        "adjudication": {
            "version": 1, "dispute": peer.authority,
            "dispute_window_seconds": 60, "case_hold_max_seconds": None,
        },
    })
    with TemporaryDirectory(prefix="seller-evidence-") as root:
        path = Path(root) / "storefront.sqlite"
        store = SQLiteEvidenceStore(path)
        for route in ("opening", "counteroffer", "administrative"):
            body = b'{"offer": "exact bytes, including whitespace"}'
            request = sign_request(signer=buyer, envelope=RequestEnvelope(
                role="buyer", principal=buyer.identity, method="POST",
                operation="negotiate", resource=route, request_id=route,
                timestamp=100, body_hash=canonical_body_hash(json.loads(body)),
            ))
            result = verify_request(
                request, body=json.loads(body), now=100, max_skew=5, expected_role="buyer",
                expected_method="POST", expected_operation="negotiate",
                expected_resource=route,
                expected_principals=TrustedIdentitySet(identities=(buyer.identity,)),
            )
            if not result.verified:
                raise RuntimeError("development request did not verify")
            with transaction(path) as conn:
                session = EvidenceSession(conn)
                session.capture(
                    route, evidence_id=route, body=body, headers={"proof": request.proof.model_dump_json()},
                    context=request.model_dump(mode="json"), recorded_at=100,
                )
                session.accept(
                    route, message_id=route, expires_at=120,
                    accepted_by=admin.identity if route == "administrative" else seller.identity,
                    terms=None if route == "counteroffer" else terms,
                )
            kept = await store.read(route)
            assert kept.items[0].body == body
            print(json.dumps({
                "acceptance": route, "kept_exact_body": kept.items[0].body == body,
                "author": "administrator" if route == "administrative" else "seller",
            }))
        await store.record_commitment("opening", CommitmentAttempt(commitment_ref="transaction-fixture"))
        with transaction(path) as conn:
            session = EvidenceSession(conn)
            session.observe("opening", RetentionObservation(
                observed_at=200, delivery_ended_at=140, recovered_at=150,
                payouts={"once": None}, cases={}, open_extensions=[], complete=True,
            ))
            kept = not session.prune("opening", now=300, has_adapter=True)
            assert kept
            print(json.dumps({"held_funds_kept": kept}))
            session.observe("opening", RetentionObservation(
                observed_at=300, delivery_ended_at=140, recovered_at=150,
                payouts={"once": 250}, cases={"case": 260}, open_extensions=[], complete=True,
            ))
            pruned = session.prune("opening", now=320, has_adapter=True)
            assert pruned
            print(json.dumps({"closed_and_paid_pruned": pruned}))
            kept = not session.prune("counteroffer", now=9999, has_adapter=False)
            assert kept
            print(json.dumps({"no_lifecycle_kept": kept}))
        # A fresh object reads the same persisted envelopes after restart.
        remaining = await SQLiteEvidenceStore(path).negotiations()
        assert remaining == ("administrative", "counteroffer")
        print(json.dumps({"after_restart": remaining}))


if __name__ == "__main__":
    asyncio.run(main())
