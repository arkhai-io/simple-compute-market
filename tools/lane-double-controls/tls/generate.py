"""Write the lane CA certificate and each lane double's leaf certificate and key.

    python tls/generate.py [OUTPUT_DIRECTORY]

writes ``lane-ca.pem``, and ``<service>.pem`` and ``<service>.key.pem`` for each
double's service name, ``payments-double`` and ``mediation-double``, into the
directory, by default the one this file is in. One CA issues both leaves, so a
caller trusts both doubles through one CA bundle. Every input is fixed — each key
comes from a seed below, the serials and validity are constants, and an Ed25519
signature is deterministic — so the output is the same bytes on every run. The
certificates are committed, and ``make check-tls`` holds them to this output. The
leaf keys are not: the repository's secret gate refuses a private key block, so
each double's image build runs this script and takes its own key from it. The
CA's private key is never written to a file, but its seed is below, in a public
repository: anyone can issue a certificate under the lane CA.

So the seeds, and the CA, the leaves and their keys, are public development
values, for lanes and local releases. Never trust the lane CA, or serve with these
keys, on a public network.
"""

from __future__ import annotations

import ipaddress
import sys
from datetime import datetime, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

# Public development seeds; never use them on a public network.
CA_SEED = bytes([0xCA]) * 32
CA_SERIAL = 1
CA_NAME = "lane doubles CA (public development value)"
NOT_BEFORE = datetime(2026, 1, 1, tzinfo=timezone.utc)
NOT_AFTER = datetime(9999, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
# Each leaf is for its double's lane service name, and for loopback, where a
# double runs outside its lane.
LOOPBACK_NAMES = ("localhost",)
LOOPBACK_ADDRESSES = ("127.0.0.1",)
#: Each double's service name, with its leaf's seed and serial.
LEAVES = {
    "payments-double": (bytes([0xD0]) * 32, 2),
    "mediation-double": (bytes([0xD1]) * 32, 3),
}


def generate() -> dict[str, bytes]:
    """Every file's name and exact contents."""

    ca_key = Ed25519PrivateKey.from_private_bytes(CA_SEED)
    ca_subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, CA_NAME)])
    ca_identifier = x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key())
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_subject)
        .issuer_name(ca_subject)
        .public_key(ca_key.public_key())
        .serial_number(CA_SERIAL)
        .not_valid_before(NOT_BEFORE)
        .not_valid_after(NOT_AFTER)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(_key_usage(certificates=True), critical=True)
        .add_extension(ca_identifier, critical=False)
        .sign(ca_key, None)
    )
    files = {"lane-ca.pem": ca.public_bytes(serialization.Encoding.PEM)}
    for service, (seed, serial) in LEAVES.items():
        leaf_key = Ed25519PrivateKey.from_private_bytes(seed)
        names = (service, *LOOPBACK_NAMES)
        leaf = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, service)]))
            .issuer_name(ca_subject)
            .public_key(leaf_key.public_key())
            .serial_number(serial)
            .not_valid_before(NOT_BEFORE)
            .not_valid_after(NOT_AFTER)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(_key_usage(certificates=False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
                           critical=False)
            .add_extension(x509.SubjectAlternativeName(
                [x509.DNSName(name) for name in names]
                + [x509.IPAddress(ipaddress.ip_address(address))
                   for address in LOOPBACK_ADDRESSES]),
                critical=False)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(leaf_key.public_key()),
                           critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_subject_key_identifier(
                ca_identifier), critical=False)
            .sign(ca_key, None)
        )
        files[f"{service}.pem"] = leaf.public_bytes(serialization.Encoding.PEM)
        files[f"{service}.key.pem"] = leaf_key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption())
    return files


def _key_usage(*, certificates: bool) -> x509.KeyUsage:
    return x509.KeyUsage(
        digital_signature=not certificates, content_commitment=False, key_encipherment=False,
        data_encipherment=False, key_agreement=False, key_cert_sign=certificates,
        crl_sign=certificates, encipher_only=False, decipher_only=False)


def main(argv: list[str]) -> int:
    output = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parent
    for name, content in generate().items():
        (output / name).write_bytes(content)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
