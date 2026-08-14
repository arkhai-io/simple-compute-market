from __future__ import annotations
import json
import tomllib
import inspect
from dataclasses import replace
from collections.abc import Mapping
from typing import Any, cast

import market_settlement_runtime as settlement_runtime
import pytest
from market_settlement_runtime import (
    ComparisonOperator,
    FieldDescriptor,
    MechanismReadiness,
    MechanismRegistration,
    ReadinessBlocker,
    QueryValueType,
    SettlementConfig,
    SettlementConfigurationError,
    SettlementConfigurationRegistry,
    SettlementClauseField,
    SettlementPublicationClause,
    compile_settlement_publication_clause,
)
from market_settlement_runtime.ports import ConditionalEscrowClient
from pydantic import BaseModel, ConfigDict, Field, SecretStr


class ProfileSettings(BaseModel):
    condition: str


class DemoSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    label: str = ""
    profiles: dict[str, ProfileSettings] = Field(default_factory=dict)
    request_secret: SecretStr | None = Field(
        default=None, json_schema_extra={"secret": True}
    )
    seller_note: str | None = Field(
        default=None, json_schema_extra={"roles": ["seller"]}
    )


class OtherSettings(BaseModel):
    enabled: bool = False


class PublicationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    profile: str = "standard"


class SecretPublicationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_secret: str = ""


def _registration(
    mechanism_id: str = "demo.pay.v1",
    config_key: str = "demo",
    *,
    roles: frozenset[str] = frozenset({"buyer", "seller"}),
    events: list[str] | None = None,
    leak_secret: bool = False,
) -> MechanismRegistration:
    observed = events if events is not None else []

    async def preflight(
        config: BaseModel, resources: Mapping[str, Any], role: str
    ) -> MechanismReadiness:
        observed.append(f"preflight:{role}")
        message = (
            cast(DemoSettings, config).request_secret.get_secret_value()
            if leak_secret and cast(DemoSettings, config).request_secret is not None
            else "configured public trust is unavailable"
        )
        return MechanismReadiness(
            mechanism=mechanism_id,
            configured=True,
            enabled=True,
            ready=not leak_secret,
            blockers=()
            if not leak_secret
            else (ReadinessBlocker(code="not_ready", message=message),),
            capabilities=("conditional",),
            contract_version="1",
            schema_version="1",
            public_details={"network": "test"},
        )

    def client_factory(
        config: BaseModel, resources: Mapping[str, Any], role: str
    ) -> ConditionalEscrowClient:
        observed.append(f"factory:{role}")
        return cast(ConditionalEscrowClient, object())

    def option_builder(
        config: BaseModel,
        readiness: MechanismReadiness,
        resources: Mapping[str, Any],
        role: str,
    ) -> dict[str, str]:
        observed.append(f"option:{role}")
        return {"mechanism": mechanism_id}

    def buyer_compatibility(
        config: BaseModel, option: Any, public_context: Mapping[str, Any]
    ) -> bool:
        observed.append("compatibility")
        return isinstance(option, Mapping) and option.get("mechanism") == mechanism_id

    return MechanismRegistration(
        mechanism_id=mechanism_id,
        config_key=config_key,
        config_model=DemoSettings if config_key == "demo" else OtherSettings,
        roles=cast(Any, roles),
        preflight=preflight,
        client_factory=client_factory,
        option_builder=option_builder,
        buyer_compatibility=buyer_compatibility,
        clause_fields=(
            SettlementClauseField(
                descriptor=FieldDescriptor(
                    name=f"{config_key}.profile",
                    value_type=QueryValueType.STRING,
                    operators=frozenset({ComparisonOperator.EQUAL}),
                ),
                roles=cast(Any, roles),
                projector=lambda option: option.params.get("profile"),
            ),
        ),
        publication_input_model=PublicationSettings,
        publication_input_validator=lambda section, value, role: value,
        public_detail_keys=frozenset({"network"}),
    )


def test_public_contract_exports_only_the_existing_runtime() -> None:
    assert settlement_runtime.SettlementConfig is SettlementConfig
    assert settlement_runtime.SETTLEMENT_CONFIG_SCHEMA_VERSION == 1
    runtime_types = {
        name
        for name, value in inspect.getmembers(settlement_runtime, inspect.isclass)
        if name.endswith("Runtime")
    }
    assert runtime_types == {"SettlementRuntime"}


def test_registration_and_priority_fail_deterministically() -> None:
    registration = _registration()
    registry = SettlementConfigurationRegistry([registration])

    with pytest.raises(
        SettlementConfigurationError, match="duplicate settlement registration"
    ):
        registry.register(registration)
    with pytest.raises(
        SettlementConfigurationError, match=r"duplicate Settlement\.priority"
    ):
        registry.resolve(
            {
                "priority": ["demo.pay.v1", "demo.pay.v1"],
                "demo": {"enabled": True},
            },
            role="buyer",
        )
    with pytest.raises(
        SettlementConfigurationError,
        match=r"uninstalled settlement mechanism 'ghost\.pay\.v1'",
    ):
        registry.resolve(
            {"priority": ["ghost.pay.v1"], "demo": {"enabled": False}},
            role="buyer",
        )
    with pytest.raises(
        SettlementConfigurationError, match=r"unknown Settlement keys: ghost"
    ):
        registry.resolve({"priority": [], "ghost": {}}, role="buyer")
    with pytest.raises(SettlementConfigurationError, match="has no configured section"):
        registry.resolve({"priority": ["demo.pay.v1"]}, role="buyer")
    with pytest.raises(
        SettlementConfigurationError, match="enabled mechanisms missing"
    ):
        registry.resolve({"priority": [], "demo": {"enabled": True}}, role="buyer")


