from __future__ import annotations

from types import SimpleNamespace

import pytest
from market_settlement_runtime import (
    MechanismReadiness,
    MechanismRegistration,
    ReadinessBlocker,
    SettlementConfig,
    SettlementConfigurationRegistry,
    SettlementPublicationClause,
)
from pydantic import BaseModel, ConfigDict

from market_storefront.settlement_composition import VmSettlementComposition


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    enabled: bool = False


class _PublicationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chain: str | None = None


def _registration(
    mechanism: str,
    key: str,
    *,
    ready: bool,
    calls: list[str],
    required_chain: str | None = None,
) -> MechanismRegistration:
    async def preflight(section, resources, role):
        del role
        calls.append(f"preflight:{mechanism}")
        selected_chains = {
            item.get("chain_name")
            for item in resources.get("accepted_escrows", ())
            if isinstance(item, dict)
        }
        chain_ready = required_chain is None or required_chain in selected_chains
        is_ready = ready and chain_ready
        return MechanismReadiness(
            mechanism=mechanism,
            configured=True,
            enabled=section.enabled,
            ready=section.enabled and is_ready,
            blockers=()
            if is_ready
            else (ReadinessBlocker(code=f"{key}.unready", message="not ready"),),
        )

    def option_builder(section, readiness, resources, role):
        del section, readiness, role
        calls.append(f"option:{mechanism}")
        return {
            "accepted_escrows": list(resources.get(f"{key}_escrows", ())),
            "settlement_options": list(resources.get(f"{key}_options", ())),
        }

    return MechanismRegistration(
        mechanism_id=mechanism,
        config_key=key,
        config_model=_Section,
        roles=frozenset({"seller"}),
        preflight=preflight,
        client_factory=lambda section, resources, role: object(),
        option_builder=option_builder,
        buyer_compatibility=lambda section, option, context: False,
        clause_fields=(),
        publication_input_model=_PublicationInput,
        publication_input_validator=lambda section, value, role: value,
    )


def _composition(
    *,
    priority: tuple[str, ...],
    stripe_ready: bool,
    alkahest_ready: bool,
    stripe_enabled: bool = True,
    alkahest_enabled: bool = True,
):
    calls: list[str] = []
    registry = SettlementConfigurationRegistry(
        (
            _registration("alkahest.v1", "alkahest", ready=alkahest_ready, calls=calls),
            _registration("fiat.stripe.v1", "stripe", ready=stripe_ready, calls=calls),
        )
    )
    config = SettlementConfig(
        priority=priority,
        mechanisms={
            "alkahest": _Section(enabled=alkahest_enabled),
            "stripe": _Section(enabled=stripe_enabled),
        },
    )
    registry.validate(config, role="seller")
    return (
        SimpleNamespace(
            configuration_registry=registry,
            settlement_config=config,
            mechanism_resources={},
        ),
        calls,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("priority", "stripe_enabled", "alkahest_enabled", "expected"),
    [
        (("fiat.stripe.v1",), True, False, ["stripe"]),
        (("alkahest.v1",), False, True, ["alkahest"]),
        (("fiat.stripe.v1", "alkahest.v1"), True, True, ["stripe", "alkahest"]),
        (("alkahest.v1", "fiat.stripe.v1"), True, True, ["alkahest", "stripe"]),
    ],
)
async def test_ready_mechanisms_are_built_in_priority_order(
    priority, stripe_enabled, alkahest_enabled, expected
):
    composition, calls = _composition(
        priority=priority,
        stripe_ready=True,
        alkahest_ready=True,
        stripe_enabled=stripe_enabled,
        alkahest_enabled=alkahest_enabled,
    )
    resources = {
        "stripe_options": [{"mechanism": "fiat.stripe.v1"}],
        "alkahest_escrows": [{"mechanism": "alkahest.v1"}],
    }

    accepted, options, _statuses = await VmSettlementComposition.publication_artifacts(
        composition, resources
    )

    assert [
        value.split(":", 1)[1] for value in calls if value.startswith("option:")
    ] == ["fiat.stripe.v1" if item == "stripe" else "alkahest.v1" for item in expected]
    assert options == ([{"mechanism": "fiat.stripe.v1"}] if stripe_enabled else [])
    assert accepted == ([{"mechanism": "alkahest.v1"}] if alkahest_enabled else [])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stripe_ready", "alkahest_ready", "expected_options", "expected_escrows"),
    [
        (False, True, [], [{"mechanism": "alkahest.v1"}]),
        (True, False, [{"mechanism": "fiat.stripe.v1"}], []),
    ],
)
async def test_one_unready_mechanism_does_not_hide_ready_peer(
    stripe_ready, alkahest_ready, expected_options, expected_escrows
):
    composition, _calls = _composition(
        priority=("fiat.stripe.v1", "alkahest.v1"),
        stripe_ready=stripe_ready,
        alkahest_ready=alkahest_ready,
    )

    accepted, options, _statuses = await VmSettlementComposition.publication_artifacts(
        composition,
        {
            "stripe_options": [{"mechanism": "fiat.stripe.v1"}],
            "alkahest_escrows": [{"mechanism": "alkahest.v1"}],
        },
    )

    assert options == expected_options
    assert accepted == expected_escrows


