from __future__ import annotations

from typing import Any

import pytest
from market_contact_exchange import (
    ContactExchangeClient,
    ContactSettlementConfig,
    contact_buyer_compatibility,
    create_contact_exchange_registration,
    resolve_seller_contact,
    validate_contact_origins,
)
from market_core.schemas import SettlementOption
from market_settlement_runtime import (
    SettlementConfigurationError,
    SettlementConfigurationRegistry,
)

_CLAIMANT = {"scheme": "ed25519", "identifier": "seller-signing-key"}


def _seller_raw(**overrides: Any) -> dict[str, Any]:
    section: dict[str, Any] = {
        "enabled": True,
        "contact_payload": {"telegram": "@capacity_broker", "email": "deals@x.example"},
        "profiles": {
            "default": {
                "channel": "telegram",
                "terms": "Net-30, minimum 8 GPUs, prose contract on request.",
            }
        },
    }
    section.update(overrides)
    return {"priority": ["contact-exchange.v1"], "contact": section}


def _registry() -> SettlementConfigurationRegistry:
    return SettlementConfigurationRegistry((create_contact_exchange_registration(),))


def test_registration_declines_scalar_negotiation() -> None:
    assert create_contact_exchange_registration().negotiates_scalar_amount is False


async def test_seller_readiness_reports_channels_only() -> None:
    registry = _registry()
    config = registry.resolve(_seller_raw(), role="seller")
    (readiness,) = await registry.ordered_readiness(config, role="seller")
    assert readiness.ready
    assert readiness.public_details == {"channels": ["telegram"]}
    assert "@capacity_broker" not in str(readiness.safe_projection())


async def test_seller_readiness_blocks_without_payload_or_profiles() -> None:
    registry = _registry()
    config = registry.resolve(
        _seller_raw(contact_payload={}, profiles={}),
        role="seller",
    )
    (readiness,) = await registry.ordered_readiness(config, role="seller")
    assert not readiness.ready
    assert {blocker.code for blocker in readiness.blockers} == {
        "no_contact_profiles",
        "no_contact_payload",
    }


async def test_option_builder_produces_one_canonical_rateless_option() -> None:
    registry = _registry()
    config = registry.resolve(_seller_raw(), role="seller")
    (readiness,) = await registry.ordered_readiness(config, role="seller")
    built = registry.build_option(
        readiness,
        config,
        role="seller",
        resources={
            # The listing's origin: the single form serves only its one site.
            "origin": "default",
            "publication_clause": {
                "mechanism": "contact-exchange.v1",
                "asset": "introduction",
                "mechanism_input": {"profile": "default"},
            },
            "claimant_principal": _CLAIMANT,
        },
    )
    assert built["accepted_escrows"] == []
    option = SettlementOption.model_validate(built["settlement_options"][0])
    assert option.rates == []
    assert option.params["channel"] == "telegram"
    assert option.params["claimant_principal"] == _CLAIMANT
    assert "@capacity_broker" not in str(built)


async def test_option_builder_rejects_scalar_rate_clauses() -> None:
    registry = _registry()
    config = registry.resolve(_seller_raw(), role="seller")
    (readiness,) = await registry.ordered_readiness(config, role="seller")
    with pytest.raises(ValueError, match="declines scalar"):
        registry.build_option(
            readiness,
            config,
            role="seller",
            resources={
                # The listing's origin: the single form serves only its one site.
                "origin": "default",
                "publication_clause": {
                    "mechanism": "contact-exchange.v1",
                    "asset": "introduction",
                    "rate": "100",
                    "per": "hour",
                    "mechanism_input": {"profile": "default"},
                },
                "claimant_principal": _CLAIMANT,
            },
        )


async def test_option_builder_refuses_leaking_contact_into_the_option() -> None:
    registry = _registry()
    config = registry.resolve(
        _seller_raw(contact_payload={"telegram": "seller-signing-key"}),
        role="seller",
    )
    (readiness,) = await registry.ordered_readiness(config, role="seller")
    with pytest.raises(ValueError, match="must not reach a published option"):
        registry.build_option(
            readiness,
            config,
            role="seller",
            resources={
                # The listing's origin: the single form serves only its one site.
                "origin": "default",
                "publication_clause": {
                    "mechanism": "contact-exchange.v1",
                    "asset": "introduction",
                    "mechanism_input": {"profile": "default"},
                },
                "claimant_principal": _CLAIMANT,
            },
        )


def test_config_rejects_contact_leaked_into_published_profiles() -> None:
    with pytest.raises(ValueError, match="must not appear in published profiles"):
        ContactSettlementConfig.model_validate(
            {
                "enabled": True,
                "contact_payload": {"telegram": "@capacity_broker"},
                "profiles": {
                    "default": {
                        "channel": "telegram",
                        "terms": "Reach me at @capacity_broker anytime.",
                    }
                },
            }
        )


