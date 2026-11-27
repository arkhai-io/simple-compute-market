"""The inference authority over ASGI through the storefront, gate, and site clients that call it."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from arkhai_api.issuance import (
    KeyDisposition,
    accepted_terms_digest,
    issuance_request,
    issuance_request_digest,
)
from arkhai_api.labels import IssuanceLabel
from arkhai_api_client import AuthorityClient, AuthorityError
from arkhai_api_gate.client import TokensClient
from arkhai_api_gate.signing import AuthoritySigning, build_trusted_authorities
from arkhai_inference.label import INFERENCE_LABEL
from market_identity import Identity, TrustedIdentitySet
from market_site_client.client import SiteCapacityAdminClient

from tests.integration.signed_service import (
    AUTHORITY,
    GATEWAY_SIGNER,
    STOREFRONT_SIGNER,
    load_signed_app,
    signed_headers,
    unload_service_modules,
)

BASE_URL = "http://inference-service"
SERVED_MODEL = "stub-instruct"
QUOTA = "stub-instruct-quota"
SCOPE = {"service": SERVED_MODEL, "resource_id": QUOTA}
TERMS = {
    "attestation": None,
    "rate_card": {"asset": "0x0000000000000000000000000000000000000006", "request_credits": 3},
}
# The API-credits label as that domain spells it, for the digest and schema
# comparisons; this root does not import another domain.
API_CREDITS_LABEL = IssuanceLabel("api-credits", "api-credit-fulfillment.v1")

# Deterministic development principal; never used on any network.
BUYER = Identity(scheme="eip191", identifier="0xabcdef0000000000000000000000000000000001")


@pytest.fixture
async def app(tmp_path: Path, monkeypatch):
    app = load_signed_app(tmp_path, monkeypatch)
    try:
        await _capacity_admin(app).register_resource(
            QUOTA,
            total_units=10_000_000,
            resource_type="inference",
            attributes={"service": SERVED_MODEL},
            pool_id="default",
        )
        yield app
    finally:
        unload_service_modules()


def _transport(app) -> httpx.ASGITransport:
    return httpx.ASGITransport(app=app)


def _expected() -> TrustedIdentitySet:
    return TrustedIdentitySet(identities=(AUTHORITY.identity,))


def _capacity_admin(app) -> SiteCapacityAdminClient:
    return SiteCapacityAdminClient(
        BASE_URL, signer=STOREFRONT_SIGNER, expected_authorities=_expected(), transport=_transport(app)
    )


def _storefront(app) -> AuthorityClient:
    return AuthorityClient(
        BASE_URL,
        label=INFERENCE_LABEL,
        transport=_transport(app),
        signer=STOREFRONT_SIGNER,
        expected_authorities=_expected(),
    )


def _gateway(app) -> TokensClient:
    return TokensClient(
        service_url=BASE_URL,
        http=httpx.AsyncClient(transport=_transport(app), base_url=BASE_URL),
        signing=AuthoritySigning(
            authority_label="inference-service",
            signer=GATEWAY_SIGNER,
            expected_authorities=build_trusted_authorities([AUTHORITY.identity.model_dump(mode="json")]),
        ),
    )


def _request(
    negotiation_id: str,
    quantity: int,
    *,
    label: IssuanceLabel = INFERENCE_LABEL,
    existing_key: str | None = None,
    terms: dict = TERMS,
    service: str = SERVED_MODEL,
    resource_id: str = QUOTA,
):
    return issuance_request(
        label,
        negotiation_id=negotiation_id,
        owner=BUYER,
        service=service,
        resource_id=resource_id,
        quantity=quantity,
        key=KeyDisposition(mode="existing", key_id=existing_key) if existing_key else KeyDisposition(mode="new"),
        accepted_terms=terms,
        terms_digest=accepted_terms_digest(terms),
        request_charge=terms["rate_card"]["request_credits"],
    )


async def test_a_purchase_is_issued_as_an_ik_key_holding_its_quantity_under_the_inference_digest(app):
    request = _request("neg-issue-1", 2_000_000)
    issued = await _storefront(app).submit_issuance(request)

    assert issued.key_id.startswith("ik_")
    assert issued.balance == 2_000_000
    assert issued.fulfillment_id.startswith("inference-fulfillment.v1")
    assert issued.request_digest == issuance_request_digest(INFERENCE_LABEL, request)
    same_inputs = _request("neg-issue-1", 2_000_000, label=API_CREDITS_LABEL)
    assert issued.request_digest != issuance_request_digest(API_CREDITS_LABEL, same_inputs)

    verified = await _gateway(app).verify(key_id=issued.key_id, secret=issued.secret, **SCOPE)
    assert (verified.valid, verified.balance) == (True, 2_000_000)
    assert (verified.accepted_terms, verified.terms_digest, verified.request_charge) == (
        TERMS,
        accepted_terms_digest(TERMS),
        3,
    )
    consumed = await _gateway(app).consume(key_id=issued.key_id, amount=verified.request_charge, **SCOPE)
    assert (consumed.ok, consumed.balance) == (True, 2_000_000 - 3)


@pytest.mark.parametrize(
    "top_up",
    [
        {"terms": {**TERMS, "rate_card": {**TERMS["rate_card"], "request_credits": 5}}},
        {"service": "other-model"},
        {"resource_id": "other-model-quota"},
    ],
    ids=["other-terms", "other-service", "other-resource"],
)
async def test_a_top_up_from_another_listing_is_refused_out_of_scope_with_the_balance_unchanged(app, top_up):
    storefront = _storefront(app)
    issued = await storefront.submit_issuance(_request("neg-scope-1", 100))

    with pytest.raises(AuthorityError) as refused:
        await storefront.submit_issuance(_request("neg-scope-2", 50, existing_key=issued.key_id, **top_up))
    assert refused.value.reason == "key_out_of_scope"

    verified = await _gateway(app).verify(key_id=issued.key_id, secret=issued.secret, **SCOPE)
    assert verified.balance == 100


async def test_a_key_presented_under_another_offerings_scope_is_refused_uncharged(app):
    issued = await _storefront(app).submit_issuance(_request("neg-other-1", 100))
    gateway = _gateway(app)

    refused = await gateway.verify(key_id=issued.key_id, secret=issued.secret, service="other-model", resource_id=QUOTA)
    assert (refused.valid, refused.status) == (False, "key_out_of_scope")
    consumed = await gateway.consume(key_id=issued.key_id, amount=3, service="other-model", resource_id=QUOTA)
    assert (consumed.ok, consumed.reason) == (False, "key_out_of_scope")

    assert (await gateway.verify(key_id=issued.key_id, secret=issued.secret, **SCOPE)).balance == 100


async def test_an_api_credits_labelled_issuance_is_refused_by_schema(app):
    payload = _request("neg-label-1", 10, label=API_CREDITS_LABEL).model_dump(mode="json", exclude_none=True)
    async with httpx.AsyncClient(transport=_transport(app), base_url=BASE_URL) as client:
        response = await client.post(
            "/api/v1/issuance",
            json=payload,
            headers=signed_headers(
                signer=STOREFRONT_SIGNER,
                role="seller",
                method="POST",
                operation="credits_issue",
                resource=payload["fulfillment_id"],
                body=payload,
            ),
        )
    assert response.status_code == 422
    assert any(error["loc"][-1] == "schema" for error in response.json()["detail"])


async def test_a_bearer_secret_is_not_a_marketplace_signature(app):
    issued = await _storefront(app).submit_issuance(_request("neg-bearer-1", 10))
    top_up = _request("neg-bearer-2", 10, existing_key=issued.key_id).model_dump(mode="json", exclude_none=True)
    bearer = {"Authorization": f"Bearer {issued.secret}"}

    async with httpx.AsyncClient(transport=_transport(app), base_url=BASE_URL) as client:
        refused = await client.post("/api/v1/issuance", json=top_up, headers=bearer)
        listed = await client.get(f"/api/v1/keys/{issued.key_id}", headers=bearer)

    assert (refused.status_code, listed.status_code) == (401, 401)
    verified = await _gateway(app).verify(key_id=issued.key_id, secret=issued.secret, **SCOPE)
    assert verified.balance == 10


async def test_a_caller_naming_no_scope_can_neither_verify_nor_charge_a_key(app):
    issued = await _storefront(app).submit_issuance(_request("neg-unscoped-1", 100))
    gateway = _gateway(app)

    verified = await gateway.verify(key_id=issued.key_id, secret=issued.secret)
    assert (verified.valid, verified.balance) == (False, 0)
    consumed = await gateway.consume(key_id=issued.key_id, amount=3)
    assert (consumed.ok, consumed.reason) == (False, "scope_required")
    batched = await gateway.consume_batch([
        {"key_id": issued.key_id, "amount": 3},
        {"key_id": issued.key_id, "amount": 3, **SCOPE},
    ])
    assert [(r.ok, r.reason) for r in batched] == [(False, "scope_required"), (True, None)]

    assert (await gateway.verify(key_id=issued.key_id, secret=issued.secret, **SCOPE)).balance == 97


async def test_a_consumption_at_another_amount_than_the_pinned_charge_is_refused_and_charges_nothing(app):
    issued = await _storefront(app).submit_issuance(_request("neg-charge-1", 100))
    gateway = _gateway(app)

    consumed = await gateway.consume(key_id=issued.key_id, amount=5, **SCOPE)
    assert (consumed.ok, consumed.reason, consumed.balance) == (False, "charge_mismatch", 100)
    batched = await gateway.consume_batch([
        {"key_id": issued.key_id, "amount": 5, "idempotency_key": "b1", **SCOPE},
        {"key_id": issued.key_id, "amount": 3, "idempotency_key": "b2", **SCOPE},
    ])
    assert [(r.ok, r.reason, r.balance) for r in batched] == [(False, "charge_mismatch", 100), (True, None, 97)]

    assert (await gateway.verify(key_id=issued.key_id, secret=issued.secret, **SCOPE)).balance == 97
