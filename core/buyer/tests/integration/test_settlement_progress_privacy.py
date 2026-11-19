"""Signed settlement polling separates public progress from private delivery,
and runs on the clock its caller gives it."""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread
import time
import uuid

import pytest
from market_identity import (
    Ed25519Signer, ResponseEnvelope, TrustedIdentitySet, canonical_body_hash,
    sign_response,
)

from core_buyer.orchestration import wait_for_settlement
from core_buyer.run_log import RunLog, read_run, runs_dir

# Public deterministic development identities; never use on a public network.
BUYER, SELLER = Ed25519Signer(b"\x11" * 32), Ed25519Signer(b"\x12" * 32)


@contextmanager
def signed_seller(answer):
    """A loopback seller signing ``answer(read_index)`` for each status read."""
    reads = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            payload = answer(len(reads))
            reads.append(self.path)
            signed = sign_response(signer=SELLER, envelope=ResponseEnvelope(
                role="seller", principal=SELLER.identity, method="GET",
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

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", reads
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    assert not worker.is_alive()


def _wait(url, **kwargs):
    return wait_for_settlement(
        seller_url=url, escrow_uid="fixture-settlement", principal=BUYER.identity,
        signer=BUYER,
        resolve_seller_principals=lambda: TrustedIdentitySet(identities=(SELLER.identity,)),
        **kwargs,
    )


class FakeClock:
    """A monotonic clock advanced only by the sleeps it is given."""

    def __init__(self):
        self.now = 1000.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def test_authenticated_private_delivery_never_reaches_public_progress(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    private = {
        "tenant_credentials": {"password": "PRIVATE-DELIVERY-CANARY"},
        "connection_details": "PRIVATE-CONNECTION-CANARY",
        "future_private_field": "FUTURE-DELIVERY-CANARY",
    }
    served = [{"status": "pending", **private}, {"status": "ready", **private}]

    log = RunLog.start(profile_id=uuid.uuid4(), principal=BUYER.identity)
    observed = []
    def observe(attempt, body):
        observed.append(body)
        log.event("settlement_poll", attempt=attempt, body=body)

    with signed_seller(lambda index: served[index]) as (url, reads):
        result = _wait(url, poll_interval=0, total_timeout=5, on_poll=observe)
    assert result == served[-1]
    assert observed == [{"status": "pending"}, {"status": "ready"}]
    assert len(reads) == 2
    events = read_run(log.run_id, signer=BUYER)
    assert [event["body"] for event in events if event.get("event") == "settlement_poll"] == observed
    persisted = next(runs_dir().glob("*.jsonl")).read_text()
    assert "CANARY" not in persisted


def test_the_wait_polls_on_its_callers_clock_until_terminal(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    clock = FakeClock()
    served = [{"status": "pending"}, {"status": "pending"}, {"status": "ready"}]

    with signed_seller(lambda index: served[index]) as (url, reads):
        result = _wait(
            url, poll_interval=30, total_timeout=600,
            sleep=clock.sleep, monotonic=clock.monotonic,
        )

    assert result == {"status": "ready"}
    assert len(reads) == 3
    # Both pauses went to the caller's sleep, none to the process's.
    assert clock.slept == [30, 30]


def test_the_wait_times_out_after_its_total_in_its_callers_time(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    clock = FakeClock()

    with signed_seller(lambda _index: {"status": "pending"}) as (url, reads):
        with pytest.raises(TimeoutError, match="within 90"):
            _wait(
                url, poll_interval=30, total_timeout=90,
                sleep=clock.sleep, monotonic=clock.monotonic,
            )

    # Polled at 0, 30, 60 and 90 seconds of fake time, then timed out.
    assert clock.slept == [30, 30, 30]
    assert len(reads) == 4