@pytest.mark.asyncio
async def test_publication_fails_safely_when_none_are_ready():
    composition, _calls = _composition(
        priority=("fiat.stripe.v1", "alkahest.v1"),
        stripe_ready=False,
        alkahest_ready=False,
    )

    with pytest.raises(RuntimeError, match="no enabled settlement mechanism is ready"):
        await VmSettlementComposition.publication_artifacts(composition, {})


@pytest.mark.asyncio
async def test_explicit_clauses_build_only_requested_mechanisms_in_clause_order():
    composition, calls = _composition(
        priority=("alkahest.v1", "fiat.stripe.v1"),
        stripe_ready=True,
        alkahest_ready=True,
    )
    clauses = [
        SettlementPublicationClause(
            mechanism="fiat.stripe.v1",
            asset="usd",
            rate="2",
            per="hour",
        ),
        SettlementPublicationClause(
            mechanism="alkahest.v1",
            asset="0x" + "12" * 20,
            rate="2",
            per="hour",
        ),
    ]

    accepted, options, _statuses = await VmSettlementComposition.publication_artifacts(
        composition,
        {
            "stripe_options": [{"mechanism": "fiat.stripe.v1"}],
            "alkahest_escrows": [{"mechanism": "alkahest.v1"}],
        },
        clauses=clauses,
    )

    assert [value for value in calls if value.startswith("option:")] == [
        "option:fiat.stripe.v1",
        "option:alkahest.v1",
    ]
    assert options == [{"mechanism": "fiat.stripe.v1"}]
    assert accepted == [{"mechanism": "alkahest.v1"}]


@pytest.mark.asyncio
async def test_explicit_disabled_clause_is_rejected() -> None:
    composition, _calls = _composition(
        priority=("alkahest.v1",),
        stripe_ready=True,
        alkahest_ready=True,
        stripe_enabled=False,
        alkahest_enabled=True,
    )

    with pytest.raises(ValueError, match="disabled"):
        await VmSettlementComposition.publication_artifacts(
            composition,
            {},
            clauses=[
                SettlementPublicationClause(
                    mechanism="fiat.stripe.v1",
                    asset="usd",
                    rate="2",
                    per="hour",
                )
            ],
        )


@pytest.mark.asyncio
async def test_builder_validation_error_fails_the_listing(monkeypatch) -> None:
    composition, _calls = _composition(
        priority=("fiat.stripe.v1",),
        stripe_ready=True,
        alkahest_ready=False,
        alkahest_enabled=False,
    )
    monkeypatch.setattr(
        composition.configuration_registry,
        "build_option",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValueError("fractional base units")
        ),
    )

    with pytest.raises(ValueError, match="fractional base units"):
        await VmSettlementComposition.publication_artifacts(
            composition,
            {},
            clauses=[
                SettlementPublicationClause(
                    mechanism="fiat.stripe.v1",
                    asset="usd",
                    rate="2.001",
                    per="hour",
                )
            ],
        )


@pytest.mark.asyncio
async def test_clause_chain_is_available_during_alkahest_preflight() -> None:
    calls: list[str] = []
    registry = SettlementConfigurationRegistry(
        (
            _registration(
                "alkahest.v1",
                "alkahest",
                ready=True,
                calls=calls,
                required_chain="base_sepolia",
            ),
        )
    )
    config = SettlementConfig(
        priority=("alkahest.v1",),
        mechanisms={"alkahest": _Section(enabled=True)},
    )
    registry.validate(config, role="seller")
    composition = SimpleNamespace(
        configuration_registry=registry,
        settlement_config=config,
        mechanism_resources={},
    )

    accepted, _options, readiness = await VmSettlementComposition.publication_artifacts(
        composition,
        {"alkahest_escrows": [{"mechanism": "alkahest.v1"}]},
        clauses=[
            SettlementPublicationClause(
                mechanism="alkahest.v1",
                asset="0x" + "12" * 20,
                rate="2",
                per="hour",
                mechanism_input={"chain": "base_sepolia"},
            )
        ],
    )

    assert readiness[0].ready is True
    assert accepted == [{"mechanism": "alkahest.v1"}]
