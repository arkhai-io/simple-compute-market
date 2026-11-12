"""Shared-registry settlement composition for the bare-metal storefront."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
import logging
from types import MappingProxyType
from typing import Any

from market_settlement_runtime.rate_servicing import RateServicing, RateServicingUnavailable
from market_arkhai_payments.presets import PaymentsRatePresetHelper, rate_term_timing
from market_settlement_runtime.horizon import RateTermProjections
from market_settlement_runtime.rate_publication import (
    RatePresetHelper, RatePresetRefusal,
    derive_rate_preset, effective_delivery_deadline,
)
from market_settlement_runtime.terms_policy import (
    DefaultSellerTermsPolicy, SellerTermsPolicy,
    penalty_periods, review_for_publication,
)

from core_storefront.publication_runner import NoSettlementOption, PublicationPayload
from market_core import SettlementStageTable
from market_storefront_kit.dispute_configuration import RegistryDisputePolicy
from market_arkhai_mediation.contract import INTERFACE as MEDIATION_INTERFACE
from market_core.schemas import SettlementOption
from .alkahest_lifecycle import alkahest_servicing
from .settlement_stages import (
    ALKAHEST_MECHANISM,
    AlkahestStage,
    ContactStage,
    PaymentStage,
    declined_servicing,
    refund_payment,
    revalidate_alkahest,
    revalidate_payment,
    settle_payment,
    verify_alkahest,
    verify_payment,
)
from market_alkahest import (
    ALKAHEST_CONFIG_KEY,
    ORACLE_GATED_RELEASE,
    RECIPIENT_RELEASE,
    require_deliverable_release_models,
    create_alkahest_registration,
    escrow_release_conditions,
)
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

logger = logging.getLogger(__name__)

SELLER_STAGES = SettlementStageTable(
    {
        # A bare-metal deal leases a whole machine that is never preempted, so
        # the interruptible splitter's refund split has nothing to settle.
        ALKAHEST_MECHANISM: AlkahestStage(
            create_alkahest_registration,
            verify_alkahest,
            revalidate_alkahest,
            True,
            completes_outside_settlement=False,
            servicing=alkahest_servicing,
            release_models=frozenset({RECIPIENT_RELEASE, ORACLE_GATED_RELEASE}),
        ),
        ARKHAI_PAYMENTS_MECHANISM: PaymentStage(
            create_arkhai_payments_registration,
            verify_payment,
            revalidate_payment,
            True,
            completes_outside_settlement=False,
            refund=refund_payment,
            reconcile=settle_payment,
        ),
        # An introduction delivers nothing through capacity and is completed by
        # its reveal, so it has no settle operation or recovery gate.
        CONTACT_MECHANISM: ContactStage(
            create_contact_exchange_registration,
            verify=None,
            revalidate=None,
            fulfils_through_capacity=False,
            completes_outside_settlement=True,
            servicing=declined_servicing,
        ),
    }
)


def _wallet_address(wallet: Any) -> str:
    """The seller wallet's address, given as the address or as a wallet carrying one."""
    if wallet is None or isinstance(wallet, str):
        return wallet or ""
    if isinstance(wallet, Mapping):
        return str(wallet.get("address") or "")
    return str(getattr(wallet, "address", "") or "")


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

    disputes: RegistryDisputePolicy = field(default_factory=lambda: RegistryDisputePolicy.from_document({}), repr=False)
    seller_stages: SettlementStageTable[Any] = SELLER_STAGES
    rate_servicing: RateServicing = field(default_factory=RateServicing, repr=False)
    rate_preset_helpers: Mapping[str, RatePresetHelper] = field(
        default_factory=lambda: {ARKHAI_PAYMENTS_MECHANISM: PaymentsRatePresetHelper()}, repr=False,
    )
    rate_term_projections: RateTermProjections = field(default_factory=dict, repr=False)
    # Decides the unstated on-demand penalty and whether a derived option is
    # published; it sees options only after derivation has validated them.
    terms_policy: SellerTermsPolicy = field(default_factory=DefaultSellerTermsPolicy, repr=False)
    delivery_deadline_for_pool: Callable[[str, str | None], int | None] = field(
        default=lambda _site, _pool: None, repr=False,
    )

    def __post_init__(self) -> None:
        if any(
            mechanism not in self.seller_stages for mechanism in self.config.priority
        ):
            raise ValueError("enabled settlement mechanism has no seller stage")
        self.registry.validate(self.config, role="seller")
        stage = self.seller_stages.get(ALKAHEST_MECHANISM)
        require_deliverable_release_models(
            self.config.mechanisms.get(ALKAHEST_CONFIG_KEY),
            getattr(stage, "release_models", ()),
        )
        object.__setattr__(self, "resources", MappingProxyType(dict(self.resources)))
        # Accepted payment deals are serviced whether or not new payment options
        # are published, so the stage follows the servicing fields, not `enabled`.
        stage = servicing_stage(
            self.config.mechanisms.get(ARKHAI_PAYMENTS_CONFIG_KEY),
            client_for_owner=self.payments_client_for_owner,
        )
        if stage is not None:
            stage.rate_servicing = self.rate_servicing
        object.__setattr__(self, "payments_stage", stage)
        if not self.rate_term_projections:
            object.__setattr__(self, "rate_term_projections", {
                ARKHAI_PAYMENTS_MECHANISM: lambda option: rate_term_timing(
                    option, authorities=self.disputes.for_publication(),
                ),
            })

    @classmethod
    def from_raw_config(
        cls,
        raw_settlement: Mapping[str, Any],
        *,
        resources: Mapping[str, Any] | None = None,
        payments_client_for_owner: ClientForOwner | None = None,
        disputes: RegistryDisputePolicy | None = None,
        terms_policy: SellerTermsPolicy | None = None,
    ) -> "BareMetalStorefrontSettlementComposition":
        registry = build_bare_metal_settlement_registry()
        return cls(
            registry=registry,
            config=registry.resolve(raw_settlement, role="seller"),
            resources={**(resources or {}), **({"disputes": disputes} if disputes is not None else {})},
            disputes=disputes or RegistryDisputePolicy.from_document({}),
            terms_policy=terms_policy or DefaultSellerTermsPolicy(),
            payments_client_for_owner=payments_client_for_owner,
        )

    @property
    def enabled_mechanisms(self) -> tuple[str, ...]:
        return self.config.priority

    @property
    def chain_clients(self) -> Mapping[str, Any]:
        """The Alkahest chain clients, as the live map the chain probe updates.

        The map itself, even while empty, so a client the probe builds after
        startup reaches every holder.
        """
        clients = self.resources.get("clients")
        return clients if isinstance(clients, Mapping) else {}

    def arkhai_payments_stage(self) -> PaymentSellerStage | None:
        return self.payments_stage

    def settlement_data_dispatch(
        self,
    ) -> dict[str, Callable[[Mapping[str, Any]], Mapping[str, Any] | None]]:
        payment_stage = self.payments_stage
        def build(entry: Any) -> Callable[[Mapping[str, Any]], Mapping[str, Any] | None]:
            def accepted(agreement: Mapping[str, Any]) -> Mapping[str, Any] | None:
                return entry.accepted_data(agreement, payment_stage)
            return accepted

        return {mechanism: build(entry) for mechanism, entry in self.seller_stages.items()}

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
        max_duration_seconds: int | None = None,
        publication_diagnostic: Callable[[dict[str, Any]], None] = lambda _entry: None,
    ) -> PublicationPayload:
        """Build ready settlement publication alternatives.

        A listing publishing an Alkahest escrow advertises, per chain its
        escrows name, the release condition the Alkahest mechanism derives from
        the configured section, the seller wallet, and that chain's address
        book, and only while Alkahest is ready: an unready mechanism's clauses
        publish no escrow to release.

        ``clauses`` are the candidate's admissible clauses. When none of them
        builds an option, the candidate is refused with ``NoSettlementOption``,
        naming their mechanisms and those whose readiness is unknown.
        """

        deadline = effective_delivery_deadline(self.delivery_deadline_for_pool(
            str(candidate["site_id"]), candidate.get("pool_id"),
        ))

        def diagnose(entry: dict[str, Any]) -> None:
            publication_diagnostic(entry)
            logger.warning("[PUBLICATION] %s: %s", entry["code"], entry["detail"])

        readiness = await self.readiness(clauses=clauses)
        readiness_by_mechanism = {item.mechanism: item for item in readiness}
        accepted_escrows: list[dict[str, Any]] = []
        settlement_options: list[dict[str, Any]] = []

        for clause in clauses:
            mechanism_readiness = readiness_by_mechanism.get(clause.mechanism)
            if mechanism_readiness is None or not mechanism_readiness.ready:
                continue
            if clause.recurring is not None:
                result = derive_rate_preset(
                    clause, helper=self.rate_preset_helpers.get(clause.mechanism),
                    servicing=self.rate_servicing,
                    authorities=self.disputes.for_publication(),
                    max_duration_seconds=max_duration_seconds,
                    available_until_utc=candidate.get("available_until_utc"),
                    delivery_deadline_seconds=deadline,
                    now=datetime.now(UTC),
                    default_penalty_periods=penalty_periods(self.terms_policy),
                )
                if isinstance(result, RatePresetRefusal):
                    diagnose({"code": result.code, "detail": result.detail, "mechanism": clause.mechanism})
                    continue
                artifacts = {"settlement_options": [result.model_dump(mode="json")]}
            else:
                if max_duration_seconds is None and self.seller_stages[clause.mechanism].fulfils_through_capacity:
                    diagnose({"code": "reserved_lease_bound_missing", "detail": "reserved bare-metal publication requires a positive relative maximum", "mechanism": clause.mechanism})
                    continue
                artifacts = self.registry.build_option(
                    mechanism_readiness,
                    self.config,
                    role="seller",
                    resources={
                        **self.resources,
                        "dispute_authorities": self.disputes.for_publication(),
                        "dispute_interfaces": frozenset({MEDIATION_INTERFACE}), "compute": True,
                        "publication_clause": clause,
                        "delivery_deadline_seconds": deadline,
                        "candidate": dict(candidate),
                        # Use the binding's site, also used in negotiation.
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
            for item in built_options:
                option = SettlementOption.model_validate(item)
                try:
                    self.rate_servicing.require_option(option)
                except RateServicingUnavailable as exc:
                    diagnose({"code": "rate_servicing_undeclared", "detail": str(exc), "mechanism": option.settlement_schema})
                    continue
                if not review_for_publication(self.terms_policy, option, diagnose):
                    continue
                settlement_options.append(option.model_dump(mode="json"))

        if not accepted_escrows and not settlement_options:
            mechanisms = tuple(dict.fromkeys(clause.mechanism for clause in clauses))
            # A ready mechanism that built nothing, as contact exchange does
            # for an origin with no contact, is ruled out like a misconfigured one.
            unknown = tuple(
                mechanism
                for mechanism in mechanisms
                if mechanism in readiness_by_mechanism
                and readiness_by_mechanism[mechanism].unknown
            )
            detail = (
                f"pool {candidate.get('pool_id')!r} publishes no settlement option: "
                + (
                    f"readiness unknown for {', '.join(unknown)}"
                    if unknown
                    else "configuration rules out "
                    + (", ".join(mechanisms) or "every mechanism")
                )
            )
            raise NoSettlementOption(detail, mechanisms=mechanisms, unknown=unknown)

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
            demands=tuple(self._release_conditions(accepted_escrows, readiness)),
            max_duration_seconds=max_duration_seconds,
        )

    def _release_conditions(
        self,
        accepted_escrows: Sequence[Mapping[str, Any]],
        readiness: Sequence[MechanismReadiness],
    ) -> list[dict[str, Any]]:
        chains = self.resources.get("chains")
        return escrow_release_conditions(
            self.config.mechanisms.get(ALKAHEST_CONFIG_KEY),
            accepted_escrows,
            readiness=readiness,
            chains=chains if isinstance(chains, Mapping) else {},
            wallet_address=_wallet_address(self.resources.get("wallet")),
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
