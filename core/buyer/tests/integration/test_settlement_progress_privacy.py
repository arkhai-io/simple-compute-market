"""Signed settlement polling separates public progress from private delivery."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread
import time
import uuid

from market_identity import (
    Ed25519Signer, ResponseEnvelope, TrustedIdentitySet, canonical_body_hash,
    sign_response,
)

from core_buyer.orchestration import wait_for_settlement
from core_buyer.run_log import RunLog, read_run, runs_dir


def test_authenticated_private_delivery_never_reaches_public_progress(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    # Public deterministic development identities; never use on a public network.
    buyer, seller = Ed25519Signer(b"\x11" * 32), Ed25519Signer(b"\x12" * 32)
    private = {
        "tenant_credentials": {"password": "PRIVATE-DELIVERY-CANARY"},
        "connection_details": "PRIVATE-CONNECTION-CANARY",
        "future_private_field": "FUTURE-DELIVERY-CANARY",
    }
    served = [{"status": "pending", **private}, {"status": "ready", **private}]
    reads = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            payload = served[len(reads)]
            reads.append(self.path)
            signed = sign_response(signer=seller, envelope=ResponseEnvelope(
                role="seller", principal=seller.identity, method="GET",
                operation="settle_status", resource="fixture-settlement",
                request_id=self.headers["X-Market-Request-ID"], timestamp=int(time.time()),
                status=200, body_hash=canonical_body_hash(payload),
            ))
            self.send_response(200)
            for name, value in {
                "X-Market-Signature-Version": signed.protocol,
                "X-Market-Identity-Scheme": signed.principal.scheme.value,
                "X-Market-Identity-Identifier": signed.principal.identifier,
                "X-Market-Role": signed.role,
                "X-Market-Request-ID": signed.request_id,
                "X-Market-Timestamp": str(signed.timestamp),
                "X-Market-Signature": signed.proof.value,
                "Content-Type": "application/json",
            }.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())

        def log_message(self, *_):
            pass

    log = RunLog.start(profile_id=uuid.uuid4(), principal=buyer.identity)
    observed = []
    def observe(attempt, body):
        observed.append(body)
        log.event("settlement_poll", attempt=attempt, body=body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    worker.start()
    try:
        result = wait_for_settlement(
            seller_url=f"http://127.0.0.1:{server.server_port}",
            escrow_uid="fixture-settlement", principal=buyer.identity, signer=buyer,
            resolve_seller_principals=lambda: TrustedIdentitySet(identities=(seller.identity,)),
            poll_interval=0, total_timeout=5, on_poll=observe,
        )
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    assert not worker.is_alive()
    assert result == served[-1]
    assert observed == [{"status": "pending"}, {"status": "ready"}]
    assert len(reads) == 2
    events = read_run(log.run_id, signer=buyer)
    assert [event["body"] for event in events if event.get("event") == "settlement_poll"] == observed
    persisted = next(runs_dir().glob("*.jsonl")).read_text()
    assert "CANARY" not in persisted
