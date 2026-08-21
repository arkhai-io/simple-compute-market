from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests.e2e.roles.scenarios.vms.hosted import network
from tests.e2e.roles.scenarios.vms.hosted.network import (
    NetworkMarketplacePort,
    _capacity_site_id,
    _option,
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


def test_capacity_site_uses_storefront_config_vocabulary() -> None:
    assert (
        _capacity_site_id({"capacity": {"sites": {"default": "http://provisioning:8081"}}})
        == "default"
    )


def test_settlement_option_uses_registry_listing_field() -> None:
    option = {
        "mechanism": "fiat.stripe.v1",
        "params": {"funding_profile": "card.v1"},
        "option_id": "option-1",
    }

    assert _option(SimpleNamespace(settlement_options=[option], extra={}), "card.v1") == option


def test_publisher_resolver_binds_durable_buyer_profile(monkeypatch) -> None:
    captured: dict[str, object] = {}
    config = object()
    resolver = object()
    monkeypatch.setattr(
        network,
        "BuyConfig",
        lambda **kwargs: captured.update(kwargs) or config,
    )
    monkeypatch.setattr(
        network,
        "make_publisher_trust_resolver",
        lambda **kwargs: captured.update(resolver_kwargs=kwargs) or resolver,
    )
    marketplace = object.__new__(NetworkMarketplacePort)
    marketplace.registry = SimpleNamespace(
        get_listing=lambda _listing_id: SimpleNamespace(to_dict=lambda: {})
    )
    marketplace._listing_id = "listing-1"
    marketplace.registry_url = "http://registry:8080"
    marketplace._registry_authority = SimpleNamespace(authority="registry-a")
    marketplace._buyer_signer = SimpleNamespace(identity=object())
    profile_id = network.uuid.UUID("11111111-1111-4111-8111-111111111111")
    marketplace._buyer_profile = SimpleNamespace(profile_id=profile_id)

    assert marketplace._publisher_resolver() is resolver
    assert captured["buyer_profile_id"] == profile_id
    assert captured["resolver_kwargs"] == {
        "config": config,
        "listing": {
            "source_registry_url": "http://registry:8080",
            "source_registry_authority": "registry-a",
        },
    }


def test_protected_listing_declares_vm_offering_mode() -> None:
    captured: dict[str, object] = {}

    class Seller:
        def create_listing(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(listing_id="listing-1")

        def get_listing(self, _listing_id: str):
            return SimpleNamespace(
                extra={
                    "settlement_options": [
                        {
                            "mechanism": "fiat.stripe.v1",
                            "params": {"funding_profile": "card.v1"},
                            "option_id": "option-1",
                        }
                    ]
                }
            )

    marketplace = object.__new__(NetworkMarketplacePort)
    marketplace.seller = Seller()
    marketplace._resource_id = "resource-1"
    marketplace._site_id = "default"
    marketplace._funding_profile = network.FundingProfile.CARD
    marketplace._interaction = network.FundingMode.INTERACTIVE

    snapshot = marketplace.create_and_publish_listing()

    assert snapshot.listing_id == "listing-1"
    assert captured["offer"] == {
        **network._OFFER,
        "resource_id": "resource-1",
        "virtualization_type": "vm",
    }
    assert captured["capacity_source"] == {
        "site_id": "default",
        "resource_id": "resource-1",
        "gpu_count": 1,
    }


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


class _Setup:
    def __init__(self, readiness, action=None, setup_ref="setup-1"):
        self.readiness = readiness
        self.action = action
        self.setup_ref = setup_ref


class _Instruments:
    instruments: list = []


def _port(monkeypatch, setup):
    """A real NetworkMarketplacePort with only the payer facade stood in."""

    from hosted_settlement_client import FundingMode, FundingProfile
    from tests.e2e.roles.scenarios.vms.hosted import network

    port = network.NetworkMarketplacePort.__new__(network.NetworkMarketplacePort)
    port._funding_profile = FundingProfile.CARD
    port._interaction = FundingMode.SAVED_INSTRUMENT
    port._payer_context = object()
    port._buyer_signer = object()
    port._payer_binding = SimpleNamespace(binding_ref="payer-1")
    port._instrument_label = "label"
    port._setup_ref = None

    async def _call(_ctx, _signer, operation, **_kwargs):
        return _Instruments() if operation == "list_instruments" else setup

    monkeypatch.setattr(network, "_payer_facade_call", _call)
    return port


def test_immediately_completed_setup_is_ready(monkeypatch) -> None:
    """A directly handed card confirms off-session and needs no browser.

    Reporting it as not ready sends the lane down the browser-action branch and
    fails a setup that has already finished.
    """

    from hosted_settlement_client import InstrumentReadiness

    port = _port(monkeypatch, _Setup(InstrumentReadiness.READY))

    fixture = port.ensure_payer_profile_fixture("card.v1", "saved_instrument")

    assert fixture["saved_instrument_ready"] is True
    assert fixture["setup_action"] is None
    assert fixture["setup_verification_pending"] is False


def test_deposit_bound_setup_is_pending_not_ready(monkeypatch) -> None:
    from hosted_settlement_client import InstrumentReadiness

    port = _port(monkeypatch, _Setup(InstrumentReadiness.VERIFICATION_PENDING))

    fixture = port.ensure_payer_profile_fixture("card.v1", "saved_instrument")

    assert fixture["saved_instrument_ready"] is False
    assert fixture["setup_verification_pending"] is True