def test_registration_rejects_unqualified_duplicate_and_sensitive_fields() -> None:
    base = _registration()

    def clause(name: str) -> SettlementClauseField:
        return SettlementClauseField(
            descriptor=FieldDescriptor(
                name=name,
                value_type=QueryValueType.STRING,
                operators=frozenset({ComparisonOperator.EQUAL}),
            ),
            roles=frozenset({"buyer"}),
            projector=lambda option: option.asset,
        )

    with pytest.raises(SettlementConfigurationError, match="must use"):
        replace(base, clause_fields=(clause("profile"),))
    with pytest.raises(SettlementConfigurationError, match="sensitive"):
        replace(base, clause_fields=(clause("demo.provider_secret"),))
    with pytest.raises(SettlementConfigurationError, match="duplicate"):
        replace(
            base,
            clause_fields=(
                clause("demo.first"),
                clause("demo.first"),
            ),
        )
    with pytest.raises(SettlementConfigurationError, match="publication input fields"):
        replace(base, publication_input_model=SecretPublicationSettings)


def test_role_and_nested_unknown_fields_are_rejected() -> None:
    seller_registry = SettlementConfigurationRegistry(
        [_registration(roles=frozenset({"seller"}))]
    )
    with pytest.raises(
        SettlementConfigurationError, match="does not apply to role 'buyer'"
    ):
        seller_registry.resolve(
            {"priority": ["demo.pay.v1"], "demo": {"enabled": True}},
            role="buyer",
        )

    registry = SettlementConfigurationRegistry([_registration()])
    with pytest.raises(
        SettlementConfigurationError, match="seller_note does not apply"
    ):
        registry.resolve(
            {
                "priority": ["demo.pay.v1"],
                "demo": {"enabled": True, "seller_note": "private seller setting"},
            },
            role="buyer",
        )
    with pytest.raises(
        SettlementConfigurationError, match=r"unknown Settlement\.demo keys"
    ):
        registry.resolve(
            {"priority": ["demo.pay.v1"], "demo": {"enabled": True, "typo": 1}},
            role="seller",
        )
    resolved = registry.resolve(
        {
            "priority": ["demo.pay.v1"],
            "demo": {
                "enabled": True,
                "profiles": {"standard": {"condition": "fulfilled"}},
            },
        },
        role="seller",
    )
    assert (
        cast(DemoSettings, resolved.mechanism_config("demo"))
        .profiles["standard"]
        .condition
        == "fulfilled"
    )
    with pytest.raises(
        SettlementConfigurationError,
        match=r"unknown Settlement\.demo\.profiles\.standard keys",
    ):
        registry.resolve(
            {
                "priority": ["demo.pay.v1"],
                "demo": {
                    "enabled": True,
                    "profiles": {"standard": {"condition": "ok", "typo": True}},
                },
            },
            role="seller",
        )


@pytest.mark.asyncio
async def test_readiness_is_ordered_and_observational() -> None:
    events: list[str] = []
    demo = _registration(events=events)
    other = _registration("other.pay.v1", "other", events=events)
    registry = SettlementConfigurationRegistry([other, demo])
    config = registry.resolve(
        {"priority": ["demo.pay.v1"], "demo": {"enabled": True}},
        role="seller",
    )

    statuses = await registry.ordered_readiness(config, role="seller")

    assert [status.mechanism for status in statuses] == ["demo.pay.v1", "other.pay.v1"]
    assert statuses[0].ready is True
    assert statuses[1].blockers[0].code == "not_configured"
    assert events == ["preflight:seller"]


def test_public_fingerprint_is_source_free_and_secret_free() -> None:
    registry = SettlementConfigurationRegistry([_registration()])
    secret = "top-secret-request-value"
    config = registry.resolve(
        {
            "priority": ["demo.pay.v1"],
            "demo": {"enabled": True, "label": "public", "request_secret": secret},
        },
        role="seller",
    )

    projection = registry.public_projection(config, role="seller")
    fingerprint = registry.public_fingerprint(config, role="seller")

    assert secret not in repr(projection)
    assert "source" not in repr(projection).lower()
    assert fingerprint.startswith("sha256:")
    assert secret not in fingerprint
    assert projection["mechanisms"][0]["clause_fields"][0]["name"] == "demo.profile"
    assert (
        projection["mechanisms"][0]["publication_input_schema"]["properties"][
            "profile"
        ]["type"]
        == "string"
    )


