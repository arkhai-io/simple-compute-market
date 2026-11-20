"""Full inference deal, driven by `market inference buy`.

    discover (schema-routed) → negotiate (new key) → settle → call the model
    → an unlisted model is refused uncharged → consume to 402
    → buy again into the existing key → call again → stream a completion
    → a key bought under another listing is refused at this gateway
    → an hour of lane time later the last credit is charged once

The topology (the inference lane): a registry speaking the ``inference``
schema, the inference service, the gateway in front of the deterministic model
stub, the inference storefront (self-seeds one model-card listing), and the
lane's own compute and API-credit registries, which the buyer pins but the
schema filter leaves alone. The model is called through the gateway with the
delivered key, exactly as a client of the served model would.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

import asyncio

import httpx
import pytest
from arkhai_inference.schema import InferenceMaterialization
from market_alkahest.alkahest import get_erc20_escrow_obligation_default
from market_identity import Identity, IdentityScheme, TrustedIdentitySet, create_signer
from market_site_client.client import SiteCapacityAdminClient
from storefront_client.client import StorefrontClient

from tests.e2e.roles.buyer_cli import _alkahest_addresses_path

from tests.e2e.roles.buyer_cli import BuyerCli
from tests.e2e.roles.helpers.domain_deal import (
    DealStage,
    DomainDealState,
    assert_market_run_succeeded,
    ordered_events,
)
from tests.e2e.roles.scenarios.inference.conftest import lane_setting

log = logging.getLogger(__name__)

pytestmark = pytest.mark.e2e_inference_deal

MODEL_QUERY = 'model_id="arkhai/stub-instruct"'
OTHER_MODEL = "other-instruct"
OTHER_QUOTA = "other-instruct-quota"
PROMPT = "hello"
# One request credit per request (the seeded card's request_credits), so a key
# bought for QUANTITY credits answers QUANTITY requests.
QUANTITY = 4


def _stub_reply(prompt: str) -> str:
    """The model stub's reply to ``prompt``: a digest of it, so any change shows."""
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    return f"Stub reply {digest[:8]} {digest[8:16]} {digest[16:24]}."


def _buy(cli: BuyerCli, *key: str, quantity: int) -> Any:
    run = cli.run([
        "inference", "buy",
        "--quantity", str(quantity),
        *key,
        "--resource", MODEL_QUERY,
        "--max-matches", "5",
        "--max-rounds", "10",
        "--poll-interval", "1.0",
        "--settlement-timeout", "300",
        "--expiration", "3600",
        "--yes",
    ], timeout=320.0)
    assert_market_run_succeeded(run, command=f"market inference buy {' '.join(key)}")
    return run


def _chat(base_url: str, secret: str, *, model: str, stream: bool = False) -> httpx.Response:
    with httpx.Client(timeout=15) as client:
        return client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {secret}"},
            json={"model": model, "stream": stream, "messages": [{"role": "user", "content": PROMPT}]},
        )


def _reply(response: httpx.Response) -> str:
    assert response.status_code == 200, f"{response.status_code}: {response.text}"
    return response.json()["choices"][0]["message"]["content"]


async def _publish_other_listing() -> str:
    """Register a second model's quota and publish its listing, as the seller.

    The gateway fronts only the seeded model, so a key bought under this
    listing is scoped to an offering it does not serve.
    """
    seller = create_signer(IdentityScheme.EIP191, lane_setting("INFERENCE.SELLER_MARKETPLACE_CREDENTIAL"))
    authority = TrustedIdentitySet(identities=(Identity(
        scheme="ed25519", identifier=lane_setting("INFERENCE.SERVICE_AUTHORITY_IDENTIFIER"),
    ),))
    site = SiteCapacityAdminClient(
        lane_setting("INFERENCE.SERVICE_URL"), signer=seller, expected_authorities=authority,
    )
    await site.register_resource(
        OTHER_QUOTA, total_units=1_000_000, resource_type="inference",
        attributes={"service": OTHER_MODEL}, pool_id="default",
    )
    token = "0x9fe46736679d2d9a65f0992f2272de9f3c7fa6e0"
    escrow = get_erc20_escrow_obligation_default("anvil", config_path=_alkahest_addresses_path())
    async with StorefrontClient(
        lane_setting("INFERENCE.STOREFRONT_URL"), seller, caller_role="seller",
        expected_publishers=TrustedIdentitySet(identities=(seller.identity,)),
    ) as storefront:
        published = await storefront.authenticated_request(
            "POST", "/api/v1/listings/publish-from-quota",
            role="seller", operation="create_listing",
            resource=f"{seller.identity.scheme.value}:{seller.identity.identifier}",
            body={
                "resource_id": OTHER_QUOTA,
                "accepted_escrows": [{
                    "chain_name": "anvil",
                    "escrow_address": str(escrow).lower(),
                    "literal_fields": {"token": token},
                    "rates": [{"field": "amount", "per": "credit", "value": "1"}],
                }],
                "paused": False,
                "model_card": {
                    "owner": "arkhai", "name": OTHER_MODEL, "artifact_ref": f"dev://arkhai/{OTHER_MODEL}",
                    "provenance": "self-hosted", "served_model_name": OTHER_MODEL,
                    "context_length": 8192, "quantization": "none",
                    "architecture": {"modality": "text->text"},
                    "supported_parameters": ["max_tokens", "stream"],
                    "endpoint": {"base_url": lane_setting("INFERENCE.GATEWAY_URL").rstrip("/") + "/v1"},
                    "rate_card": {
                        "asset": token, "prompt_credits_per_million": 0,
                        "completion_credits_per_million": 0, "request_credits": 1,
                    },
                },
            },
        )
    return str(published["listing_id"])


