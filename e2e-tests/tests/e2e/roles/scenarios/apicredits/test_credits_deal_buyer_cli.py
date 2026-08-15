"""Full API-credits deal, driven by `market credits buy`.

The domain's end-to-end (ARCHITECTURE.md, "API-credits market domain"):

    discover → negotiate (new key) → settle → consume to 402
             → buy again into the existing key → consume succeeds

The topology (docker-compose.yml): a second registry speaking the
``api_credits`` schema, the credits service, the credits storefront
(self-seeds one quota-backed listing pointing at the sample app), and
the sample app gated by the Python middleware. The buyer runs the same
`market` binary as the VM tests — its schema filter routes discovery to
the api-credits registry while leaving the vms.compute registry alone.

Consuming runs against the gated sample app directly with the issued
bearer secret, exactly as a real client of that API would.
"""

from __future__ import annotations

import logging
import time

import httpx
from market_identity import IdentityScheme
import pytest

from src.settings import settings
from tests.e2e.roles.buyer_cli import (
    BuyerCli,
    _alkahest_addresses_path,
    _toml_quote,
    create_profiled_buyer_cli,
)
from tests.e2e.roles.helpers.domain_deal import (
    DealStage,
    DomainDealState,
    assert_market_run_succeeded,
    ordered_events,
)

log = logging.getLogger(__name__)

pytestmark = pytest.mark.e2e_credits_deal


@pytest.fixture(scope="module")
def credits_buyer_cli(buyer_cli_binary, tmp_path_factory) -> BuyerCli:
    """Compose API credits over the shared profile/config fixture."""
    private_key = str(settings.BUYER.PRIVATE_KEY or "")
    wallet_address = str(settings.BUYER.WALLET_ADDRESS or "")
    if not private_key or not wallet_address:
        pytest.skip("BUYER.PRIVATE_KEY / BUYER.WALLET_ADDRESS not configured")
    marketplace_credential = str(
        getattr(settings.BUYER, "MARKETPLACE_CREDENTIAL", None) or ""
    )
    if not marketplace_credential:
        pytest.skip("BUYER.MARKETPLACE_CREDENTIAL not configured")

    vms_registry = str(settings.REGISTRY.API_URL or "")
    credits_registry = str(
        getattr(settings, "API_CREDITS", {}).get("REGISTRY_URL", "")
        if hasattr(settings, "API_CREDITS")
        else ""
    )
    if not credits_registry:
        credits_registry = str(settings.get("API_CREDITS.REGISTRY_URL", "") or "")
    if not credits_registry:
        pytest.skip("API_CREDITS.REGISTRY_URL not configured")

    rpc_url = (
        str(settings.BUYER.CHAIN_RPC_URL or "").strip()
        or str(settings.RPC.URL or "").strip()
        or "ws://localhost:8545"
    )
    if rpc_url.startswith("http://"):
        rpc_url = "ws://" + rpc_url[len("http://"):]
    elif rpc_url.startswith("https://"):
        rpc_url = "wss://" + rpc_url[len("https://"):]
    alkahest_path = _alkahest_addresses_path()
    if not alkahest_path:
        pytest.skip("Could not locate alkahest_anvil_addresses.json")

    registries = tuple(url for url in (vms_registry, credits_registry) if url)
    log.info("[credits_buyer_cli] registries=%s rpc=%s", registries, rpc_url)
    yield create_profiled_buyer_cli(
        binary=buyer_cli_binary,
        base=tmp_path_factory.mktemp("credits_buyer_cli"),
        domain_identity="api_credits.v1",
        marketplace_scheme=IdentityScheme.EIP191,
        marketplace_credential=marketplace_credential,
        registries=registries,
        credential_variable="ARKHAI_E2E_BUYER_MARKETPLACE_CREDENTIAL",
        toml_sections=(
            "[wallet]",
            f"address = {_toml_quote(wallet_address)}",
            f"private_key = {_toml_quote(private_key)}",
            "",
            "[chains.anvil]",
            f"rpc_url = {_toml_quote(rpc_url)}",
            f"alkahest_address_config_path = {_toml_quote(alkahest_path)}",
            "",
        ),
    )


@pytest.fixture(scope="module")
def credits_deal_state() -> DomainDealState:
    return DomainDealState(domain_identity="api_credits.v1")


def _forecast(secret: str, base_url: str) -> httpx.Response:
    with httpx.Client(timeout=15) as c:
        return c.get(
            f"{base_url.rstrip('/')}/api/forecast",
            headers={"Authorization": f"Bearer {secret}"},
        )