def test_publication_input_rejects_unoffered_profiles() -> None:
    registry = _registry()
    config = registry.resolve(_seller_raw(), role="seller")
    with pytest.raises(SettlementConfigurationError, match="invalid publication input"):
        registry.validate_publication_input(
            "contact-exchange.v1",
            {"profile": "unlisted"},
            config,
            role="seller",
        )


def test_buyer_compatibility_requires_a_rateless_introduction_option() -> None:
    section = ContactSettlementConfig.model_validate({"enabled": True})
    option = {
        "mechanism": "contact-exchange.v1",
        "asset": "introduction",
        "rates": [],
        "params": {},
    }
    assert contact_buyer_compatibility(section, option, {})
    assert not contact_buyer_compatibility(
        section,
        {**option, "rates": [{"field": "amount", "per": "hour", "value": "1"}]},
        {},
    )
    disabled = ContactSettlementConfig.model_validate({"enabled": False})
    assert not contact_buyer_compatibility(disabled, option, {})


def test_buyer_role_resolves_a_minimal_enabled_section() -> None:
    registry = _registry()
    config = registry.resolve(
        {"priority": ["contact-exchange.v1"], "contact": {"enabled": True}},
        role="buyer",
    )
    clients = registry.runtime_clients(config, role="buyer")
    assert isinstance(clients["contact-exchange.v1"], ContactExchangeClient)


def test_retention_defaults_to_thirty_days_with_an_hourly_sweep() -> None:
    config = _registry().resolve(_seller_raw(), role="seller")
    section = config.mechanism_config("contact")
    assert section.retention_seconds == 2_592_000
    assert section.retention_sweep_interval_seconds == 3600


@pytest.mark.parametrize("window", [5, "indefinite"])
def test_retention_accepts_a_positive_window_or_indefinite(window: Any) -> None:
    config = _registry().resolve(
        _seller_raw(retention_seconds=window), role="seller"
    )
    assert config.mechanism_config("contact").retention_seconds == window


@pytest.mark.parametrize(
    "overrides",
    [
        {"retention_seconds": 0},
        {"retention_seconds": -1},
        {"retention_seconds": "forever"},
        {"retention_seconds": True},
        {"retention_sweep_interval_seconds": 0},
    ],
)
def test_retention_refuses_a_zero_negative_or_unknown_window(
    overrides: dict[str, Any],
) -> None:
    with pytest.raises((SettlementConfigurationError, ValueError)):
        _registry().resolve(_seller_raw(**overrides), role="seller")


def test_retention_is_seller_configuration() -> None:
    raw = {
        "priority": ["contact-exchange.v1"],
        "contact": {"enabled": True, "retention_seconds": 60},
    }
    with pytest.raises(SettlementConfigurationError, match="does not apply to role"):
        _registry().resolve(raw, role="buyer")


def _origin_raw(**overrides: Any) -> dict[str, Any]:
    raw = _seller_raw(contact_payload={})
    raw["contact"]["origins"] = {
        "dc-west": {"contact_payload": {"email": "ops@west.example"}},
        "dc-east": {"contact_payload": {"email": "sales@east.example"}},
    }
    raw["contact"].update(overrides)
    return raw


def _clause() -> dict[str, Any]:
    return {
        "mechanism": "contact-exchange.v1",
        "asset": "introduction",
        "mechanism_input": {"profile": "default"},
    }


def test_both_contact_forms_are_refused() -> None:
    with pytest.raises(ValueError, match="not both"):
        ContactSettlementConfig.model_validate(
            {
                "contact_payload": {"email": "one@x.example"},
                "origins": {"a": {"contact_payload": {"email": "a@x.example"}}},
            }
        )


def test_an_origin_entry_requires_a_contact() -> None:
    with pytest.raises(ValueError):
        ContactSettlementConfig.model_validate({"origins": {"a": {"contact_payload": {}}}})


@pytest.mark.parametrize("key", ["", " padded", "x" * 129])
def test_origin_keys_are_bounded(key: str) -> None:
    with pytest.raises(ValueError, match="contact origins"):
        ContactSettlementConfig.model_validate(
            {"origins": {key: {"contact_payload": {"email": "a@x.example"}}}}
        )


def test_origin_count_is_bounded() -> None:
    origins = {
        f"site-{index}": {"contact_payload": {"email": "a@x.example"}}
        for index in range(257)
    }
    with pytest.raises(ValueError, match="at most 256"):
        ContactSettlementConfig.model_validate({"origins": origins})


