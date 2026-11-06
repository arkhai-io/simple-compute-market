"""The generated lane CA and leaf: who the leaf is for, and that the CA is enough to trust it."""

from __future__ import annotations

import ipaddress
import ssl
from pathlib import Path
from types import ModuleType

import pytest
from conftest import TLS
from cryptography import x509
from cryptography.hazmat.primitives import serialization


@pytest.fixture
def generated(tls_generator: ModuleType) -> dict[str, bytes]:
    return tls_generator.generate()


def test_the_generator_is_deterministic(tls_generator: ModuleType) -> None:
    assert tls_generator.generate() == tls_generator.generate()


def test_the_generated_key_is_the_committed_leaf_certificates(
        generated: dict[str, bytes]) -> None:
    # The image pairs the committed certificate with the key its build generates.
    committed = x509.load_pem_x509_certificate((TLS / "double.pem").read_bytes())
    key = serialization.load_pem_private_key(generated["double.key.pem"], password=None)

    raw = (serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    assert key.public_key().public_bytes(*raw) == committed.public_key().public_bytes(*raw)


def test_the_leaf_is_issued_by_the_ca_for_exactly_the_service_names(
        generated: dict[str, bytes]) -> None:
    ca = x509.load_pem_x509_certificate(generated["lane-ca.pem"])
    leaf = x509.load_pem_x509_certificate(generated["double.pem"])

    leaf.verify_directly_issued_by(ca)
    names = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert sorted(names.get_values_for_type(x509.DNSName)) == ["localhost", "payments-double"]
    assert names.get_values_for_type(x509.IPAddress) == [ipaddress.ip_address("127.0.0.1")]
    assert len(list(names)) == 3


@pytest.mark.parametrize("server_name", ["payments-double", "localhost", "127.0.0.1"])
def test_a_context_trusting_only_the_lane_ca_completes_a_handshake_with_the_leaf(
        generated: dict[str, bytes], tmp_path: Path, server_name: str) -> None:
    for name, content in generated.items():
        (tmp_path / name).write_bytes(content)
    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.load_cert_chain(tmp_path / "double.pem", tmp_path / "double.key.pem")
    # The default client context, as a lane caller builds it from SSL_CERT_FILE,
    # with the lane CA as its only trust anchor.
    client = ssl.create_default_context(cafile=tmp_path / "lane-ca.pem")

    _handshake(client, server, server_name)


def test_a_context_without_the_lane_ca_refuses_the_leaf(
        generated: dict[str, bytes], tmp_path: Path) -> None:
    for name, content in generated.items():
        (tmp_path / name).write_bytes(content)
    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.load_cert_chain(tmp_path / "double.pem", tmp_path / "double.key.pem")
    client = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

    with pytest.raises(ssl.SSLCertVerificationError):
        _handshake(client, server, "payments-double")


def _handshake(client_context: ssl.SSLContext, server_context: ssl.SSLContext,
               server_name: str) -> None:
    """Run a TLS handshake in memory, so the proof needs no socket."""

    client_in, client_out = ssl.MemoryBIO(), ssl.MemoryBIO()
    server_in, server_out = ssl.MemoryBIO(), ssl.MemoryBIO()
    client = client_context.wrap_bio(client_in, client_out, server_hostname=server_name)
    server = server_context.wrap_bio(server_in, server_out, server_side=True)
    done = {"client": False, "server": False}
    for _ in range(10):
        for name, side in (("client", client), ("server", server)):
            if not done[name]:
                try:
                    side.do_handshake()
                    done[name] = True
                except ssl.SSLWantReadError:
                    pass
        server_in.write(client_out.read())
        client_in.write(server_out.read())
        if all(done.values()):
            return
    raise AssertionError("the handshake did not complete")
