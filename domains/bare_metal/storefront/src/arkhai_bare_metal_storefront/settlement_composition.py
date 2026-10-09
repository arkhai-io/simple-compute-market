"""Shared-registry settlement composition for the bare-metal storefront."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from core_storefront.publication_runner import PublicationPayload
from market_core import SettlementStageTable
from market_core.schemas import SettlementOption
from .alkahest_lifecycle import alkahest_servicing
from .settlement_stages import (
    ALKAHEST_MECHANISM,
    ContactStage,
    PaymentStage,
    SellerStage,
    declined_servicing,
    refund_payment,
    revalidate_alkahest,
    revalidate_contact,
    revalidate_payment,
    settle_payment,
    verify_alkahest,
    verify_contact,
    verify_payment,
)
from market_alkahest import create_alkahest_registration
from market_contact_exchange import (
    MECHANISM as CONTACT_MECHANISM,
    create_contact_exchange_registration,
)
from market_settlement_runtime import (
    MechanismReadiness,
    SettlementConfig,
    SettlementConfigurationRegistry,
    SettlementPublicationClause,
)

from market_arkhai_payments import (
    ARKHAI_PAYMENTS_CONFIG_KEY,
    ARKHAI_PAYMENTS_MECHANISM,
    ClientForOwner,
    PaymentSellerStage,
    create_arkhai_payments_registration,
    servicing_stage,
)

SELLER_STAGES = SettlementStageTable(
    {
        ALKAHEST_MECHANISM: SellerStage(
            create_alkahest_registration,
            verify_alkahest,
            revalidate_alkahest,
            True,
            servicing=alkahest_servicing,
        ),
        ARKHAI_PAYMENTS_MECHANISM: PaymentStage(
            create_arkhai_payments_registration,
            verify_payment,
            revalidate_payment,
            True,
            refund=refund_payment,
            reconcile=settle_payment,
        ),
        CONTACT_MECHANISM: ContactStage(
            create_contact_exchange_registration,
            verify_contact,
            revalidate_contact,
            False,
            servicing=declined_servicing,
        ),
    }
)

def build_bare_metal_settlement_registry() -> SettlementConfigurationRegistry:
    """Install the supported mechanisms through their shared facades."""

    return SettlementConfigurationRegistry(
        tuple(stage.registration_factory() for stage in SELLER_STAGES.values())
    )


@dataclass(frozen=True, slots=True)
class BareMetalStorefrontSettlementComposition:
    """Typed seller composition for the supported settlement mechanisms."""

    registry: SettlementConfigurationRegistry
    config: SettlementConfig
    resources: Mapping[str, Any] = field(default_factory=dict, repr=False)
    payments_client_for_owner: ClientForOwner | None = field(default=None, repr=False)
    payments_stage: PaymentSellerStage | None = field(default=None, init=False, repr=False)

    seller_stages: SettlementStageTable[Any] = SELLER_STAGES

    def __post_init__(self) -> None:
        if any(
            mechanism not in self.seller_stages for mechanism in self.config.priority
        ):
            raise ValueError("enabled settlement mechanism has no seller stage")
        self.registry.validate(self.config, role="seller")
        object.__setattr__(self, "resources", MappingProxyType(dict(self.resources)))
        # Accepted payment deals are serviced whether or not new payment options
        # are published, so the stage follows the servicing fields, not `enabled`.
        stage = servicing_stage(
            self.config.mechanisms.get(ARKHAI_PAYMENTS_CONFIG_KEY),
            client_for_owner=self.payments_client_for_owner,
        )
        object.__setattr__(self, "payments_stage", stage)

    @classmethod
    def from_raw_config(
        cls,
        raw_settlement: Mapping[str, Any],
        *,
        resources: Mapping[str, Any] | None = None,
        payments_client_for_owner: ClientForOwner | None = None,
    ) -> "BareMetalStorefrontSettlementComposition":
        registry = build_bare_metal_settlement_registry()
        return cls(
            registry=registry,
            config=registry.resolve(raw_settlement, role="seller"),
            resources=resources or {},
            payments_client_for_owner=payments_client_for_owner,
        )

    @property
    def enabled_mechanisms(self) -> tuple[str, ...]:
        return self.config.priority

    def arkhai_payments_stage(self) -> PaymentSellerStage | None:
        return self.payments_stage

    def settlement_data_dispatch(
        self,
    ) -> dict[str, Callable[[Mapping[str, Any]], Mapping[str, Any] | None]]:
        payment_stage = self.payments_stage
        return {
            mechanism: lambda agreement, entry=entry: entry.accepted_data(
                agreement, payment_stage
            )
            for mechanism, entry in self.seller_stages.items()
        }

    def configures(self, mechanism_id: str) -> bool:
        """Whether the settlement root has a section for ``mechanism_id``.

        A configured section may be disabled for new deals and still owns the
        obligations accepted while it was enabled, so whatever services them
        is built for every configured section, not only the enabled ones.
        """

        config_key = self.registry.registration(mechanism_id).config_key
        return config_key in self.config.mechanisms

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
                    # The site the listing binding records, so a mechanism
                    # resolving anything per origin sees the value its
                    # negotiation will later inherit.
                    "origin": str(candidate["site_id"]),
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
            entry = self.seller_stages[mechanism_id]
            registration = entry.registration_factory()
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
