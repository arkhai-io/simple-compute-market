"""Shared-registry settlement composition for the bare-metal storefront."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any

from arkhai_bare_metal import (
    BareMetalHostedPublicationPolicy,
    build_ready_bare_metal_hosted_options,
)
from core_storefront.publication_runner import PublicationPayload
from market_alkahest import create_alkahest_registration
from market_core.schemas import SettlementOption
from market_hosted_settlement import (
    StripeSettlementConfig,
    create_stripe_registration,
)
from market_settlement_runtime import (
    MechanismReadiness,
    SettlementConfig,
    SettlementConfigurationRegistry,
    SettlementPublicationClause,
)

HOSTED_MECHANISM = "fiat.stripe.v1"
ALKAHEST_MECHANISM = "alkahest.v1"


def build_bare_metal_settlement_registry() -> SettlementConfigurationRegistry:
    """Install the two supported mechanisms through their shared facades."""

    return SettlementConfigurationRegistry(
        (create_alkahest_registration(), create_stripe_registration())
    )


@dataclass(frozen=True, slots=True)
class BareMetalStorefrontSettlementComposition:
    """One typed seller composition with no domain-local hosted transport."""

    registry: SettlementConfigurationRegistry
    config: SettlementConfig
    resources: Mapping[str, Any] = field(default_factory=dict, repr=False)
    publication_policy: BareMetalHostedPublicationPolicy = field(
        default_factory=BareMetalHostedPublicationPolicy
    )

    def __post_init__(self) -> None:
        self.registry.validate(self.config, role="seller")
        object.__setattr__(self, "resources", MappingProxyType(dict(self.resources)))

    @classmethod
    def from_raw_config(
        cls,
        raw_settlement: Mapping[str, Any],
        *,
        resources: Mapping[str, Any] | None = None,
        publication_policy: BareMetalHostedPublicationPolicy | None = None,
    ) -> "BareMetalStorefrontSettlementComposition":
        registry = build_bare_metal_settlement_registry()
        return cls(
            registry=registry,
            config=registry.resolve(raw_settlement, role="seller"),
            resources=resources or {},
            publication_policy=publication_policy or BareMetalHostedPublicationPolicy(),
        )

    @property
    def enabled_mechanisms(self) -> tuple[str, ...]:
        return self.config.priority

    @property
    def hosted_only(self) -> bool:
        return self.config.priority == (HOSTED_MECHANISM,)

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
        offer_expires_at: datetime,
        funding_deadlines: Mapping[str, datetime],
        fulfillment_deadline: datetime,
        demands: Sequence[Mapping[str, Any]] = (),
        max_duration_seconds: int | None = None,
        now: datetime | None = None,
    ) -> PublicationPayload:
        """Build independent Alkahest and profile-exact hosted alternatives."""

        readiness = await self.readiness(clauses=clauses)
        readiness_by_mechanism = {item.mechanism: item for item in readiness}
        accepted_escrows: list[dict[str, Any]] = []
        settlement_options: list[dict[str, Any]] = []
        hosted_bases: list[SettlementOption] = []

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
            if clause.mechanism == HOSTED_MECHANISM:
                hosted_bases.extend(
                    SettlementOption.model_validate(item) for item in built_options
                )
            else:
                settlement_options.extend(
                    SettlementOption.model_validate(item).model_dump(mode="json")
                    for item in built_options
                )

        hosted = build_ready_bare_metal_hosted_options(
            candidate=candidate,
            base_hosted_options=hosted_bases,
            policy=self.publication_policy,
            offer_expires_at=offer_expires_at,
            funding_deadlines=funding_deadlines,
            fulfillment_deadline=fulfillment_deadline,
            now=now,
        )
        settlement_options.extend(
            option.model_dump(mode="json") for option in hosted.settlement_options
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
        """Build clients only for configured mechanisms; hosted-only needs no chain."""

        return self.registry.runtime_clients(
            self.config,
            role="seller",
            resources=self.resources,
        )

    def accepted_obligation_dispatch(
        self,
    ) -> dict[str, Callable[[Mapping[str, Any], Mapping[str, Any]], Any]]:
        """Curried registry dispatch for every enabled obligation-building mechanism."""

        dispatch: dict[str, Callable[[Mapping[str, Any], Mapping[str, Any]], Any]] = {}
        for mechanism_id in self.config.priority:
            registration = self.registry.registration(mechanism_id)
            if registration.accepted_obligation_builder is None:
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


def default_hosted_selection_dispatch() -> dict[
    str, Callable[[Mapping[str, Any], Mapping[str, Any]], Any]
]:
    """Hosted-only dispatch for runtimes composed without settlement config.

    Selection acceptance works from listing data alone, so a legacy
    deployment keeps accepting hosted selections exactly as before; the
    validation-only section carries no deployment state.
    """

    registry = SettlementConfigurationRegistry((create_stripe_registration(),))
    config = SettlementConfig(mechanisms={"stripe": StripeSettlementConfig()})

    def build(option: Mapping[str, Any], context: Mapping[str, Any]) -> Any:
        return registry.build_accepted_obligation(
            HOSTED_MECHANISM,
            option,
            config,
            role="seller",
            context=context,
        )

    return {HOSTED_MECHANISM: build}


__all__ = [
    "ALKAHEST_MECHANISM",
    "HOSTED_MECHANISM",
    "BareMetalStorefrontSettlementComposition",
    "build_bare_metal_settlement_registry",
    "default_hosted_selection_dispatch",
]
