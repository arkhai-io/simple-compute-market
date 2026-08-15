from __future__ import annotations

from types import SimpleNamespace
import pytest

from tests.e2e.roles.scenarios.vms.hosted import network
from tests.e2e.roles.scenarios.vms.hosted.network import (
    NetworkMarketplacePort,
    _primary_registry_authority,
)


def test_interactive_payer_fixture_is_a_successful_lifecycle_response() -> None:
    marketplace = object.__new__(NetworkMarketplacePort)
    marketplace._funding_profile = network.FundingProfile.CARD
    marketplace._interaction = network.FundingMode.INTERACTIVE

    response = marketplace.ensure_payer_profile_fixture("card.v1", "interactive")

    assert response["ok"] is True
    assert response["available"] is True
    assert response["saved_instrument_ready"] is True


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


def test_public_status_wait_retries_authority_unavailability(monkeypatch) -> None:
    marketplace = object.__new__(NetworkMarketplacePort)
    responses = iter(
        (
            RuntimeError("GET http://storefront/settlement -> authenticated HTTP 503: unavailable"),
            {"status": "funded"},
        )
    )

    def buyer_status(_settlement_ref: str):
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(marketplace, "_buyer_status", buyer_status)
    monkeypatch.setattr(network.time, "sleep", lambda _seconds: None)
    monkeypatch.setenv("HOSTED_SETTLEMENT_E2E_LIFECYCLE_TIMEOUT", "1")

    assert marketplace._wait_public_status("settlement-1", {"funded"}) == {"status": "funded"}


def test_refund_funding_reconciles_materialization_without_fulfillment(
    monkeypatch,
) -> None:
    marketplace = object.__new__(NetworkMarketplacePort)
    marketplace._stripe_test_case = "refund"
    monkeypatch.setattr(
        marketplace,
        "_buyer_status",
        lambda _settlement_ref: {"status": "ready"},
    )
    monkeypatch.setattr(
        marketplace,
        "_buyer_call",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("GET http://storefront/settlement failed: timed out")
        ),
    )
    monkeypatch.setattr(
        marketplace,
        "_release_refund_fulfillment_failure",
        lambda: None,
    )
    monkeypatch.setenv("HOSTED_SETTLEMENT_E2E_LIFECYCLE_TIMEOUT", "1")

    assert marketplace.wait_funded("settlement-1") is True


def test_refund_request_retries_transient_settlement_conflict(monkeypatch) -> None:
    marketplace = object.__new__(NetworkMarketplacePort)
    terminal = SimpleNamespace(marketplace_status="reclaimed")
    responses = iter(
        (
            RuntimeError(
                "POST http://storefront/settlement/reclaim -> authenticated HTTP 409: busy"
            ),
            terminal,
        )
    )

    def reclaim(_settlement_ref: str):
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(marketplace, "reclaim", reclaim)
    monkeypatch.setattr(network.time, "sleep", lambda _seconds: None)
    monkeypatch.setenv("HOSTED_SETTLEMENT_E2E_LIFECYCLE_TIMEOUT", "1")

    assert marketplace.request_eligible_pretransfer_refund("settlement-1") is terminal


def test_public_status_wait_rejects_nontransient_authenticated_errors(
    monkeypatch,
) -> None:
    marketplace = object.__new__(NetworkMarketplacePort)
    monkeypatch.setattr(
        marketplace,
        "_buyer_status",
        lambda _settlement_ref: (_ for _ in ()).throw(
            RuntimeError("GET http://storefront/settlement -> authenticated HTTP 401: rejected")
        ),
    )
    monkeypatch.setenv("HOSTED_SETTLEMENT_E2E_LIFECYCLE_TIMEOUT", "1")

    with pytest.raises(RuntimeError, match="authenticated HTTP 401"):
        marketplace._wait_public_status("settlement-1", {"funded"})
