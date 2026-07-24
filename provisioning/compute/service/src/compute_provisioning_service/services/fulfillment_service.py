"""Durable provisioning-side fulfillment acceptance and provider dispatch.

The service receives an already-selected settlement resource. Scheduling is a
separate operation and is never called from this boundary. Provider input is
prepared synchronously and persisted before any external dispatch occurs.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from market_fulfillment import (
    FulfillmentConflictError,
    FulfillmentRequestInvalidError,
    FulfillmentValidationIssue,
    FulfillmentValidationResult,
    LiveCredential,
    ProviderNotFoundError,
    ProviderRegistry,
    ProviderUnavailableError,
    SettlementEntityNotFoundError,
    SettlementRecord,
    SettlementRecordState,
    SettlementRepository,
    SettlementRequirement,
    SettlementResource,
    VersionedEnvelope,
    begin_sqlite_write_transaction,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FulfillmentAcceptance:
    capacity_reservation_id: str
    fulfillment_id: str
    state: str


@dataclass(frozen=True)
class FulfillmentStatus:
    capacity_reservation_id: str
    fulfillment_id: str
    state: str
    failure_reason: str | None
    failure_message: str | None


@dataclass(frozen=True)
class FulfillmentResourceResult:
    provisioned_resource_id: str
    domain_resource_ref: str | None
    status: str


@dataclass(frozen=True)
class FulfillmentResultProjection:
    capacity_reservation_id: str
    fulfillment_id: str
    state: str
    provisioned_resources: tuple[FulfillmentResourceResult, ...]
    failure_reason: str | None
    failure_message: str | None
    credential_generation: int
    credentials: tuple[LiveCredential, ...]


def _resource_from_record(record: SettlementRecord) -> SettlementResource:
    requirement = SettlementRequirement.model_validate(record.scheduling_requirements)
    return SettlementResource(
        settlement_resource_id=str(record.settlement_resource_id),
        pool_id=str(record.pool_id),
        resource_kind=requirement.resource_kind,
        provider=str(record.provider),
        attributes=dict(record.resource_attributes or {}),
    )


def _validate_payload(fulfillment_request: VersionedEnvelope) -> None:
    if not isinstance(fulfillment_request.payload, dict):
        raise FulfillmentRequestInvalidError(
            "fulfillment request payload must be an object"
        )


class FulfillmentService:
    """Accept and dispatch fulfillment without performing placement."""

    def __init__(
        self,
        *,
        provider_registry: ProviderRegistry,
        session_factory: sessionmaker[Session],
        repository: SettlementRepository,
    ) -> None:
        self._provider_registry = provider_registry
        self._session_factory = session_factory
        self._repository = repository

    def _owned_record(
        self,
        db: Session,
        *,
        capacity_reservation_id: str,
        owner_principal: str,
    ) -> SettlementRecord:
        record = self._repository.get(db, capacity_reservation_id)
        if record is None or record.owner_principal != owner_principal:
            raise SettlementEntityNotFoundError(
                f"no settlement assignment exists for capacity_reservation_id="
                f"{capacity_reservation_id!r}"
            )
        return record

    def get_status(
        self,
        *,
        fulfillment_id: str,
        owner_principal: str,
    ) -> FulfillmentStatus:
        with self._session_factory() as db:
            record = self._repository.get_by_fulfillment_id(db, fulfillment_id)
            if record is None or record.owner_principal != owner_principal:
                raise SettlementEntityNotFoundError(
                    f"no fulfillment exists for fulfillment_id={fulfillment_id!r}"
                )
            return FulfillmentStatus(
                capacity_reservation_id=str(record.capacity_reservation_id),
                fulfillment_id=str(record.fulfillment_id),
                state=str(record.state),
                failure_reason=(
                    str(record.failure_reason)
                    if record.failure_reason is not None
                    else None
                ),
                failure_message=(
                    str(record.failure_message)
                    if record.failure_message is not None
                    else None
                ),
            )

    async def get_result(
        self,
        *,
        fulfillment_id: str,
        owner_principal: str,
    ) -> FulfillmentResultProjection:
        claim_id = f"credential:{uuid.uuid4()}"
        with self._session_factory() as db:
            record = self._repository.get_by_fulfillment_id(db, fulfillment_id)
            if record is None or record.owner_principal != owner_principal:
                raise SettlementEntityNotFoundError(
                    f"no fulfillment exists for fulfillment_id={fulfillment_id!r}"
                )
            resources = tuple(
                FulfillmentResourceResult(
                    provisioned_resource_id=str(item.provisioned_resource_id),
                    domain_resource_ref=(
                        str(item.domain_resource_ref)
                        if item.domain_resource_ref is not None
                        else None
                    ),
                    status=str(item.status),
                )
                for item in self._repository.list_provisioned_resources(
                    db, str(record.capacity_reservation_id)
                )
            )
            generation = int(record.credential_generation or 0)
            capacity_reservation_id = str(record.capacity_reservation_id)
            durable_result = FulfillmentResultProjection(
                capacity_reservation_id=capacity_reservation_id,
                fulfillment_id=str(record.fulfillment_id),
                state=str(record.state),
                provisioned_resources=resources,
                failure_reason=(
                    str(record.failure_reason)
                    if record.failure_reason is not None
                    else None
                ),
                failure_message=(
                    str(record.failure_message)
                    if record.failure_message is not None
                    else None
                ),
                credential_generation=generation,
                credentials=(),
            )
            if record.state != SettlementRecordState.active.value:
                return durable_result
            try:
                claimed = self._repository.claim_credential_rotation(
                    db,
                    fulfillment_id=fulfillment_id,
                    owner_principal=owner_principal,
                    claim_id=claim_id,
                    lease_seconds=300,
                )
            except FulfillmentConflictError as exc:
                db.rollback()
                raise ProviderUnavailableError(
                    "credential rotation is already in progress"
                ) from exc
            if claimed is None:
                raise SettlementEntityNotFoundError(
                    f"no active fulfillment exists for fulfillment_id={fulfillment_id!r}"
                )
            resource = _resource_from_record(claimed)
            provider = self._provider_registry.require(
                resource.provider, resource.resource_kind
            )
            provider_metadata = dict(claimed.provider_metadata or {})
            db.commit()

        try:
            live = await provider.get_live_credentials(
                capacity_reservation_id,
                resource,
                provider_metadata,
                credential_generation=generation + 1,
            )
        except Exception:
            with self._session_factory() as db:
                self._repository.clear_claim(
                    db,
                    capacity_reservation_id,
                    worker_id=claim_id,
                )
                db.commit()
            raise

        with self._session_factory() as db:
            if live.rotated:
                generation = self._repository.complete_credential_rotation(
                    db,
                    capacity_reservation_id=capacity_reservation_id,
                    claim_id=claim_id,
                )
            else:
                self._repository.clear_claim(
                    db,
                    capacity_reservation_id,
                    worker_id=claim_id,
                )
            db.commit()
        return FulfillmentResultProjection(
            capacity_reservation_id=durable_result.capacity_reservation_id,
            fulfillment_id=durable_result.fulfillment_id,
            state=durable_result.state,
            provisioned_resources=durable_result.provisioned_resources,
            failure_reason=durable_result.failure_reason,
            failure_message=durable_result.failure_message,
            credential_generation=generation,
            credentials=live.credentials,
        )

    def validate_create(
        self,
        *,
        capacity_reservation_id: str,
        market: str,
        fulfillment_request: VersionedEnvelope,
        owner_principal: str,
    ) -> FulfillmentValidationResult:
        issues: list[FulfillmentValidationIssue] = []
        try:
            with self._session_factory() as db:
                record = self._owned_record(
                    db,
                    capacity_reservation_id=capacity_reservation_id,
                    owner_principal=owner_principal,
                )
                if record.market != market:
                    raise FulfillmentConflictError(
                        "fulfillment market differs from the scheduled market"
                    )
                if record.fulfillment_id is not None:
                    if record.fulfillment_request != fulfillment_request.model_dump(
                        mode="json"
                    ):
                        raise FulfillmentConflictError(
                            "capacity reservation already has a different fulfillment request"
                        )
                else:
                    resource = _resource_from_record(record)
                    _validate_payload(fulfillment_request)
                    provider = self._provider_registry.require(
                        resource.provider,
                        resource.resource_kind,
                    )
                    provider.prepare_create(
                        capacity_reservation_id,
                        fulfillment_request,
                        resource,
                    )
        except SettlementEntityNotFoundError:
            raise
        except ProviderNotFoundError as exc:
            issues.append(
                FulfillmentValidationIssue(
                    code="provider_not_found",
                    message=str(exc),
                    field="resource.provider",
                )
            )
        except FulfillmentConflictError as exc:
            issues.append(
                FulfillmentValidationIssue(
                    code="fulfillment_conflict",
                    message=str(exc),
                )
            )
        except Exception as exc:
            issues.append(
                FulfillmentValidationIssue(
                    code="request_invalid",
                    message=str(exc),
                )
            )
        return FulfillmentValidationResult(tuple(issues))

    async def begin_fulfillment(
        self,
        *,
        capacity_reservation_id: str,
        market: str,
        fulfillment_request: VersionedEnvelope,
        owner_principal: str,
    ) -> FulfillmentAcceptance:
        with self._session_factory() as db:
            begin_sqlite_write_transaction(db)
            record = self._owned_record(
                db,
                capacity_reservation_id=capacity_reservation_id,
                owner_principal=owner_principal,
            )
            if record.market != market:
                raise FulfillmentConflictError(
                    "fulfillment market differs from the scheduled market"
                )
            resource = _resource_from_record(record)
            provider = self._provider_registry.require(
                resource.provider,
                resource.resource_kind,
            )
            _validate_payload(fulfillment_request)

            was_accepted = record.fulfillment_id is not None
            prepared: VersionedEnvelope[Any]
            if was_accepted:
                if record.prepared_create_operation is None:
                    raise FulfillmentConflictError(
                        "accepted fulfillment has no prepared create operation"
                    )
                prepared = VersionedEnvelope.model_validate(
                    record.prepared_create_operation
                )
            else:
                prepared = provider.prepare_create(
                    capacity_reservation_id,
                    fulfillment_request,
                    resource,
                )

            accepted = self._repository.accept_fulfillment(
                db,
                capacity_reservation_id=capacity_reservation_id,
                market=market,
                fulfillment_request=fulfillment_request,
                prepared_create_operation=prepared,
                owner_principal=owner_principal,
            )
            fulfillment_id = str(accepted.fulfillment_id)
            accepted_state = str(accepted.state)
            db.commit()

        return FulfillmentAcceptance(
            capacity_reservation_id=capacity_reservation_id,
            fulfillment_id=fulfillment_id,
            state=accepted_state,
        )

    async def begin_teardown(
        self,
        *,
        fulfillment_id: str,
        owner_principal: str,
    ) -> FulfillmentAcceptance:
        with self._session_factory() as db:
            begin_sqlite_write_transaction(db)
            record = self._repository.get_by_fulfillment_id(db, fulfillment_id)
            if record is None or record.owner_principal != owner_principal:
                raise SettlementEntityNotFoundError(
                    f"no fulfillment exists for fulfillment_id={fulfillment_id!r}"
                )
            resource = _resource_from_record(record)
            provider = self._provider_registry.require(
                resource.provider, resource.resource_kind
            )
            if record.state == SettlementRecordState.active.value:
                prepared: VersionedEnvelope[Any] = (
                    VersionedEnvelope.model_validate(
                        record.prepared_teardown_operation
                    )
                    if record.prepared_teardown_operation is not None
                    else provider.prepare_teardown(
                        str(record.capacity_reservation_id),
                        resource,
                        dict(record.provider_metadata or {}),
                    )
                )
                record = self._repository.transition(
                    db,
                    str(record.capacity_reservation_id),
                    SettlementRecordState.teardown_dispatch_pending.value,
                    prepared_teardown_operation=prepared.model_dump(mode="json"),
                )
            elif record.state == SettlementRecordState.teardown_failed.value:
                if record.prepared_teardown_operation is None:
                    raise FulfillmentConflictError(
                        "failed teardown has no prepared operation"
                    )
                prepared = VersionedEnvelope.model_validate(
                    record.prepared_teardown_operation
                )
                record = self._repository.transition(
                    db,
                    str(record.capacity_reservation_id),
                    SettlementRecordState.teardown_dispatch_pending.value,
                )
            elif record.state in {
                SettlementRecordState.teardown_dispatch_pending.value,
                SettlementRecordState.tearing_down.value,
                SettlementRecordState.torn_down.value,
            }:
                prepared = (
                    VersionedEnvelope.model_validate(
                        record.prepared_teardown_operation
                    )
                    if record.prepared_teardown_operation is not None
                    else None
                )
                db.commit()
                return FulfillmentAcceptance(
                    capacity_reservation_id=str(record.capacity_reservation_id),
                    fulfillment_id=fulfillment_id,
                    state=str(record.state),
                )
            else:
                raise FulfillmentConflictError(
                    f"fulfillment in state {record.state!r} cannot be torn down"
                )
            capacity_reservation_id = str(record.capacity_reservation_id)
            state = str(record.state)
            db.commit()

        return FulfillmentAcceptance(
            capacity_reservation_id=capacity_reservation_id,
            fulfillment_id=fulfillment_id,
            state=state,
        )
