"""The production negotiation transport stores acceptance before commitment."""

import asyncio
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread
import time
from types import SimpleNamespace

from core_buyer.negotiation_client import negotiate_with_seller
from market_core.schemas import Agreement
from market_identity import Ed25519Signer, ResponseEnvelope, TrustedIdentitySet, canonical_body_hash, sign_response
from market_deal_lifecycle_buyer import FileEvidenceStore


def test_acceptance_is_durable_before_payment(tmp_path, monkeypatch):
    # Deterministic development identities; never use these keys on a public network.
    buyer = Ed25519Signer(bytes([17]) * 32)
    seller = Ed25519Signer(bytes([34]) * 32)
    terms = {"kind": "example.v1", "version": 1, "payload": {}}
    agreement = Agreement(
        negotiation_id="neg-1", listing_id="listing-1", listing_hash="0" * 64,
        buyer=buyer.identity.model_dump(mode="json"), seller=seller.identity.model_dump(mode="json"),
        amount=4200, duration_seconds=3600, start_utc="2025-01-01T00:00:00Z", accepted_at="2025-01-01T00:00:00Z",
    )
    payload = {
        "negotiation_id": "neg-1", "action": "accept", "proposal": {"fields": {"amount": 4200}},
        "buyer_principal": agreement.buyer, "seller_principal": agreement.seller,
        "accepted_provision_terms": terms, "agreement": agreement.model_dump(mode="json", exclude_none=True),
        "agreement_bytes": base64.b64encode(agreement.model_dump_json(exclude_none=True).encode()).decode(),
    }
    raw = json.dumps(payload, indent=2).encode()
    class Seller(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            signed = sign_response(signer=seller, envelope=ResponseEnvelope(
                role="seller", principal=seller.identity, method="POST", operation="negotiate_new",
                resource="listing-1", request_id=self.headers["X-Market-Request-ID"],
                timestamp=int(time.time()), status=200, body_hash=canonical_body_hash(payload),
            ))
            self.send_response(200)
            for name, value in {
                "Signature-Version": signed.protocol, "Identity-Scheme": signed.principal.scheme.value,
                "Identity-Identifier": signed.principal.identifier, "Role": signed.role,
                "Request-ID": signed.request_id, "Timestamp": str(signed.timestamp), "Signature": signed.proof.value,
            }.items():
                self.send_header("X-Market-" + name, value)
            self.end_headers()
            self.wfile.write(raw)
        def log_message(self, *_):
            pass
    store = FileEvidenceStore(tmp_path / "evidence")
    monkeypatch.setattr("core_buyer.negotiation_client.run_negotiation_chain",
                        lambda *_a, **_kw: SimpleNamespace(action="counter", proposal={"fields": {"amount": 4200}}))
    server = ThreadingHTTPServer(("127.0.0.1", 0), Seller)
    # shutdown() returns only at serve_forever's next poll, and the library
    # has no way to wake it, so the poll is short rather than the default 0.5s.
    thread = Thread(target=lambda: server.serve_forever(poll_interval=0.01))
    thread.start()
    def before_payment(_outcome):
        record = asyncio.run(FileEvidenceStore(store.root).read("neg-1"))
        assert record.items[0].body == raw
        assert record.items[0].headers["X-Market-Signature"]
        assert record.items[1].kind == "signed_request"
    try:
        outcome = negotiate_with_seller(
            seller_url=f"http://127.0.0.1:{server.server_port}", principal=buyer.identity, signer=buyer,
            listing_id="listing-1", resolve_seller_principals=lambda: TrustedIdentitySet(identities=(seller.identity,)),
            initial_price=4200, max_price=4200, unit_count=1, provision_terms=terms, escrow_proposal={},
            encode_escrow_proposal=lambda _: {"fields": {"amount": 4200}}, chain=[],
            capture=store.capture, validate_acceptance=before_payment,
        )
        assert outcome.status == "agreed"
        store.remember_commitment("neg-1", "first")
        store.remember_commitment("neg-1", "second")
        store.remember_commitment("neg-1", "second")
        reopened = FileEvidenceStore(store.root)
        attempts = asyncio.run(reopened.read("neg-1")).commitments
        assert [(a.commitment_ref, a.superseded) for a in attempts] == [("first", True), ("second", False)]
        assert asyncio.run(reopened.read("neg-1")).items[0].body == raw
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
