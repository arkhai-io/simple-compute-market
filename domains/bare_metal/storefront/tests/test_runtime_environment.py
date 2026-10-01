"""Building the storefront runtime from its process environment.

The server builds its runtime only this way, so the app tests, which construct a
runtime directly, cannot see a defect in it. Every value below is a development
fixture and must never be used on a public network.
"""

from __future__ import annotations

import json

import pytest
from market_identity import Eip191Signer

from arkhai_bare_metal_storefront.runtime import build_runtime_from_environment

SELLER = Eip191Signer(bytes.fromhex("11" * 32))
ADMIN = Eip191Signer(bytes.fromhex("33" * 32))
SITE = Eip191Signer(bytes.fromhex("44" * 32))


@pytest.fixture
def environment(monkeypatch, tmp_path):
    values = {
        "BARE_METAL_STOREFRONT_IDENTITY_SCHEME": str(SELLER.identity.scheme.value),
        "BARE_METAL_STOREFRONT_IDENTITY_IDENTIFIER": SELLER.identity.identifier,
        "ARKHAI_IDENTITY_CREDENTIAL": "0x" + "11" * 32,
        "BARE_METAL_STOREFRONT_ADMIN_IDENTITIES": json.dumps(
            [ADMIN.identity.model_dump(mode="json")]
        ),
        "BARE_METAL_STOREFRONT_PUBLIC_URL": "http://seller:8000",
        "BARE_METAL_STOREFRONT_EVM_ADDRESS": "0x" + "33" * 20,
        "BARE_METAL_STOREFRONT_SITES": json.dumps(
            [
                {
                    "site_id": "site-a",
                    "authority_principal": SITE.identity.model_dump(mode="json"),
                    "authority_url": "http://site-a",
                }
            ]
        ),
        "BARE_METAL_STOREFRONT_DB_PATH": str(tmp_path / "storefront.db"),
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return values


def test_the_runtime_takes_its_principal_from_the_configured_identity(environment):
    runtime = build_runtime_from_environment()

    assert runtime.seller_principal == SELLER.identity
    assert runtime.marketplace_signer.identity == SELLER.identity
    assert runtime.pool_override_service() is not None


def test_a_credential_that_does_not_own_the_identity_is_refused(environment, monkeypatch):
    monkeypatch.setenv("ARKHAI_IDENTITY_CREDENTIAL", "0x" + "22" * 32)

    with pytest.raises(RuntimeError, match="identity"):
        build_runtime_from_environment()
