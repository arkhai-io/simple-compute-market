"""Case export binds each commitment to its own exact accepted Agreement."""

import asyncio
import base64
import hashlib
import json

from market_core.schemas import Agreement
from market_deal_lifecycle_contracts.models import CasePayload, EvidenceItem
from market_deal_lifecycle_buyer import FileEvidenceStore, create_evidence_command_group, export_case
from market_identity import Ed25519Signer, ResponseEnvelope, TrustedIdentitySet, canonical_body_hash, sign_response, verify_response
from typer.testing import CliRunner


def test_export_preserves_original_bytes_and_superseded_commitments(tmp_path):
    # Deterministic development identities; never use these keys on a public network.
    buyer = Ed25519Signer(bytes([17]) * 32)
    seller = Ed25519Signer(bytes([34]) * 32)
    store = FileEvidenceStore(tmp_path)
    def accept(amount):
        agreement = Agreement(negotiation_id="neg-1", listing_id="listing-1", listing_hash="0" * 64,
                              buyer=buyer.identity.model_dump(mode="json"), seller=seller.identity.model_dump(mode="json"),
                              amount=amount, duration_seconds=3600, start_utc="2025-01-01T00:00:00Z", accepted_at="2025-01-01T00:00:00Z")
        exact_agreement = json.dumps(agreement.model_dump(mode="json"), indent=4).encode()
        payload = {"negotiation_id": "neg-1", "action": "accept", "agreement_bytes": base64.b64encode(exact_agreement).decode()}
        raw = json.dumps(payload, indent=2).encode()
        envelope = sign_response(signer=seller, envelope=ResponseEnvelope(
            role="seller", principal=seller.identity, method="POST", operation="negotiate_continue",
            resource="neg-1", request_id=f"request-{amount}", timestamp=2000, status=200,
            body_hash=canonical_body_hash(payload),
        ))
        result = verify_response(envelope, body=payload, now=2000, max_skew=0, expected_role="seller",
                                 expected_principals=TrustedIdentitySet(identities=(seller.identity,)),
                                 expected_method="POST", expected_operation="negotiate_continue", expected_resource="neg-1",
                                 expected_request_id=envelope.request_id, capture=store.capture, raw_body=raw,
                                 headers={"X-Market-Signature": envelope.proof.value})
        assert result.verified
        return exact_agreement, raw
    first, raw = accept(4200)
    store.remember_commitment("neg-1", "first")
    observation = EvidenceItem(evidence_id="observation", kind="connectivity", classification="buyer_observation",
                               recorded_at=2001, body=base64.b64encode(b"\x00\xff"),
                               context={"producer": buyer.identity.model_dump(mode="json")})
    asyncio.run(store.put("neg-1", observation))
    second, _ = accept(4300)
    store.remember_commitment("neg-1", "second")
    store.remember_commitment("neg-1", "first")
    def terms_from_agreement(raw):
        option = Agreement.model_validate_json(raw).settlement
        return option.lifecycle if option is not None else None
    requested = {"kind": "effects", "effects": []}
    case = asyncio.run(export_case(FileEvidenceStore(tmp_path), "neg-1", claim="No access", requested_outcome=requested, commitment_ref="first", terms_from_agreement=terms_from_agreement))
    assert case.agreement == first
    assert case.commitment_ref == "first"
    assert case.items[0].body == raw
    assert case.items[1].body == b"\x00\xff"
    assert case.items[1].context["digest"] == hashlib.sha256(b"\x00\xff").hexdigest()
    assert case.items[1].context["producer"] == buyer.identity.model_dump(mode="json")
    assert case.request == {"terms": None, "claim": "No access", "request": requested}
    assert CasePayload.model_validate_json(case.model_dump_json()) == case
    async def unavailable(_):
        raise ConnectionError("offline")
    app = create_evidence_command_group(lambda: store, unavailable, clock=lambda: 10000, terms_from_agreement=terms_from_agreement)
    result = CliRunner().invoke(app, ["export", "neg-1", "--claim", "No access", "--requested-outcome", json.dumps(requested)])
    assert result.exit_code == 0, result.output
    assert CasePayload.model_validate_json(result.output).agreement == second
    result = CliRunner().invoke(app, ["prune"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["kept"] == {"neg-1": "read_unavailable"}