@pytest.fixture(scope="module")
def inference_deal_state() -> DomainDealState:
    return DomainDealState(domain_identity="inference.v1")


def test_inference_full_deal(
    inference_buyer_cli: BuyerCli,
    inference_deal_state: DomainDealState,
    monkeypatch: pytest.MonkeyPatch,
    lane_time,
) -> None:
    served_model = lane_setting("INFERENCE.SERVED_MODEL_NAME")

    # A second model's listing, so the model filter has something to leave out;
    # step (f) buys it.
    other_listing = asyncio.run(_publish_other_listing())
    log.info("[inference] published %s for %s", other_listing, OTHER_MODEL)

    # --- a. The schema filter routes discovery to the inference registry -----
    # Wide enough that the table prints the model id whole.
    monkeypatch.setenv("COLUMNS", "240")
    listed = inference_buyer_cli.run(
        ["inference", "listing", "list", "--resource", MODEL_QUERY], timeout=60.0,
    )
    assert listed.returncode == 0, f"listing list: {listed.stderr()[-2000:]}"
    assert "arkhai/stub-instruct" in listed.stdout(), listed.stdout()
    assert f"arkhai/{OTHER_MODEL}" not in listed.stdout(), listed.stdout()
    unfiltered = inference_buyer_cli.run(["inference", "listing", "list"], timeout=60.0)
    assert unfiltered.returncode == 0, f"listing list: {unfiltered.stderr()[-2000:]}"
    assert f"arkhai/{OTHER_MODEL}" in unfiltered.stdout(), unfiltered.stdout()
    for registry, schema in (
        (lane_setting("INFERENCE.COMPUTE_REGISTRY_URL"), "compute.market"),
        (lane_setting("INFERENCE.API_CREDITS_REGISTRY_URL"), "api_credits"),
    ):
        assert f"skipping {registry.rstrip('/')}: serves schema '{schema}'" in listed.stderr(), listed.stderr()

    # --- b. Buy request credits into a new key --------------------------------
    buy = _buy(inference_buyer_cli, "--new-key", quantity=QUANTITY)
    events = buy.read_events()
    lifecycle = ordered_events(
        events,
        "discover",
        "negotiation_started",
        "negotiation_completed",
        "settlement_submitted",
        "credentials_delivered",
        "run_ended",
    )
    inference_deal_state.complete(DealStage.DISCOVERY, listing_id=str(lifecycle[1]["listing_id"]))
    inference_deal_state.complete(
        DealStage.NEGOTIATION, negotiation_id=str(lifecycle[-1]["negotiation_id"]),
    )
    inference_deal_state.complete(DealStage.SETTLEMENT, settlement_id=str(lifecycle[-1]["escrow_uid"]))
    buy.wait_for_event("credentials_delivered", timeout=10.0)
    creds = inference_buyer_cli.credentials("inference", buy.run_id)
    secret, base_url, key_id = creds["secret"], creds["base_url"], creds["key_id"]
    assert secret and key_id, "credentials event is incomplete"
    assert base_url.rstrip("/") == lane_setting("INFERENCE.GATEWAY_URL").rstrip("/") + "/v1"
    assert creds.get("service_name") == served_model, creds
    inference_deal_state.complete(
        DealStage.DELIVERY,
        fulfillment_ref=str(lifecycle[-1]["fulfillment_uid"]),
        delivery={"key_id": key_id, "service": served_model},
    )
    log.info("[inference] issued key %s, base_url %s", key_id, base_url)

    # --- c. The public result materializes the listing it was sold under -----
    # Delivery results stay behind the buyer's private result boundary, so the
    # materialization is read from the saved delivery, not the run log.
    assert "materialization" in creds, f"the saved delivery holds no materialization: {sorted(creds)}"
    materialization = InferenceMaterialization.model_validate(creds["materialization"])
    assert materialization.listing_resource.served_model_name == served_model
    assert materialization.rate_card.request_credits == 1
    assert materialization.key_id == key_id

    # --- d. The model answers through the gateway ----------------------------
    assert _reply(_chat(base_url, secret, model=served_model)) == _stub_reply(PROMPT)

    # --- e. An unlisted model is refused before anything is charged ----------
    unlisted = _chat(base_url, secret, model="not-a-listed-model")
    assert unlisted.status_code == 404, unlisted.text
    # The uncharged proof: every remaining credit still buys a request.
    for _ in range(QUANTITY - 1):
        assert _reply(_chat(base_url, secret, model=served_model)) == _stub_reply(PROMPT)

    # --- g. The key is consumed to 402, pointing back at the listing ---------
    drained = _chat(base_url, secret, model=served_model)
    assert drained.status_code == 402, drained.text
    body = drained.json()
    assert body["error"] == "insufficient_credits"
    assert body["purchase"]["storefront_url"] == lane_setting("INFERENCE.STOREFRONT_URL").rstrip("/")
    assert body["purchase"]["registry_url"] == lane_setting("INFERENCE.REGISTRY_URL").rstrip("/")
    inference_deal_state.complete(
        DealStage.TEARDOWN, teardown={"kind": "grant_consumed", "status_code": drained.status_code},
    )
    inference_deal_state.assert_complete()

    # --- h. A top-up into the same key is admitted after the verify TTL ------
    # Three credits: one for this step, one for the stream, one for the advance.
    topup = _buy(inference_buyer_cli, "--key-id", key_id, quantity=3)
    topup.wait_for_event("run_ended", predicate=lambda e: e.get("status") == "ready", timeout=10.0)
    deadline = time.monotonic() + 20.0
    last: httpx.Response | None = None
    while time.monotonic() < deadline:
        last = _chat(base_url, secret, model=served_model)
        if last.status_code == 200:
            break
        time.sleep(1.0)
    else:
        raise AssertionError(
            "a request was not admitted within 20s of the top-up; "
            f"last={getattr(last, 'status_code', None)}: {getattr(last, 'text', '')}"
        )
    assert _reply(last) == _stub_reply(PROMPT)

    # --- i. A streamed completion is relayed as it is produced ---------------
    arrivals: list[tuple[float, str]] = []
    with httpx.Client(timeout=15) as client, client.stream(
        "POST",
        f"{base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {secret}"},
        json={"model": served_model, "stream": True, "messages": [{"role": "user", "content": PROMPT}]},
    ) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if line.startswith("data: "):
                arrivals.append((time.monotonic(), line.removeprefix("data: ")))
    assert arrivals and arrivals[-1][1] == "[DONE]"
    pieces = [json.loads(data)["choices"][0]["delta"]["content"] for _, data in arrivals[:-1]]
    assert "".join(pieces) == _stub_reply(PROMPT)
    # The stub pauses after every chunk, so a relayed stream spreads its events
    # over at least that long; a buffered one delivers them all at once.
    pause = float(lane_setting("INFERENCE.STUB_CHUNK_DELAY_SECONDS"))
    assert arrivals[-1][0] - arrivals[0][0] >= 0.5 * pause * len(pieces), arrivals

    # --- f. A key bought under another listing is refused at this gateway ----
    other = inference_buyer_cli.run([
        "inference", "buy",
        "--quantity", "2",
        "--new-key",
        "--resource", f'model_id="arkhai/{OTHER_MODEL}"',
        "--max-matches", "5",
        "--max-rounds", "10",
        "--poll-interval", "1.0",
        "--settlement-timeout", "300",
        "--expiration", "3600",
        "--yes",
    ], timeout=320.0)
    assert_market_run_succeeded(other, command="market inference buy (other listing)")
    other.wait_for_event("credentials_delivered", timeout=10.0)
    other_creds = inference_buyer_cli.credentials("inference", other.run_id)
    assert other_creds["key_id"] != key_id
    assert other_creds["balance"] == 2
    refused = _chat(base_url, other_creds["secret"], model=served_model)
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"] == "key_out_of_scope"
    # The uncharged proof: a top-up reports the authority's balance, which
    # still holds both credits the key was bought with.
    other_topup = inference_buyer_cli.run([
        "inference", "buy",
        "--quantity", "1",
        "--key-id", other_creds["key_id"],
        "--resource", f'model_id="arkhai/{OTHER_MODEL}"',
        "--max-matches", "5",
        "--max-rounds", "10",
        "--poll-interval", "1.0",
        "--settlement-timeout", "300",
        "--expiration", "3600",
        "--yes",
    ], timeout=320.0)
    assert_market_run_succeeded(other_topup, command="market inference buy --key-id (other listing)")
    delivered = other_topup.wait_for_event("credentials_delivered", timeout=10.0)
    assert (delivered["key_id"], delivered["balance"]) == (other_creds["key_id"], 3), delivered

    # --- j. An hour of lane time later, a request is still charged once ------
    # Past the signing skew, so the gateway's signed calls are admitted only
    # because it and the service both moved. A blocked skip on a wall-time run.
    if lane_time is None:
        pytest.skip("blocked: an hour forward needs lane time, and the run has none")
    lane_time.reach(lane_time.now() + 3600, fixed_by_agreement=False)
    assert _reply(_chat(base_url, secret, model=served_model)) == _stub_reply(PROMPT)
    spent = _chat(base_url, secret, model=served_model)
    assert spent.status_code == 402, spent.text
    assert spent.json()["error"] == "insufficient_credits"
