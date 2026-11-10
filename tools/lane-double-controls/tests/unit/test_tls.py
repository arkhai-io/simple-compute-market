"""The generated lane CA and leaves: who each leaf is for, and that the CA is enough to trust it."""

from __future__ import annotations

import ipaddress
import ssl
from pathlib import Path
from types import ModuleType

import pytest
from conftest import TLS
from cryptography import x509
from cryptography.hazmat.primitives import serialization

SERVICES = ("payments-double", "mediation-double")


@pytest.fixture
def generated(tls_generator: ModuleType) -> dict[str, bytes]:
    files: dict[str, bytes] = tls_generator.generate()
    return files


def test_the_generator_is_deterministic(tls_generator: ModuleType) -> None:
    assert tls_generator.generate() == tls_generator.generate()


def test_the_generator_reproduces_every_committed_certificate(
        generated: dict[str, bytes]) -> None:
    for name in ("lane-ca.pem", *(f"{service}.pem" for service in SERVICES)):
        assert generated[name] == (TLS / name).read_bytes(), name


@pytest.mark.parametrize("service", SERVICES)
def test_each_generated_key_is_its_committed_leaf_certificates(
        generated: dict[str, bytes], service: str) -> None:
    # Each image pairs the committed certificate with the key its build generates.
    committed = x509.load_pem_x509_certificate((TLS / f"{service}.pem").read_bytes())
    key = serialization.load_pem_private_key(generated[f"{service}.key.pem"], password=None)

    raw = (serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    assert key.public_key().public_bytes(*raw) == committed.public_key().public_bytes(*raw)


@pytest.mark.parametrize("service", SERVICES)
def test_each_leaf_is_issued_by_the_ca_for_exactly_its_service_names(
        generated: dict[str, bytes], service: str) -> None:
    ca = x509.load_pem_x509_certificate(generated["lane-ca.pem"])
    leaf = x509.load_pem_x509_certificate(generated[f"{service}.pem"])

    leaf.verify_directly_issued_by(ca)
    names = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert sorted(names.get_values_for_type(x509.DNSName)) == sorted(["localhost", service])
    assert names.get_values_for_type(x509.IPAddress) == [ipaddress.ip_address("127.0.0.1")]
    assert len(list(names)) == 3


def test_the_leaves_have_distinct_keys(generated: dict[str, bytes]) -> None:
    keys = {generated[f"{service}.key.pem"] for service in SERVICES}

    assert len(keys) == len(SERVICES)


@pytest.mark.parametrize(("service", "server_name"), [
    (service, name) for service in SERVICES for name in (service, "localhost", "127.0.0.1")])
def test_a_context_trusting_only_the_lane_ca_completes_a_handshake_with_each_leaf(
        generated: dict[str, bytes], tmp_path: Path, service: str, server_name: str) -> None:
    for name, content in generated.items():
        (tmp_path / name).write_bytes(content)
    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.load_cert_chain(tmp_path / f"{service}.pem", tmp_path / f"{service}.key.pem")
    # The context a caller builds from its configured CA bundle, with the lane CA
    # as its only trust anchor.
    client = ssl.create_default_context(cafile=tmp_path / "lane-ca.pem")

    _handshake(client, server, server_name)


def test_a_leaf_does_not_answer_for_the_other_double(
        generated: dict[str, bytes], tmp_path: Path) -> None:
    for name, content in generated.items():
        (tmp_path / name).write_bytes(content)
    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.load_cert_chain(tmp_path / "payments-double.pem",
                           tmp_path / "payments-double.key.pem")
    client = ssl.create_default_context(cafile=tmp_path / "lane-ca.pem")

    with pytest.raises(ssl.SSLCertVerificationError):
        _handshake(client, server, "mediation-double")


def test_a_context_without_the_lane_ca_refuses_a_leaf(
        generated: dict[str, bytes], tmp_path: Path) -> None:
    for name, content in generated.items():
        (tmp_path / name).write_bytes(content)
    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.load_cert_chain(tmp_path / "mediation-double.pem",
                           tmp_path / "mediation-double.key.pem")
    client = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

    with pytest.raises(ssl.SSLCertVerificationError):
        _handshake(client, server, "mediation-double")


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
