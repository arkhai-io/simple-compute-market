"""A storefront's settlement composition over the shared settlement runtime, mechanism-neutral.

The storefront injects its seller stage table, one entry per mechanism it
composes, and every mechanism decision is that entry's: the library builds the
registry from the entries' registrations, the mechanism clients from the
entries, and the coordinator's continuations from the entry the accepted
Agreement selects, comparing no mechanism ID.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from arkhai_api_client import AuthorityClient
from market_core import MarketDomainContract, SettlementStageTable
from market_identity import Identity
from market_settlement_runtime import (
    MechanismReadiness,
    SettlementConfigurationRegistry,
    SettlementPublicationClause,
    SettlementRuntime,
    SettlementServicingWorker,
    SettlementSQLiteRepository,
    compile_settlement_publication_clause,
    derive_obligation_ref,
)

from arkhai_api_selling.contributions import SellingContributions
from arkhai_api_selling.evidence_store import IssuanceEvidenceService, PrivateResultRepository
from arkhai_api_selling.issuance import accepted_agreement

logger = logging.getLogger(__name__)


def build_settlement_registry(stages: SettlementStageTable) -> SettlementConfigurationRegistry:
    """One registration per composed seller stage."""
    return SettlementConfigurationRegistry(
        tuple(stage.registration() for stage in stages.values())
    )


def enabled_mechanism_clients(
    stages: SettlementStageTable,
    registry: SettlementConfigurationRegistry,
    settlement_config: Any,
    resources: Mapping[str, Any],
) -> dict[str, Any]:
    """The client each enabled mechanism's stage builds from ``resources``, if it builds one."""
    clients: dict[str, Any] = {}
    for registration in registry.ordered_registrations(settlement_config, role="seller"):
        section = settlement_config.mechanism_config(registration.config_key)
        if section is None or not getattr(section, "enabled", False):
            continue
        stage = stages.get(registration.mechanism_id)
        if stage is not None:
            client = stage.client(resources)
            if client is not None:
                clients[registration.mechanism_id] = client
    return clients


@dataclass(frozen=True, slots=True)
class SellingSettlementComposition:
    """The mechanism-neutral settlement parts one storefront composes."""

    contributions: SellingContributions
    stages: SettlementStageTable
    domain: MarketDomainContract
    repository: SettlementSQLiteRepository
    runtime: SettlementRuntime
    worker: SettlementServicingWorker
    local_principal: Identity
    mechanism_clients: Mapping[str, Any]
    settlement_config: Any
    configuration_registry: SettlementConfigurationRegistry
    mechanism_resources: Mapping[str, Any]
    credits_client: AuthorityClient
    evidence_service: IssuanceEvidenceService
    private_results: PrivateResultRepository
    failure_policy: Any

    def accepted_settlement_artifacts(self, agreement: Mapping[str, Any]) -> dict[str, Any]:
        mechanism = agreement["settlement"]["mechanism"]
        return self.stages[mechanism].agreement_artifacts(agreement, self)

    async def readiness(self) -> tuple[MechanismReadiness, ...]:
        return await self.configuration_registry.ordered_readiness(
            self.settlement_config,
            role="seller",
            resources=self.mechanism_resources,
        )

    def accepted_obligation_dispatch(
        self,
    ) -> dict[str, Callable[[Mapping[str, Any], Mapping[str, Any]], Any] | None]:
        """Curried registry dispatch for every enabled obligation-building mechanism."""

        dispatch: dict[
            str, Callable[[Mapping[str, Any], Mapping[str, Any]], Any] | None
        ] = {}
        for mechanism_id in self.settlement_config.priority:
            if mechanism_id not in self.stages:
                continue
            registration = self.configuration_registry.registration(mechanism_id)
            if registration.accepted_obligation_builder is None:
                dispatch[mechanism_id] = None
                continue

            def build(
                option: Mapping[str, Any],
                context: Mapping[str, Any],
                *,
                _mechanism_id: str = mechanism_id,
            ) -> Any:
                return self.configuration_registry.build_accepted_obligation(
                    _mechanism_id,
                    option,
                    self.settlement_config,
                    role="seller",
                    context=context,
                )

            dispatch[mechanism_id] = build
        return dispatch

    async def publication_artifacts(
        self,
        resources: Mapping[str, Any],
        clauses: list[SettlementPublicationClause | Mapping[str, Any]] | None = None,
    ) -> tuple[
        list[dict[str, Any]], list[dict[str, Any]], tuple[MechanismReadiness, ...]
    ]:
        """Compile each complete ready clause without suppressing ready peers."""
        merged_resources = {**self.mechanism_resources, **resources}
        compiled = (
            [
                compile_settlement_publication_clause(
                    clause,
                    registry=self.configuration_registry,
                    config=self.settlement_config,
                    role="seller",
                )
                for clause in clauses
            ]
            if clauses is not None
            else None
        )
        readiness_resources = merged_resources
        if compiled is not None:
            projected: dict[str, Any] = {}
            for mechanism, stage in self.stages.items():
                projected.update(stage.readiness_resources(
                    [clause for clause in compiled if clause.mechanism == mechanism],
                    merged_resources,
                ))
            readiness_resources = {**merged_resources, **projected}
        readiness = await self.configuration_registry.ordered_readiness(
            self.settlement_config,
            role="seller",
            resources=readiness_resources,
        )
        statuses = {status.mechanism: status for status in readiness}
        work = (
            [
                (
                    statuses.get(clause.mechanism),
                    {**merged_resources, "publication_clause": clause},
                )
                for clause in compiled
            ]
            if compiled is not None
            else [(status, merged_resources) for status in readiness]
        )
        accepted_escrows: list[dict[str, Any]] = []
        settlement_options: list[dict[str, Any]] = []
        for status, option_resources in work:
            if status is None:
                raise RuntimeError("settlement clause has no registered mechanism")
            if not status.enabled:
                if compiled is not None:
                    raise ValueError(
                        f"settlement publication mechanism {status.mechanism!r} is disabled"
                    )
                continue
            if not status.ready:
                logger.warning(
                    "[SETTLEMENT] option suppressed mechanism=%s blockers=%s",
                    status.mechanism,
                    ",".join(blocker.code for blocker in status.blockers),
                )
                continue
            if status.mechanism not in self.stages:
                continue
            self.stages[status.mechanism].validate_publication(option_resources)
            envelope = self.configuration_registry.build_option(
                status,
                self.settlement_config,
                role="seller",
                resources=option_resources,
            )
            if not isinstance(envelope, Mapping):
                raise RuntimeError("settlement option builder returned no envelope")
            accepted_escrows.extend(
                dict(item) for item in envelope.get("accepted_escrows", ())
            )
            settlement_options.extend(
                dict(item) for item in envelope.get("settlement_options", ())
            )
        if not accepted_escrows and not settlement_options:
            raise RuntimeError("no enabled settlement mechanism is ready")
        return accepted_escrows, settlement_options, readiness


