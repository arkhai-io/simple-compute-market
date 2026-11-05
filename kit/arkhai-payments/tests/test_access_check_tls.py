"""An untrusted payments certificate fails the access check at its transport step.

The real check and payments client against a real TLS listener on a loopback
port, serving a certificate this test issues and no trust store holds: a real
handshake, not a mocked transport. The handshake fails before any request is sent, and the
outcome names the transport step. Spec scenario "The storefront does not trust
the payments origin".
"""

from __future__ import annotations

import datetime
import ipaddress
import ssl
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from market_arkhai_payments import check_payments_access

from payment_terms import PAYEE, SERVICE

# A public test-only key value that authenticates to nothing; never use it on a
# public network.
KEY = "sk_test_access_check_tls_canary"
KEY_ENV = "SELLER_PAYMENTS_KEY"


def _self_signed(directory: Path) -> tuple[Path, Path]:
    """A certificate for 127.0.0.1 signed by its own throwaway key."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "untrusted payments test")])
    now = datetime.datetime.now(datetime.timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(hours=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    certificate_path = directory / "untrusted.pem"
    key_path = directory / "untrusted.key.pem"
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    return certificate_path, key_path


@contextmanager
def _serving(certificate: Path, key: Path, requests: list[str]) -> Iterator[int]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - the stdlib's handler name
            requests.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"available": {}, "held": []}')

        def log_message(self, *_args: object) -> None:
            return None

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate, key)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_a_certificate_no_trust_store_holds_fails_the_transport_step(tmp_path):
    certificate, key = _self_signed(tmp_path)
    requests: list[str] = []
    with _serving(certificate, key, requests) as port:
        outcome = check_payments_access(
            {
                "enabled": True, "service_url": f"https://127.0.0.1:{port}",
                "service_identity": SERVICE.identity, "fee_bps": 250,
                "api_key_env": KEY_ENV,
            },
            PAYEE,
            environment={KEY_ENV: KEY},
        )

    assert not outcome.ok
    assert outcome.step == "transport"
    assert requests == []
    assert KEY not in outcome.json_line()
