"""The access check's trust: a configured CA bundle, and trust it cannot establish.

The real check and mediation client against a real TLS listener on a loopback
port, serving a leaf a private CA issues for this test, which no trust store
holds: a real handshake, not a mocked transport. Given the CA's bundle as
``ca_bundle_path``, the client verifies the listener and the check is ``ok``.
Given another CA's bundle, or none, the handshake fails before any request is
sent and the outcome names the transport step (spec scenario "The storefront
does not trust the authority's certificate"), as it does for an origin whose
connection is refused. A process-level ``SSL_CERT_FILE``
the client cannot load fails the transport step before any connection.
"""

from __future__ import annotations

import socket

import pytest
from pydantic import SecretStr

from market_deal_lifecycle.configuration import DisputeCredential

from market_arkhai_mediation.access_check import check_mediation_access
from market_arkhai_mediation.fixtures.authority import MediationContractFake

from .tls_listener import private_ca, serving

# A public test-only token that authenticates to nothing; never use it on a
# public network.
TOKEN = "mediation-access-check-tls-canary"


def _credential(origin: str, ca_bundle_path: str | None = None) -> DisputeCredential:
    authority = MediationContractFake().authority
    return DisputeCredential(
        interface=authority["interface"], origin=origin, account=authority["account"],
        record_key=authority["record_key"], api_key=SecretStr(TOKEN),
        ca_bundle_path=ca_bundle_path,
    )


def test_the_configured_ca_bundle_verifies_the_authority(tmp_path):
    bundle, certificate, key = private_ca(tmp_path)
    requests: list[str] = []
    with serving(certificate, key, requests) as port:
        origin = f"https://127.0.0.1:{port}"
        outcome = check_mediation_access([_credential(origin, str(bundle))], origin)

    assert outcome.ok, outcome.json_line()
    assert [path.split("?")[0] for path in requests] == ["/respondent"]


@pytest.mark.parametrize("trust", ["another-ca", "default-store"])
def test_a_certificate_the_credentials_trust_does_not_cover_fails_the_transport_step(
    tmp_path, trust,
):
    _bundle, certificate, key = private_ca(tmp_path)
    ca_bundle_path = None
    if trust == "another-ca":
        other = tmp_path / "other"
        other.mkdir()
        ca_bundle_path = str(private_ca(other)[0])
    requests: list[str] = []
    with serving(certificate, key, requests) as port:
        origin = f"https://127.0.0.1:{port}"
        outcome = check_mediation_access([_credential(origin, ca_bundle_path)], origin)

    assert (outcome.outcome, outcome.step) == ("failed", "transport")
    assert requests == []
    assert TOKEN not in outcome.json_line()


def test_an_origin_nothing_answers_at_fails_the_transport_step(tmp_path):
    bundle, _certificate, _key = private_ca(tmp_path)
    # A port the kernel just handed out and that nothing now listens on, so the
    # connection is refused.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    origin = f"https://127.0.0.1:{port}"

    outcome = check_mediation_access([_credential(origin, str(bundle))], origin)

    assert (outcome.outcome, outcome.step) == ("failed", "transport")
    assert outcome.detail == "mediation authority could not be reached over a trusted connection"


@pytest.mark.parametrize("bundle", ["missing", "malformed"])
def test_a_process_trust_bundle_that_cannot_be_loaded_fails_the_transport_step(
    tmp_path, monkeypatch, bundle,
):
    # Without a ca_bundle_path the client verifies under the process's trust,
    # which it loads when built, so the origin is a reserved name nothing is ever
    # asked at.
    path = tmp_path / "process-ca.pem"
    if bundle == "malformed":
        path.write_text("-----BEGIN CERTIFICATE-----\nnot a certificate\n", "utf-8")
    monkeypatch.setenv("SSL_CERT_FILE", str(path))
    origin = "https://mediation.invalid"

    outcome = check_mediation_access([_credential(origin)], origin)

    assert (outcome.outcome, outcome.step) == ("failed", "transport")
    assert outcome.detail == "the trust bundle SSL_CERT_FILE names could not be loaded"
    assert TOKEN not in outcome.json_line()
    assert str(path) not in outcome.json_line()
