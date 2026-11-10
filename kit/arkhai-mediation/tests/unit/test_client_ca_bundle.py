"""The mediation client loads its CA bundle when it is built, or refuses it."""

from __future__ import annotations

import ssl

import pytest
from pydantic import SecretStr

from market_deal_lifecycle.terms import DisputeAuthority

from market_arkhai_mediation.client import MediationClient, MediationCredential
from market_arkhai_mediation.fixtures.authority import MediationContractFake

# A public test-only token that authenticates to nothing; never use it on a
# public network.
TOKEN = "mediation-client-ca-canary"


def _build(ca_bundle: str) -> MediationClient:
    authority = DisputeAuthority.model_validate(MediationContractFake().authority)
    return MediationClient(
        authority, MediationCredential(authority.identity, token=SecretStr(TOKEN)),
        ca_bundle=ca_bundle,
    )


def test_a_ca_bundle_is_loaded_when_the_client_is_built(tmp_path):
    with pytest.raises(FileNotFoundError):
        _build(str(tmp_path / "none.pem"))
    malformed = tmp_path / "malformed.pem"
    malformed.write_text("-----BEGIN CERTIFICATE-----\nnot a certificate\n", "utf-8")
    with pytest.raises(ssl.SSLError):
        _build(str(malformed))


@pytest.mark.parametrize("bundle", ["", "  "], ids=["empty", "blank"])
def test_an_empty_ca_bundle_is_refused_rather_than_read_as_the_default_store(bundle):
    with pytest.raises(ValueError, match="ca_bundle must name a file"):
        _build(bundle)
