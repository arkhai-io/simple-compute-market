from __future__ import annotations

from typing import Any

from core_buyer.settlement import BuyerSettlementPolicy
from market_core.schemas import SettlementOption, derive_settlement_option_id
from market_settlement_runtime import (
    ComparisonOperator,
    FieldDescriptor,
    MechanismReadiness,
    MechanismRegistration,
    QueryValueType,
    SettlementClauseField,
    SettlementConfig,
    SettlementConfigurationRegistry,
)
from pydantic import BaseModel, ConfigDict


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = False


class _PublicationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    profile: str = ""


def _option(mechanism: str, asset: str) -> SettlementOption:
    params: dict[str, Any] = {"profile": asset}
    return SettlementOption(
        option_id=derive_settlement_option_id(
            mechanism=mechanism,
            asset=asset,
            rates=[],
            params=params,
        ),
        mechanism=mechanism,
        asset=asset,
        params=params,
    )


def _registration(
    mechanism: str,
    key: str,
    *,
    compatible: bool = True,
    compatibility_calls: list[str] | None = None,
) -> MechanismRegistration:
    def buyer_compatibility(section, option, public_context):
        assert section.enabled is True
        assert public_context == {"currency": "usd"}
        if compatibility_calls is not None:
            compatibility_calls.append(mechanism)
        return compatible and option.mechanism == mechanism

    return MechanismRegistration(
        mechanism_id=mechanism,
        config_key=key,
        config_model=_Section,
        roles=frozenset({"buyer"}),
        preflight=lambda section, resources, role: MechanismReadiness(
            mechanism=mechanism,
            configured=True,
            enabled=section.enabled,
            ready=section.enabled,
        ),
        client_factory=lambda section, resources, role: object(),
        option_builder=lambda section, readiness, resources, role: (),
        buyer_compatibility=buyer_compatibility,
        clause_fields=(
            SettlementClauseField(
                descriptor=FieldDescriptor(
                    name=f"{key}.profile",
                    value_type=QueryValueType.STRING,
                    operators=frozenset({ComparisonOperator.EQUAL}),
                ),
                roles=frozenset({"buyer"}),
                projector=lambda option: option.params.get("profile"),
            ),
        ),
        publication_input_model=_PublicationInput,
        publication_input_validator=lambda section, value, role: value,
    )


def _policy(
    priority: tuple[str, ...],
    *,
    hosted_compatible: bool = True,
    calls: list[str] | None = None,
) -> BuyerSettlementPolicy:
    registry = SettlementConfigurationRegistry()
    registry.register(
        _registration(
            "fiat.stripe.v1",
            "stripe",
            compatible=hosted_compatible,
            compatibility_calls=calls,
        )
    )
    registry.register(
        _registration(
            "alkahest.v1",
            "alkahest",
            compatibility_calls=calls,
        )
    )
    config = SettlementConfig(
        priority=priority,
        mechanisms={
            "stripe": _Section(enabled="fiat.stripe.v1" in priority),
            "alkahest": _Section(enabled="alkahest.v1" in priority),
        },
    )
    return BuyerSettlementPolicy(
        config=config,
        registry=registry,
        public_context={"currency": "usd"},
    )


def test_hosted_first_policy_orders_before_alkahest() -> None:
    hosted = _option("fiat.stripe.v1", "usd")
    alkahest = _option("alkahest.v1", "usdc")

    selected = _policy(("fiat.stripe.v1", "alkahest.v1")).select(
        {"settlement_options": [alkahest.model_dump(), hosted.model_dump()]},
        expiration_unix=2_000_000_000,
    )

    assert selected is not None
    assert selected.selection.mechanism == "fiat.stripe.v1"
    assert selected.option == hosted


def test_alkahest_first_policy_orders_before_hosted() -> None:
    hosted = _option("fiat.stripe.v1", "usd")
    alkahest = _option("alkahest.v1", "usdc")

    selected = _policy(("alkahest.v1", "fiat.stripe.v1")).select(
        {"settlement_options": [hosted.model_dump(), alkahest.model_dump()]},
        expiration_unix=2_000_000_000,
    )

    assert selected is not None
    assert selected.selection.mechanism == "alkahest.v1"


