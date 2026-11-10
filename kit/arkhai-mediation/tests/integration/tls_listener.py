"""A real TLS listener on a loopback port, serving a leaf a throwaway CA issued.

No trust store holds the CA, so a client verifies the listener only when it is
given the CA's bundle. The listener answers every GET with an empty respondent
listing and records each request's path.
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
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def private_ca(directory: Path) -> tuple[Path, Path, Path]:
    """A throwaway CA's bundle, and a leaf for 127.0.0.1 it issued, with its key.

    Both carry the extensions strict X.509 verification, the default context's
    since Python 3.13, requires of a CA and a server leaf.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "mediation test CA")])
    ca_key_id = x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key())
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(_key_usage(key_cert_sign=True, crl_sign=True), critical=True)
        .add_extension(ca_key_id, critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    leaf_key = ec.generate_private_key(ec.SECP256R1())
    leaf = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")]))
        .issuer_name(ca_name).public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(hours=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(_key_usage(digital_signature=True), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_subject_key_identifier(ca_key_id),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    bundle = directory / "test-ca.pem"
    certificate = directory / "leaf.pem"
    key = directory / "leaf.key.pem"
    bundle.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    certificate.write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
    key.write_bytes(leaf_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    return bundle, certificate, key


def _key_usage(**granted: bool) -> x509.KeyUsage:
    usages = dict.fromkeys(
        ("digital_signature", "content_commitment", "key_encipherment", "data_encipherment",
         "key_agreement", "key_cert_sign", "crl_sign", "encipher_only", "decipher_only"),
        False,
    )
    return x509.KeyUsage(**{**usages, **granted})


@contextmanager
def serving(certificate: Path, key: Path, requests: list[str]) -> Iterator[int]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - the stdlib's handler name
            requests.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"cases": [], "next_after": "", "has_more": false}')

        def log_message(self, *_args: object) -> None:
            return None

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate, key)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    # shutdown() returns only at serve_forever's next poll, and the library
    # has no way to wake it, so the poll is short rather than the default 0.5s.
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