# The settlement job coordinator's continuations. A storefront binds each to its
# stage table and collaborators; each resolves the stage the accepted Agreement
# selected.


async def prepare_settlement(stages: SettlementStageTable, **context: Any) -> Any:
    """Resolve only the exact accepted seller stage before verification."""
    thread = await context["sqlite_client"].load_negotiation_thread_row(
        negotiation_id=context["negotiation_id"],
    )
    if thread is None:
        raise ValueError("accepted negotiation is unavailable")
    agreement, _raw = accepted_agreement(thread)
    try:
        stage = stages[agreement.settlement.mechanism]
    except KeyError as exc:
        raise ValueError("unsupported accepted settlement mechanism") from exc
    return await stage.prepare(**context)


async def reserve_settlement(
    sqlite_client: Any,
    prepared: Any,
    escrow_uid: str,
    negotiation_id: str,
    *,
    settlement_runtime: Any,
    wake_servicing: Any,
) -> dict[str, Any] | None:
    """Create, bind, and recover the existing public settlement row."""
    projection = prepared.projection_context
    inserted = await sqlite_client.insert_escrow(
        escrow_uid=escrow_uid,
        negotiation_id=negotiation_id,
        chain_name=projection.chain_name,
        escrow_address=projection.escrow_address,
        is_primary=True,
        status="provisioning",
    )
    obligation_ref = derive_obligation_ref(
        prepared.agreement_ref,
        prepared.selected_obligation_index,
        prepared.obligations[prepared.selected_obligation_index],
    )
    row = await sqlite_client.bind_escrow_obligation(
        escrow_uid=escrow_uid,
        obligation_ref=obligation_ref,
        obligation_index=prepared.selected_obligation_index,
    )
    fulfillment_ref = row.get("fulfillment_uid")
    if (
        not inserted
        and row.get("status") == "ready"
        and isinstance(fulfillment_ref, str)
        and fulfillment_ref
    ):
        await settlement_runtime.bind_fulfillment(
            obligation_ref,
            fulfillment_ref,
            local_principal=prepared.local_principal,
        )
        await wake_servicing(obligation_ref)
    existing = await sqlite_client.load_issuance_progress(reference=escrow_uid)
    if existing is None:
        await sqlite_client.save_issuance_progress(
            negotiation_id=negotiation_id, public_ref=escrow_uid, status="provisioning",
        )
    return row if existing is not None and existing["status"] in {"ready", "failed"} else None


async def fulfill_settlement(
    stages: SettlementStageTable, prepared: Any, *, mechanism_client: Any
) -> Any:
    """Reconstruct the selected continuation from the accepted Agreement."""
    db = prepared.fulfillment_input.sqlite_client
    thread = await db.load_negotiation_thread_row(negotiation_id=prepared.agreement_ref)
    agreement, _raw = accepted_agreement(thread)
    return await stages[agreement.settlement.mechanism].deliver_prepared(
        prepared, mechanism_client=mechanism_client,
    )


async def persist_settlement_outcome(
    sqlite_client: Any,
    prepared: Any,
    outcome: Any,
) -> None:
    """Project generic completion into the unchanged settle-status row."""
    if outcome.status == "fulfilled":
        await sqlite_client.update_escrow(
            escrow_uid=prepared.mechanism_ref,
            status="ready",
            fulfillment_uid=outcome.fulfillment_ref,
            connection_details=outcome.public_result.get("connection_details"),
            tenant_credentials=None,
        )
        return
    reason = outcome.reason or "fulfillment failed"
    # Logged as well as persisted. The reason reaches the buyer in the
    # settle-status body, and nowhere else: a settlement that fails before
    # its first call to the credits service leaves no other trace in the
    # storefront's output. `issuance_error:` prefixes carry a caught
    # exception, which is the one case where the reason is the only record
    # that it happened at all.
    logger.warning(
        "[SETTLE] settlement failed for %s: %s",
        prepared.mechanism_ref,
        reason,
    )
    await sqlite_client.save_issuance_progress(
        negotiation_id=prepared.agreement_ref, public_ref=prepared.mechanism_ref,
        status="failed", reason=reason,
    )
    await sqlite_client.update_escrow(
        escrow_uid=prepared.mechanism_ref,
        status="failed",
        reason=reason,
    )