def test_credits_full_deal(
    credits_buyer_cli: BuyerCli,
    credits_deal_state: DomainDealState,
) -> None:
    # --- 1. Buy 3 credits into a fresh key --------------------------------
    buy = credits_buyer_cli.run([
        "credits", "buy",
        "--quantity", "3",
        "--new-key",
        "--service-name", "weather-api",
        "--chain", "anvil",
        "--max-matches", "5",
        "--max-rounds", "10",
        "--poll-interval", "1.0",
        "--settlement-timeout", "300",
        "--expiration", "3600",
        "--yes",
    ], timeout=320.0)
    assert_market_run_succeeded(buy, command="market credits buy --new-key")
    lifecycle = ordered_events(
        buy.read_events(),
        "discover",
        "negotiation_started",
        "negotiation_completed",
        "settlement_submitted",
        "credentials_delivered",
        "run_ended",
    )
    credits_deal_state.complete(
        DealStage.DISCOVERY,
        listing_id=str(lifecycle[1]["listing_id"]),
    )
    credits_deal_state.complete(
        DealStage.NEGOTIATION,
        negotiation_id=str(lifecycle[-1]["negotiation_id"]),
    )
    credits_deal_state.complete(
        DealStage.SETTLEMENT,
        settlement_id=str(lifecycle[-1]["escrow_uid"]),
    )

    creds = buy.wait_for_event(
        "credentials_delivered", timeout=10.0,
    )["credentials"]
    secret = creds["secret"]
    base_url = creds["base_url"]
    key_id = creds["key_id"]
    assert secret and base_url and key_id, "credentials event is incomplete"
    credits_deal_state.complete(
        DealStage.DELIVERY,
        fulfillment_ref=str(lifecycle[-1]["fulfillment_uid"]),
        delivery={"key_id": key_id, "service": "weather-api"},
    )
    log.info("[credits] issued key %s, base_url %s", key_id, base_url)

    # --- 2. Consume the 3 credits, then hit 402 ---------------------------
    for i in range(3):
        r = _forecast(secret, base_url)
        assert r.status_code == 200, f"consume #{i+1} got {r.status_code}: {r.text}"
        assert r.json()["forecast"] == "sunny"

    drained = _forecast(secret, base_url)
    assert drained.status_code == 402, (
        f"expected 402 after draining, got {drained.status_code}: {drained.text}"
    )
    body = drained.json()
    assert body["error"] == "insufficient_credits"
    # The purchase pointer is the re-purchase loop's signpost.
    assert body["purchase"]["service_name"] == "weather-api"
    credits_deal_state.complete(
        DealStage.TEARDOWN,
        teardown={"kind": "grant_consumed", "status_code": drained.status_code},
    )
    credits_deal_state.assert_complete()

    # --- 3. Top up the SAME key with 2 more credits -----------------------
    topup = credits_buyer_cli.run([
        "credits", "buy",
        "--quantity", "2",
        "--key-id", key_id,
        "--service-name", "weather-api",
        "--chain", "anvil",
        "--max-matches", "5",
        "--max-rounds", "10",
        "--poll-interval", "1.0",
        "--settlement-timeout", "300",
        "--expiration", "3600",
        "--yes",
    ], timeout=320.0)
    assert_market_run_succeeded(topup, command="market credits buy --key-id")
    topup.wait_for_event(
        "run_ended", predicate=lambda e: e.get("status") == "ready", timeout=10.0,
    )

    # --- 4. Consume succeeds again, then the top-up grant exhausts ----------
    # The middleware's short verify cache hides the top-up briefly; poll
    # through that window (TTL is 3s in the sample app's compose env).
    deadline = time.monotonic() + 20.0
    last = None
    while time.monotonic() < deadline:
        response = _forecast(secret, base_url)
        if response.status_code == 200:
            assert response.json()["forecast"] == "sunny"
            break
        last = response
        time.sleep(1.0)
    else:
        raise AssertionError(
            "consume did not recover to 200 after top-up within 20s; "
            f"last={getattr(last, 'status_code', None)}: "
            f"{getattr(last, 'text', '')}"
        )
    final_credit = _forecast(secret, base_url)
    assert final_credit.status_code == 200, final_credit.text
    exhausted_again = _forecast(secret, base_url)
    assert exhausted_again.status_code == 402, exhausted_again.text
