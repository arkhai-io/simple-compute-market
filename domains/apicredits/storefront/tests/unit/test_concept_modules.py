"""API-credits terms, and the names its chain's guards run under."""

from __future__ import annotations

from arkhai_api_selling.negotiation import default_guards
from arkhai_apicredits.negotiation.terms import (
    make_api_credits_provision_terms,
    provision_key_id,
    provision_key_mode,
    provision_quantity,
)

from apicredits_storefront.container import SELLING_CONTRIBUTIONS


def test_provision_terms_round_trip():
    terms = make_api_credits_provision_terms(
        quantity=5, key_mode="existing", key_id="ak_abc",
    )
    assert terms.kind == "api_credits.v1"
    assert provision_quantity(terms) == 5
    assert provision_key_mode(terms) == "existing"
    assert provision_key_id(terms) == "ak_abc"

    # Carrier-agnostic: plain dicts off the wire parse the same.
    wire = terms.model_dump()
    assert provision_quantity(wire) == 5
    assert provision_key_mode(wire) == "existing"
    assert provision_key_id(wire) == "ak_abc"


def test_provision_terms_defaults():
    terms = make_api_credits_provision_terms(quantity=1)
    assert provision_key_mode(terms) == "new"
    assert provision_key_id(terms) is None
    assert provision_quantity({}) is None
    assert provision_key_mode({}) == "new"


def test_the_chain_runs_the_guards_under_the_names_its_configuration_uses():
    assert default_guards(SELLING_CONTRIBUTIONS) == (
        "api_credits_round_zero_guard",
        "buyer_counter_guard",
        "credit_quota_guard",
        "key_owned_by_buyer_principal",
        "escrow_shape_guard",
    )
