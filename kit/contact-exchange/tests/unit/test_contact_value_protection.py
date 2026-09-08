"""Literal configured contacts cannot cross decoded public mechanism surfaces."""

from __future__ import annotations

import pytest
from market_contact_exchange import (
    MECHANISM,
    ContactSettlementConfig,
    contains_contact_value,
    contact_accepted_obligation_builder,
    contact_option_builder,
    contact_preflight,
    create_contact_exchange_registration,
    validate_contact_payload,
)
from market_core.schemas import derive_settlement_option_id
from market_settlement_runtime import SettlementConfigurationError, SettlementConfigurationRegistry
from pydantic import ValidationError

# Synthetic test-only canaries and public principals; never deploy them live.
_CONTACTS = {
    "unicode": "Zoë@example.invalid",
    "quote": 'quote"@example.invalid',
    "slash": "slash/@example.invalid",
    "backslash": "slash\\@example.invalid",
    "newline": "line\nbreak@example.invalid",
}
_BUYER = {"scheme": "ed25519", "identifier": "ERERERERERERERERERERERERERERERERERERERERERE"}
_SELLER = {"scheme": "ed25519", "identifier": "IiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiI"}


@pytest.fixture(params=_CONTACTS.values(), ids=_CONTACTS)
def contact(request):
    return validate_contact_payload({"email": request.param})["email"]


def _raw_config(contact):
    return {
        "enabled": True,
        "contact_payload": {"email": contact},
        "profiles": {"default": {"channel": "email", "terms": "Public introduction terms."}},
    }


def test_profile_guard_refuses_escaped_contact_with_key_only_diagnostic(contact):
    raw = _raw_config(contact)
    raw["profiles"]["default"]["terms"] += " " + contact
    with pytest.raises(ValidationError) as rejected:
        ContactSettlementConfig.model_validate(raw)
    # Inspect the mechanism's error, without rendering Pydantic's raw inputs.
    message = str(rejected.value.errors(include_input=False)[0]["ctx"]["error"])
    assert message == "contact payload values must not appear in published profiles: email"
    assert contact not in message
    registry = SettlementConfigurationRegistry((create_contact_exchange_registration(),))
    with pytest.raises(SettlementConfigurationError) as resolved:
        registry.resolve({"priority": [MECHANISM], "contact": raw}, role="seller")
    assert contact not in str(resolved.value)


@pytest.mark.parametrize("placement", ["key", "value"])
def test_option_guard_refuses_escaped_contact_in_public_resources(contact, placement):
    config = ContactSettlementConfig.model_validate(_raw_config(contact))
    readiness = contact_preflight(config, {}, "seller")
    annotation = {contact: "synthetic"} if placement == "key" else {"note": contact}
    resources = {
        "publication_clause": {
            "mechanism": MECHANISM, "asset": "introduction",
            "mechanism_input": {"profile": "default"},
        },
        "claimant_principal": {**_SELLER, "annotation": [annotation]},
    }
    with pytest.raises(ValueError, match="must not reach a published option") as rejected:
        contact_option_builder(config, readiness, resources, "seller")
    assert contact not in str(rejected.value)


@pytest.mark.parametrize("placement", ["selected_terms", "context_key", "context_value"])
def test_accepted_guard_refuses_escaped_contact_in_public_context(contact, placement):
    config = ContactSettlementConfig.model_validate(_raw_config(contact))
    params = {"profile": "default", "channel": "email", "terms": "Public terms", "claimant_principal": _SELLER}
    context = {
        "buyer_principal": _BUYER, "seller_principal": _SELLER,
        "expiration_unix": 1_900_000_000,
    }
    if placement == "selected_terms":
        params["terms"] = "Public terms " + contact
    else:
        note = {contact: "synthetic"} if placement == "context_key" else {"note": contact}
        context["negotiated_context"] = {"notes": [note]}
    option = {
        "option_id": derive_settlement_option_id(
            mechanism=MECHANISM, asset="introduction", rates=[], params=params,
        ),
        "mechanism": MECHANISM, "asset": "introduction", "rates": [], "params": params,
    }
    with pytest.raises(ValueError, match="must not reach an accepted obligation") as rejected:
        contact_accepted_obligation_builder(config, option, context)
    assert contact not in str(rejected.value)


def test_literal_check_visits_decoded_containers_without_normalization(contact):
    assert contains_contact_value({"nested": [{contact: "public"}]}, contact)
    assert contains_contact_value({"nested": [None, 1, {"value": "prefix " + contact}]}, contact)
    assert contains_contact_value((False, {"value": contact}), contact)
    assert not contains_contact_value({"nested": [None, 1, "public"]}, contact)
    assert not contains_contact_value({"value": contact.upper()}, contact)
    assert not contains_contact_value({"value": "public"}, "")
