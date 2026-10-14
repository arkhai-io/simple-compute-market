"""Full API-credit deal settled through Arkhai payments, then refunded by the seller.

    discover → negotiate (arkhai.payments.v1) → approve → receipt-gated issuance
             → consume → re-drive settlement from the run log → seller refund

The buyer is a wallet-free Ed25519 identity with only Arkhai payments enabled,
so selection cannot fall back to Alkahest. The scenario needs a reachable
payments service and the credits storefront configured for the same service;
An absent payments target reports blocked; invalid lane settings fail.
The refund stage uses the seller's typed client and reads the transaction back
from the payments service as the payer.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
import pytest
from market_arkhai_payments import ArkhaiPaymentsConfig, payments_client_for_owner
from market_identity import Ed25519Signer, IdentityScheme, TrustedIdentitySet
from storefront_client import SyncStorefrontClient

from tests.e2e.roles.buyer_cli import BuyerCli, _toml_quote, create_profiled_buyer_cli
from tests.e2e.roles.helpers.domain_deal import (
    DealStage,
    DomainDealState,
    assert_market_run_succeeded,
    ordered_events,
    require_state,
)
from tests.e2e.roles.helpers.payments import (
    configured_payments,
    payment_config_toml,
    payment_setting,
)
from tests.e2e.roles.scenarios.apicredits.conftest import lane_setting

log = logging.getLogger(__name__)

pytestmark = pytest.mark.e2e_credits_payment_deal


def _registry_pin(prefix: str) -> tuple[str, dict[str, Any]]:
    url = lane_setting(f"API_CREDITS.{prefix}_URL").rstrip("/")
    return url, {
        "authority": lane_setting(f"API_CREDITS.{prefix}_AUTHORITY_ID"),
        "identities": [
            {
                "scheme": lane_setting(f"API_CREDITS.{prefix}_SCHEME"),
                "identifier": lane_setting(f"API_CREDITS.{prefix}_IDENTIFIER"),
            }
        ],
    }


@pytest.fixture(scope="module")
def payments_config() -> ArkhaiPaymentsConfig:
    """The trusted payments target, or a blocked scenario when it is not ready.

    The lane's own settings are checked first and fail when absent; only the
    payments target, an authority the lane does not supply, blocks the scenario.
    """

    lane_setting("API_CREDITS.REGISTRY_URL")
    lane_setting("API_CREDITS.STOREFRONT_URL")
    return configured_payments()


@pytest.fixture(scope="module")
def payment_buyer_cli(payments_config, buyer_cli_binary, tmp_path_factory) -> BuyerCli:
    compute_registry, compute_pin = _registry_pin("COMPUTE_REGISTRY")
    credits_registry, credits_pin = _registry_pin("REGISTRY")
    section = (
        "[Settlement]",
        "schema_version = 1",
        'priority = ["arkhai.payments.v1"]',
        "",
        *payment_config_toml(payments_config),
        "",
        "[apicredits]",
        f"payer_account = {_toml_quote(str(payment_setting('BUYER_ACCOUNT')))}",
        "",
    )
    return create_profiled_buyer_cli(
        binary=buyer_cli_binary,
        base=tmp_path_factory.mktemp("credits_payment_buyer_cli"),
        domain_identity="api_credits.v1",
        marketplace_scheme=IdentityScheme.ED25519,
        marketplace_credential=str(payment_setting("BUYER_MARKETPLACE_CREDENTIAL")),
        registries=(compute_registry, credits_registry),
        registry_authorities={compute_registry: compute_pin, credits_registry: credits_pin},
        credential_variable="ARKHAI_E2E_PAYMENT_BUYER_MARKETPLACE_CREDENTIAL",
        toml_sections=tuple(section),
    )


@pytest.fixture(scope="module")
def payment_deal_state() -> DomainDealState:
    return DomainDealState(domain_identity="api_credits.v1")


@pytest.fixture(scope="module")
def payment_run() -> dict:
    return {}


def test_payment_deal_issues_credits_after_a_verified_receipt(
    payment_buyer_cli: BuyerCli,
    payment_deal_state: DomainDealState,
    payment_run: dict,
) -> None:
    buy = payment_buyer_cli.run([
        "credits", "buy",
        "--quantity", "3",
        "--new-key",
        "--resource", "service_name=weather-api",
        "--max-matches", "5",
        "--max-rounds", "10",
        "--poll-interval", "1.0",
        "--settlement-timeout", "300",
        "--yes",
    ], timeout=320.0)
    assert_market_run_succeeded(buy, command="market credits buy (arkhai.payments.v1)")
    events = buy.read_events()
    lifecycle = ordered_events(
        events,
        "discover",
        "negotiation_started",
        "negotiation_completed",
        "payment_approved",
        "settlement_submitted",
        "credentials_delivered",
        "run_ended",
    )
    payment_deal_state.complete(DealStage.DISCOVERY, listing_id=str(lifecycle[1]["listing_id"]))
    payment_deal_state.complete(
        DealStage.NEGOTIATION, negotiation_id=str(lifecycle[-1]["negotiation_id"])
    )
    payment_deal_state.complete(
        DealStage.SETTLEMENT, settlement_id=str(lifecycle[3]["transaction_id"])
    )
    credentials = buy.wait_for_event("credentials_delivered", timeout=10.0)["credentials"]
    with httpx.Client(timeout=15) as client:
        consumed = client.get(
            f"{credentials['base_url'].rstrip('/')}/api/forecast",
            headers={"Authorization": f"Bearer {credentials['secret']}"},
        )
    assert consumed.status_code == 200, consumed.text
    payment_deal_state.complete(
        DealStage.DELIVERY,
        fulfillment_ref=str(lifecycle[-1].get("fulfillment_uid") or credentials["key_id"]),
        delivery={"key_id": credentials["key_id"], "service": "weather-api"},
    )
    payment_run["run_id"] = buy.run_id


def test_settlement_re_driven_from_the_run_log_is_idempotent(
    payment_buyer_cli: BuyerCli,
    payment_deal_state: DomainDealState,
    payment_run: dict,
) -> None:
    """A second buyer settlement from the run log returns the same delivery.

    This proves idempotent re-drive from the buyer's run log; it does not
    restart the storefront or the payments service.
    """
    require_state(payment_deal_state, "settlement_id", "fulfillment_ref")
    again = payment_buyer_cli.run(
        ["credits", "settle", "--from", payment_run["run_id"], "--settlement-timeout", "60"],
        timeout=90.0,
    )
    assert_market_run_succeeded(again, command="market credits settle --from <run>")
    delivered = again.wait_for_event("credentials_delivered", timeout=10.0)["credentials"]
    assert delivered["key_id"] == payment_deal_state.delivery["key_id"]


def test_the_seller_refund_reverses_the_held_payment(
    payment_deal_state: DomainDealState,
    payments_config: ArkhaiPaymentsConfig,
) -> None:
    require_state(payment_deal_state, "negotiation_id", "settlement_id")
    seller = Ed25519Signer(bytes.fromhex(str(payment_setting("SELLER_MARKETPLACE_CREDENTIAL"))))
    with SyncStorefrontClient(
        lane_setting("API_CREDITS.STOREFRONT_URL"),
        signer=seller,
        caller_role="seller",
        expected_publishers=TrustedIdentitySet(identities=(seller.identity,)),
    ) as storefront:
        refunded = storefront.refund_settlement(payment_deal_state.negotiation_id)
    assert refunded.status == "refunded"
    assert refunded.settlement_ref == payment_deal_state.settlement_id

    with payments_client_for_owner(payments_config, str(payment_setting("BUYER_ACCOUNT"))) as client:
        snapshot = client.get_transaction(payment_deal_state.settlement_id).snapshot
    assert {part.status.value for part in snapshot.parts} == {"reversed"}
    payment_deal_state.complete(
        DealStage.TEARDOWN,
        teardown={"kind": "payment_reversed", "transaction": payment_deal_state.settlement_id},
    )
    payment_deal_state.assert_complete()
