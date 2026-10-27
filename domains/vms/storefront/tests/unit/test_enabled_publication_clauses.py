"""A readable clause naming a mechanism the storefront does not enable is dropped
from a candidate, in whichever form the clause is written; a clause that cannot
be read is kept for compilation to refuse, whatever mechanism it names."""

from __future__ import annotations

import pytest

from market_storefront.services.publication_terms import enabled_publication_clauses

from tests._settings_overrides import replaced_setting

# Alkahest is configured but disabled; contact exchange is enabled. Development
# values on a reserved domain.
_SETTLEMENT = {
    "schema_version": 1,
    "priority": ["contact-exchange.v1"],
    "alkahest": {"enabled": False},
    "contact": {
        "enabled": True,
        "contact_payload": {"email": "sales@seller.invalid"},
        "profiles": {"default": {"channel": "email", "terms": "Introduction."}},
    },
}
# A development token address; never used on a public network.
_TOKEN = "0x" + "22" * 20
_CONTACT = {
    "mechanism": "contact-exchange.v1",
    "asset": "introduction",
    "mechanism_input": {"profile": "default"},
}
_ALKAHEST_INPUT = {"chain": "anvil", "escrow_kind": "erc20_escrow_obligation_default"}


def test_a_disabled_mechanisms_clauses_are_dropped_as_dsl_text_and_as_mappings():
    alkahest_text = (
        f"mechanism=alkahest asset={_TOKEN} rate=1/hour alkahest.chain=anvil "
        "alkahest.escrow_kind=erc20_escrow_obligation_default"
    )
    alkahest_mapping = {
        "mechanism": "alkahest.v1",
        "asset": _TOKEN,
        "rate": "1",
        "per": "hour",
        "mechanism_input": dict(_ALKAHEST_INPUT),
    }

    with replaced_setting("settlement", _SETTLEMENT):
        kept, disabled = enabled_publication_clauses(
            [alkahest_text, _CONTACT, alkahest_mapping]
        )

    assert kept == [_CONTACT]
    assert disabled == ("alkahest.v1",)


@pytest.mark.parametrize(
    "malformed",
    [
        f"mechanism=alkahest asset={_TOKEN} rate=1/hour chain=anvil",
        f"mechanism=alkahest asset={_TOKEN} rate=1/hour alkahest.chain=anvil",
        f"mechanism=alkahest asset={_TOKEN} rate=1",
        {
            "mechanism": "alkahest.v1",
            "asset": _TOKEN,
            "rate": "1",
            "per": "hour",
            "mechanism_input": dict(_ALKAHEST_INPUT),
            "unknown": True,
        },
        {
            "mechanism": "alkahest.v1",
            "asset": _TOKEN,
            "rate": "1",
            "per": "hour",
            "mechanism_input": {"chain": "anvil"},
        },
        {"mechanism": "alkahest.v1", "asset": _TOKEN, "rate": 1.5, "per": "hour"},
    ],
    ids=[
        "dsl-unqualified-field",
        "dsl-incomplete-input",
        "dsl-rate-without-unit",
        "mapping-unknown-field",
        "mapping-incomplete-input",
        "mapping-binary-rate",
    ],
)
def test_a_malformed_clause_naming_a_disabled_mechanism_is_kept_for_compilation_to_refuse(
    malformed,
):
    """Its mechanism's section is never consulted: a clause that cannot be read
    is a defect, never a mechanism the configuration rules out."""
    with replaced_setting("settlement", _SETTLEMENT):
        kept, disabled = enabled_publication_clauses([malformed, _CONTACT])

    assert kept == [malformed, _CONTACT]
    assert disabled == ()


def test_a_clause_naming_no_installed_mechanism_is_kept_for_compilation_to_refuse():
    unreadable = {"asset": _TOKEN, "rate": "1", "per": "hour"}

    with replaced_setting("settlement", _SETTLEMENT):
        kept, disabled = enabled_publication_clauses([unreadable, "asset=usd"])

    assert kept == [unreadable, "asset=usd"]
    assert disabled == ()
