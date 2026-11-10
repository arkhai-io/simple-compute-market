"""The mediation client's trust: a configured CA bundle, or the default store.

The real client against a real TLS listener on a loopback port, serving a leaf a
private CA issues for this test, which no trust store holds: a real handshake,
not a mocked transport. Given the CA's bundle, the client verifies the listener
and reads its respondent page. Given another CA's bundle, or none, the handshake
fails before any request is sent, and the caller sees a transport error.
"""

from __future__ import annotations

import asyncio

import pytest
from pydantic import SecretStr

from market_deal_lifecycle.terms import DisputeAuthority

from market_arkhai_mediation.client import (
    MediationClient, MediationCredential, MediationTransportError,
)
from market_arkhai_mediation.fixtures.authority import MediationContractFake
from market_arkhai_mediation.models import RespondentAfter

from .tls_listener import private_ca, serving

# A public test-only token that authenticates to nothing; never use it on a
# public network.
TOKEN = "mediation-client-tls-canary"


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
    bundle, certificate, key = private_ca(tmp_path)
    requests: list[str] = []
    with serving(certificate, key, requests) as port:
        page = asyncio.run(_read_respondent(_client(port, str(bundle))))

    assert page.cases == []
    assert [path.split("?")[0] for path in requests] == ["/respondent"]


@pytest.mark.parametrize("trust", ["another-ca", "default-store"])
def test_a_certificate_the_client_does_not_trust_fails_before_any_request(tmp_path, trust):
    _bundle, certificate, key = private_ca(tmp_path)
    ca_bundle = None
    if trust == "another-ca":
        other = tmp_path / "other"
        other.mkdir()
        ca_bundle = str(private_ca(other)[0])
    requests: list[str] = []
    with serving(certificate, key, requests) as port:
        with pytest.raises(MediationTransportError):
            asyncio.run(_read_respondent(_client(port, ca_bundle)))

    assert requests == []