def test_incompatible_preferred_mechanism_advances_before_acceptance() -> None:
    calls: list[str] = []
    hosted = _option("fiat.stripe.v1", "usd")
    alkahest = _option("alkahest.v1", "usdc")

    selected = _policy(
        ("fiat.stripe.v1", "alkahest.v1"),
        hosted_compatible=False,
        calls=calls,
    ).select(
        {"settlement_options": [hosted.model_dump(), alkahest.model_dump()]},
        expiration_unix=2_000_000_000,
    )

    assert selected is not None
    assert selected.selection.mechanism == "alkahest.v1"
    assert calls == ["fiat.stripe.v1", "alkahest.v1"]


def test_policy_compatibility_never_receives_wallet_or_chain_resources() -> None:
    calls: list[str] = []
    hosted = _option("fiat.stripe.v1", "usd")

    selected = _policy(("fiat.stripe.v1",), calls=calls).select(
        {"settlement_options": [hosted.model_dump()]},
        expiration_unix=2_000_000_000,
    )

    assert selected is not None
    assert calls == ["fiat.stripe.v1"]


def test_run_metadata_contains_only_public_schema_set_and_fingerprint() -> None:
    metadata = _policy(("fiat.stripe.v1",)).public_run_metadata()

    assert metadata["settlement_config_schema_version"] == 1
    assert metadata["settlement_public_mechanisms"] == ["fiat.stripe.v1"]
    assert metadata["settlement_public_fingerprint"].startswith("sha256:")
    assert set(metadata) == {
        "settlement_config_schema_version",
        "settlement_public_mechanisms",
        "settlement_public_fingerprint",
    }


def test_ordered_clauses_apply_across_listings_before_mechanism_priority() -> None:
    hosted = _option("fiat.stripe.v1", "usd")
    alkahest = _option("alkahest.v1", "usdc")
    policy = _policy(("fiat.stripe.v1", "alkahest.v1"))
    clauses = policy.compile_clauses(
        (
            "mechanism=alkahest alkahest.profile=usdc",
            "mechanism=stripe stripe.profile=usd",
        )
    )

    selected = policy.select_listings(
        (
            {"listing_id": "stripe", "settlement_options": [hosted.model_dump()]},
            {"listing_id": "alkahest", "settlement_options": [alkahest.model_dump()]},
        ),
        expiration_unix=2_000_000_000,
        clauses=clauses,
    )

    assert [
        (listing["listing_id"], choice.clause_index) for listing, choice in selected
    ] == [("alkahest", 0)]


def test_clause_survivors_use_mechanism_priority_then_option_identity() -> None:
    hosted = _option("fiat.stripe.v1", "usd")
    alkahest = _option("alkahest.v1", "usd")
    policy = _policy(("fiat.stripe.v1", "alkahest.v1"))

    selected = policy.select_listings(
        (
            {"listing_id": "alkahest", "settlement_options": [alkahest.model_dump()]},
            {"listing_id": "stripe", "settlement_options": [hosted.model_dump()]},
        ),
        expiration_unix=2_000_000_000,
        clauses=("asset=usd",),
    )

    assert [listing["listing_id"] for listing, _ in selected] == ["stripe"]


def test_explanation_reports_ordered_public_survivors_and_rejections() -> None:
    hosted = _option("fiat.stripe.v1", "usd")
    policy = _policy(("fiat.stripe.v1", "alkahest.v1"))

    explanation = policy.explain_listings(
        (
            {"listing_id": "hosted", "settlement_options": [hosted.model_dump()]},
            {"listing_id": "empty", "settlement_options": []},
        ),
        expiration_unix=2_000_000_000,
        clauses=(
            "mechanism=alkahest asset=usdc",
            "mechanism=stripe asset=usd",
        ),
    ).to_dict()

    assert explanation["resource_listing_count"] == 2
    assert explanation["installed_enabled_compatibility"] == {
        "listing_count": 1,
        "option_count": 1,
    }
    assert explanation["clause_survivors"] == [
        {
            "index": 0,
            "clause": "mechanism=alkahest.v1 asset=usdc",
            "listing_count": 0,
            "option_count": 0,
        },
        {
            "index": 1,
            "clause": "mechanism=fiat.stripe.v1 asset=usd",
            "listing_count": 1,
            "option_count": 1,
        },
    ]
    assert explanation["winning_clause_index"] == 1
    assert explanation["policy_ordering"] == {
        "mechanism": "fiat.stripe.v1",
        "listing_count": 1,
    }
    assert explanation["selected_option_id"] == hosted.option_id
    assert explanation["rejection_categories"] == {
        "asset_mismatch": 1,
        "clause_mismatch": 1,
        "installed_enabled_incompatible": 0,
        "mechanism_mismatch": 1,
        "no_settlement_options": 1,
    }
