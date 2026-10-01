"""Shared-registry settlement composition for the bare-metal storefront."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from core_storefront.publication_runner import PublicationPayload
from market_alkahest import create_alkahest_registration
from market_contact_exchange import create_contact_exchange_registration
from market_core.schemas import SettlementOption
from market_settlement_runtime import (
    MechanismReadiness,
    SettlementConfig,
    SettlementConfigurationRegistry,
    SettlementPublicationClause,
)

from .arkhai_payments import (
    ARKHAI_PAYMENTS_CONFIG_KEY,
    ARKHAI_PAYMENTS_MECHANISM,
    ArkhaiPaymentsConfig,
    BareMetalArkhaiPaymentsStage,
    create_arkhai_payments_registration,
)

ALKAHEST_MECHANISM = "alkahest.v1"


def build_bare_metal_settlement_registry() -> SettlementConfigurationRegistry:
    """Install the supported mechanisms through their shared facades."""

    return SettlementConfigurationRegistry(
        (
            create_alkahest_registration(),
            create_contact_exchange_registration(),
            create_arkhai_payments_registration(),
        )
    )


@dataclass(frozen=True, slots=True)
class BareMetalStorefrontSettlementComposition:
    """Typed seller composition for the supported settlement mechanisms."""

    registry: SettlementConfigurationRegistry
    config: SettlementConfig
    resources: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self.registry.validate(self.config, role="seller")
        object.__setattr__(self, "resources", MappingProxyType(dict(self.resources)))

    @classmethod
    def from_raw_config(
        cls,
        raw_settlement: Mapping[str, Any],
        *,
        resources: Mapping[str, Any] | None = None,
    ) -> "BareMetalStorefrontSettlementComposition":
        registry = build_bare_metal_settlement_registry()
        return cls(
            registry=registry,
            config=registry.resolve(raw_settlement, role="seller"),
            resources=resources or {},
        )

    @property
    def enabled_mechanisms(self) -> tuple[str, ...]:
        return self.config.priority

    def arkhai_payments_stage(self) -> BareMetalArkhaiPaymentsStage | None:
        section = self.config.mechanisms.get(ARKHAI_PAYMENTS_CONFIG_KEY)
        if section is None:
            return None
        config = ArkhaiPaymentsConfig.model_validate(section)
        if not config.enabled:
            return None
        return BareMetalArkhaiPaymentsStage(
            config=config,
            api_key=self.resources.get("arkhai_payments_api_key"),
            development_account=self.resources.get(
                "arkhai_payments_development_account"
            ),
        )

    def settlement_mandate_dispatch(
        self,
    ) -> dict[str, Callable[[Mapping[str, Any]], Mapping[str, Any]]]:
        stage = self.arkhai_payments_stage()
        if stage is None:
            return {}
        return {ARKHAI_PAYMENTS_MECHANISM: stage.mandate_for_agreement}

    async def readiness(
        self,
        *,
        clauses: Sequence[SettlementPublicationClause],
    ) -> tuple[MechanismReadiness, ...]:
        resources = {
            **self.resources,
            "publication_clauses": [
                item.model_dump(mode="json", exclude_none=True) for item in clauses
            ],
        }
        return await self.registry.ordered_readiness(
            self.config,
            role="seller",
            resources=resources,
        )

    async def publication_payload(
        self,
        *,
        candidate: Mapping[str, Any],
        clauses: Sequence[SettlementPublicationClause],
        demands: Sequence[Mapping[str, Any]] = (),
        max_duration_seconds: int | None = None,
    ) -> PublicationPayload:
        """Build ready settlement publication alternatives."""

        readiness = await self.readiness(clauses=clauses)
        readiness_by_mechanism = {item.mechanism: item for item in readiness}
        accepted_escrows: list[dict[str, Any]] = []
        settlement_options: list[dict[str, Any]] = []

        for clause in clauses:
            mechanism_readiness = readiness_by_mechanism.get(clause.mechanism)
            if mechanism_readiness is None or not mechanism_readiness.ready:
                continue
            artifacts = self.registry.build_option(
                mechanism_readiness,
                self.config,
                role="seller",
                resources={
                    **self.resources,
                    "publication_clause": clause,
                    "candidate": dict(candidate),
                },
            )
            if not isinstance(artifacts, Mapping):
                raise ValueError(
                    "settlement option builder returned an invalid artifact"
                )
            built_escrows = artifacts.get("accepted_escrows", ())
            built_options = artifacts.get("settlement_options", ())
            if not isinstance(built_escrows, (list, tuple)) or not isinstance(
                built_options, (list, tuple)
            ):
                raise ValueError("settlement option builder returned invalid carriers")
            accepted_escrows.extend(dict(item) for item in built_escrows)
            settlement_options.extend(
                SettlementOption.model_validate(item).model_dump(mode="json")
                for item in built_options
            )

        option_ids = [item["option_id"] for item in settlement_options]
        if len(option_ids) != len(set(option_ids)):
            raise ValueError(
                "publication produced duplicate settlement option identities"
            )

        return PublicationPayload(
            accepted_escrows=tuple(accepted_escrows),
            settlement_options=tuple(settlement_options),
            publication_clauses=tuple(
                item.model_dump(mode="json", exclude_none=True) for item in clauses
            ),
            demands=tuple(dict(item) for item in demands),
            max_duration_seconds=max_duration_seconds,
        )

    def runtime_clients(self) -> dict[str, Any]:
        """Build clients for configured conditional settlement mechanisms."""

        return self.registry.runtime_clients(
            self.config,
            role="seller",
            resources=self.resources,
        )

    def accepted_obligation_dispatch(
        self,
    ) -> dict[str, Callable[[Mapping[str, Any], Mapping[str, Any]], Any] | None]:
        """Curried registry dispatch for obligation-building mechanisms."""

        dispatch: dict[
            str, Callable[[Mapping[str, Any], Mapping[str, Any]], Any] | None
        ] = {}
        for mechanism_id in self.config.priority:
            registration = self.registry.registration(mechanism_id)
            if registration.accepted_obligation_builder is None:
                dispatch[mechanism_id] = None
                continue

            def build(
                option: Mapping[str, Any],
                context: Mapping[str, Any],
                *,
                _mechanism_id: str = mechanism_id,
            ) -> Any:
                return self.registry.build_accepted_obligation(
                    _mechanism_id,
                    option,
                    self.config,
                    role="seller",
                    context=context,
                )

            dispatch[mechanism_id] = build
        return dispatch
