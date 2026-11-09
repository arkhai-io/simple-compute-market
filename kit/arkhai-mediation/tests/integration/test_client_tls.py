"""The mediation client's trust: a configured CA bundle, or the default store.

The real client against a real TLS listener on a loopback port, serving a leaf a
private CA issues for this test, which no trust store holds: a real handshake,
not a mocked transport. Given the CA's bundle, the client verifies the listener
and reads its respondent page. Given another CA's bundle, or none, the handshake
fails before any request is sent, and the caller sees a transport error.
"""

from __future__ import annotations

import asyncio
import datetime
import ipaddress
import ssl
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from pydantic import SecretStr

from market_deal_lifecycle.terms import DisputeAuthority

from market_arkhai_mediation.client import (
    MediationClient, MediationCredential, MediationTransportError,
)
from market_arkhai_mediation.fixtures.authority import MediationContractFake
from market_arkhai_mediation.models import RespondentAfter

# A public test-only token that authenticates to nothing; never use it on a
# public network.
TOKEN = "mediation-client-tls-canary"


def _private_ca(directory: Path) -> tuple[Path, Path, Path]:
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
def _serving(certificate: Path, key: Path, requests: list[str]) -> Iterator[int]:
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


def _client(port: int, ca_bundle: str | None) -> MediationClient:
    authority = DisputeAuthority.model_validate(
        MediationContractFake().authority | {"origin": f"https://127.0.0.1:{port}"}
    )
    return MediationClient(
        authority, MediationCredential(authority.identity, token=SecretStr(TOKEN)),
        ca_bundle=ca_bundle,
    )


async def _read_respondent(client: MediationClient):
    async with client:
        return await client.respondent(RespondentAfter(after=""))


def test_the_configured_ca_bundle_verifies_the_authority(tmp_path):
    bundle, certificate, key = _private_ca(tmp_path)
    requests: list[str] = []
    with _serving(certificate, key, requests) as port:
        page = asyncio.run(_read_respondent(_client(port, str(bundle))))

    assert page.cases == []
    assert [path.split("?")[0] for path in requests] == ["/respondent"]


@pytest.mark.parametrize("trust", ["another-ca", "default-store"])
def test_a_certificate_the_client_does_not_trust_fails_before_any_request(tmp_path, trust):
    _bundle, certificate, key = _private_ca(tmp_path)
    ca_bundle = None
    if trust == "another-ca":
        other = tmp_path / "other"
        other.mkdir()
        ca_bundle = str(_private_ca(other)[0])
    requests: list[str] = []
    with _serving(certificate, key, requests) as port:
        with pytest.raises(MediationTransportError):
            asyncio.run(_read_respondent(_client(port, ca_bundle)))

    assert requests == []
