"""Accepted terms and key scope through the real credits service and its typed clients."""

from __future__ import annotations

from pathlib import Path

import pytest
from arkhai_api.issuance import KeyDisposition, accepted_terms_digest, issuance_request
from arkhai_api_client import AuthorityError

from apicredits_service.config import ISSUANCE_LABEL
from tests.integration.signed_service import load_signed_app, unload_service_modules
from tests.integration.test_compat_baseline import (
    BUYER,
    _capacity_admin,
    _gated_client,
    _seller_client,
)

TERMS = {"attestation": None, "rate_card": {"asset": "USD/6", "request_credits": 2}}
SCOPE = {"service": "weather-api", "resource_id": "weather-quota"}


@pytest.fixture
async def app(tmp_path: Path, monkeypatch):
    app = load_signed_app(tmp_path, monkeypatch)
    try:
        await _capacity_admin(app).register_resource(
            "weather-quota",
            total_units=100,
            resource_type="api.credits",
            attributes={"service": "weather-api"},
            pool_id="default",
        )
        yield app
    finally:
        unload_service_modules()


def _request(negotiation_id: str, *, pinned: bool, existing_key: str | None = None, terms=TERMS):
    fields = (
        {"accepted_terms": terms, "terms_digest": accepted_terms_digest(terms), "request_charge": 2}
        if pinned
        else {}
    )
    return issuance_request(
        ISSUANCE_LABEL,
        negotiation_id=negotiation_id,
        owner=BUYER,
        service="weather-api",
        resource_id="weather-quota",
        quantity=10,
        key=KeyDisposition(mode="existing", key_id=existing_key) if existing_key else KeyDisposition(mode="new"),
        **fields,
    )


async def test_a_pinned_key_verifies_with_its_terms_and_a_top_up_under_other_terms_is_refused(app):
    issued = await _seller_client(app).submit_issuance(_request("neg-pin-1", pinned=True))

    verified = await _gated_client(app).verify(key_id=issued.key_id, secret=issued.secret, **SCOPE)
    assert verified.valid is True
    assert (verified.accepted_terms, verified.terms_digest, verified.request_charge) == (
        TERMS, accepted_terms_digest(TERMS), 2,
    )

    repriced = {**TERMS, "rate_card": {**TERMS["rate_card"], "request_credits": 9}}
    with pytest.raises(AuthorityError) as refused:
        await _seller_client(app).submit_issuance(
            _request("neg-pin-2", pinned=True, existing_key=issued.key_id, terms=repriced)
        )
    assert refused.value.reason == "key_out_of_scope"
    assert (await _gated_client(app).verify(key_id=issued.key_id, secret=issued.secret)).balance == 10


async def test_a_key_presented_under_another_scope_is_refused_uncharged(app):
    issued = await _seller_client(app).submit_issuance(_request("neg-scope-1", pinned=False))
    gated = _gated_client(app)

    refused = await gated.verify(key_id=issued.key_id, secret=issued.secret, service="other-api")
    assert (refused.valid, refused.status, refused.balance) == (False, "key_out_of_scope", 0)
    consumed = await gated.consume(key_id=issued.key_id, amount=1, resource_id="other-quota")
    assert (consumed.ok, consumed.reason) == (False, "key_out_of_scope")

    admitted = await gated.verify(key_id=issued.key_id, secret=issued.secret, **SCOPE)
    assert (admitted.valid, admitted.balance, admitted.request_charge) == (True, 10, None)
    assert (await gated.consume(key_id=issued.key_id, amount=1, **SCOPE)).balance == 9
    assert (await gated.consume(key_id=issued.key_id, amount=1)).balance == 8