def test_publication_input_is_strictly_typed_and_role_scoped() -> None:
    registry = SettlementConfigurationRegistry([_registration()])
    config = registry.resolve(
        {"priority": ["demo.pay.v1"], "demo": {"enabled": True}},
        role="seller",
    )

    value = registry.validate_publication_input(
        "demo.pay.v1",
        {"profile": "premium"},
        config,
        role="seller",
    )

    assert value == PublicationSettings(profile="premium")
    with pytest.raises(SettlementConfigurationError, match="invalid publication input"):
        registry.validate_publication_input(
            "demo.pay.v1",
            {"profile": "premium", "provider_secret": "canary"},
            config,
            role="seller",
        )


def test_publication_clause_compiles_dsl_and_round_trips_structured_data() -> None:
    registry = SettlementConfigurationRegistry([_registration()])
    config = registry.resolve(
        {"priority": ["demo.pay.v1"], "demo": {"enabled": True}},
        role="seller",
    )

    clause = compile_settlement_publication_clause(
        "mechanism=demo asset=usd rate=2.50/hour "
        "public.condition=delivered demo.profile=premium",
        registry=registry,
        config=config,
        role="seller",
    )

    assert clause == SettlementPublicationClause(
        mechanism="demo.pay.v1",
        asset="usd",
        rate="2.50",
        per="hour",
        public={"condition": "delivered"},
        mechanism_input={"profile": "premium"},
    )
    encoded = json.dumps(clause.model_dump(mode="json"))
    assert (
        compile_settlement_publication_clause(
            json.loads(encoded),
            registry=registry,
            config=config,
            role="seller",
        )
        == clause
    )

    toml_payload = tomllib.loads(
        """
[[settlements]]
mechanism = "demo.pay.v1"
asset = "usd"
rate = "2.50"
per = "hour"

[settlements.public]
condition = "delivered"

[settlements.mechanism_input]
profile = "premium"
"""
    )
    assert (
        compile_settlement_publication_clause(
            toml_payload["settlements"][0],
            registry=registry,
            config=config,
            role="seller",
        )
        == clause
    )


@pytest.mark.parametrize(
    "payload, message",
    [
        (
            {
                "mechanism": "demo.pay.v1",
                "asset": "usd",
                "rate": 2.5,
                "per": "hour",
            },
            "binary floating-point",
        ),
        (
            {
                "mechanism": "demo.pay.v1",
                "asset": "usd",
                "rate": "2",
                "per": "hour",
                "unknown": True,
            },
            "Extra inputs",
        ),
        (
            {
                "mechanism": "demo.pay.v1",
                "asset": "usd",
                "rate": "2",
                "per": "hour",
                "public": {"ratio": 0.5},
            },
            "binary floating-point",
        ),
    ],
)
def test_publication_clause_rejects_unknown_fields_and_binary_floats(
    payload: dict[str, Any],
    message: str,
) -> None:
    registry = SettlementConfigurationRegistry([_registration()])
    config = registry.resolve(
        {"priority": ["demo.pay.v1"], "demo": {"enabled": True}},
        role="seller",
    )

    with pytest.raises(SettlementConfigurationError, match=message):
        compile_settlement_publication_clause(
            payload,
            registry=registry,
            config=config,
            role="seller",
        )


def test_publication_clause_rejects_unknown_or_unqualified_mechanism_fields() -> None:
    registry = SettlementConfigurationRegistry([_registration()])
    config = registry.resolve(
        {"priority": ["demo.pay.v1"], "demo": {"enabled": True}},
        role="seller",
    )

    with pytest.raises(SettlementConfigurationError, match="unknown"):
        compile_settlement_publication_clause(
            "mechanism=demo asset=usd rate=2/hour profile=premium",
            registry=registry,
            config=config,
            role="seller",
        )
    with pytest.raises(SettlementConfigurationError, match="invalid publication input"):
        compile_settlement_publication_clause(
            {
                "mechanism": "demo.pay.v1",
                "asset": "usd",
                "rate": "2",
                "per": "hour",
                "mechanism_input": {"typo": "premium"},
            },
            registry=registry,
            config=config,
            role="seller",
        )


@pytest.mark.asyncio
async def test_preflight_secret_leak_is_rejected() -> None:
    registry = SettlementConfigurationRegistry([_registration(leak_secret=True)])
    config = registry.resolve(
        {
            "priority": ["demo.pay.v1"],
            "demo": {"enabled": True, "request_secret": "must-not-escape"},
        },
        role="seller",
    )

    with pytest.raises(SettlementConfigurationError, match="exposed a secret value"):
        await registry.ordered_readiness(config, role="seller")


def test_client_dispatch_ignores_current_enablement_for_recovery() -> None:
    events: list[str] = []
    registry = SettlementConfigurationRegistry([_registration(events=events)])
    config = registry.resolve(
        {"priority": [], "demo": {"enabled": False, "label": "recovery"}},
        role="buyer",
    )

    registry.create_client("demo.pay.v1", config, role="buyer")

    assert events == ["factory:buyer"]
