from __future__ import annotations

from types import SimpleNamespace

from tests.e2e.roles.scenarios.vms.hosted import network
from tests.e2e.roles.scenarios.vms.hosted.network import (
    NetworkMarketplacePort,
    _primary_registry_authority,
)


def test_primary_registry_authority_uses_advertised_url_not_runtime_endpoint() -> None:
    authority = _primary_registry_authority(
        {
            "registry": {
                "urls": ["http://registry:8080"],
                "authorities": {
                    "http://registry:8080": {
                        "authority": "registry-a",
                        "principals": [{"scheme": "ed25519", "identifier": "registry-principal"}],
                    }
                },
            }
        }
    )

    assert authority["authority"] == "registry-a"


def test_runtime_readiness_requires_only_destination_transfer_capability(
    monkeypatch,
) -> None:
    marketplace = object.__new__(NetworkMarketplacePort)
    marketplace.buyer_config = {}
    marketplace.storefront_url = "http://storefront"
    marketplace.authority_url = "http://authority"
    marketplace.account_ref = "seller-account"
    marketplace._seller_signer = object()
    monkeypatch.setattr(
        network.httpx,
        "get",
        lambda *_args, **_kwargs: SimpleNamespace(status_code=200),
    )
    monkeypatch.setattr(
        network,
        "released_authority_client",
        lambda **_kwargs: SimpleNamespace(
            account_readiness=lambda *_args, **_kwargs: SimpleNamespace(
                ready=True,
                capabilities=("transfers",),
            )
        ),
    )

    snapshot = marketplace.verify_runtime()

    assert snapshot.wallet_free is True
    assert snapshot.runtime_ready is True
    assert snapshot.account_ready is True