def test_resolution_never_falls_back_to_another_origin() -> None:
    config = ContactSettlementConfig.model_validate(_origin_raw()["contact"])
    assert resolve_seller_contact(config, "dc-west") == {"email": "ops@west.example"}
    assert resolve_seller_contact(config, "dc-east") == {"email": "sales@east.example"}
    assert resolve_seller_contact(config, "dc-north") is None
    assert resolve_seller_contact(config, None) is None


def test_the_single_form_resolves_to_its_configured_value() -> None:
    config = ContactSettlementConfig.model_validate(_seller_raw()["contact"])
    assert resolve_seller_contact(config, "default") == {
        "telegram": "@capacity_broker",
        "email": "deals@x.example",
    }


def test_the_single_form_resolves_only_for_its_one_origin() -> None:
    config = ContactSettlementConfig.model_validate(_seller_raw()["contact"])
    assert resolve_seller_contact(config, "default", {"default"}) is not None
    # A listing with no origin, or one from a site this storefront does not
    # serve, never borrows the storefront's one contact.
    assert resolve_seller_contact(config, None, {"default"}) is None
    assert resolve_seller_contact(config, "elsewhere", {"default"}) is None


def test_a_stale_deal_from_a_site_no_longer_configured_resolves_nothing() -> None:
    """A deal accepted at ``old-site`` stays bound to it after the storefront is
    reconfigured to serve ``new-site``; the new site's contact is not its."""
    config = ContactSettlementConfig.model_validate(_seller_raw()["contact"])
    validate_contact_origins(config, {"new-site"})
    assert resolve_seller_contact(config, "old-site", {"new-site"}) is None


def test_keyed_contacts_need_an_origin() -> None:
    config = ContactSettlementConfig.model_validate(_origin_raw()["contact"])
    assert resolve_seller_contact(config, None) is None


def test_the_single_form_is_refused_for_several_origins() -> None:
    config = ContactSettlementConfig.model_validate(_seller_raw()["contact"])
    validate_contact_origins(config, {"default"})
    with pytest.raises(ValueError, match="dc-east, dc-west"):
        validate_contact_origins(config, {"dc-west", "dc-east"})


def test_a_keyed_contact_for_an_unknown_origin_is_refused() -> None:
    config = ContactSettlementConfig.model_validate(_origin_raw()["contact"])
    validate_contact_origins(config, {"dc-west", "dc-east", "dc-north"})
    with pytest.raises(ValueError, match="dc-east"):
        validate_contact_origins(config, {"dc-west"})


async def test_keyed_contacts_are_ready_even_when_an_origin_has_none() -> None:
    registry = _registry()
    config = registry.resolve(_origin_raw(), role="seller")
    (readiness,) = await registry.ordered_readiness(config, role="seller")
    assert readiness.ready
    projection = str(readiness.safe_projection())
    assert "west.example" not in projection and "dc-west" not in projection


async def test_publication_offers_contact_only_for_an_origin_that_has_one() -> None:
    registry = _registry()
    config = registry.resolve(_origin_raw(), role="seller")
    (readiness,) = await registry.ordered_readiness(config, role="seller")

    def build(**resources: Any) -> dict[str, Any]:
        return registry.build_option(
            readiness,
            config,
            role="seller",
            resources={"claimant_principal": _CLAIMANT, **resources},
        )

    assert len(build(publication_clause=_clause(), origin="dc-west")["settlement_options"]) == 1
    assert build(publication_clause=_clause(), origin="dc-north")["settlement_options"] == []
    with pytest.raises(ValueError, match="must supply the listing's origin"):
        build(publication_clause=_clause())


async def test_publication_without_a_clause_offers_no_introduction() -> None:
    registry = _registry()
    config = registry.resolve(_seller_raw(), role="seller")
    (readiness,) = await registry.ordered_readiness(config, role="seller")
    built = registry.build_option(
        readiness, config, role="seller", resources={"claimant_principal": _CLAIMANT}
    )
    assert built["settlement_options"] == []


def test_contact_fields_are_never_published_rather_than_secret() -> None:
    schema = ContactSettlementConfig.model_json_schema()
    single = schema["properties"]["contact_payload"]
    keyed = schema["$defs"]["ContactOrigin"]["properties"]["contact_payload"]
    for field in (single, keyed):
        assert field.get("never_published") is True
        assert "secret" not in field


async def test_publication_without_an_origin_offers_no_introduction() -> None:
    registry = _registry()
    config = registry.resolve(_seller_raw(), role="seller")
    (readiness,) = await registry.ordered_readiness(config, role="seller")
    built = registry.build_option(
        readiness,
        config,
        role="seller",
        resources={"claimant_principal": _CLAIMANT, "publication_clause": _clause()},
    )
    assert built["settlement_options"] == []
