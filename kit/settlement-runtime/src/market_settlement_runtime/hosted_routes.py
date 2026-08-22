"""Provider-neutral storefront mechanics for accepted hosted settlements."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from market_core.schemas import SettlementObligation
from market_identity import Identity
from pydantic import BaseModel, ConfigDict, Field

from .models import SettlementObligationRecord


class HostedSettlementStart(BaseModel):
    """The complete caller-controlled input admitted by a hosted start route."""

    model_config = ConfigDict(extra="forbid")

    negotiation_id: str = Field(min_length=1)
    obligation_ref: str = Field(pattern=r"^[0-9a-f]{64}$")
    funding_authorization_ref: str = Field(min_length=1, max_length=256)


@dataclass(frozen=True, slots=True)
class HostedAcceptedAgreement:
    """Server-authoritative accepted obligation loaded by a domain callback."""

    agreement_ref: str
    obligation_ref: str
    buyer_principal: Identity
    obligation: SettlementObligation
    mechanism_params: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class AuthorizedSettlementRequest:
    """Replay result returned by an owning storefront authentication boundary."""

    exact_retry: bool = False
    recorded_outcome: tuple[int, Any] | None = None


class PrepareHostedAgreement(Protocol):
    def __call__(
        self,
        agreement_ref: str,
        obligation_ref: str,
        record: SettlementObligationRecord | None,
    ) -> Awaitable[HostedAcceptedAgreement]: ...


class AuthorizeHostedRequest(Protocol):
    def __call__(
        self,
        request_context: Any,
        operation: str,
        resource_id: str,
        expected_principal: Identity,
        body: Mapping[str, Any] | None,
    ) -> Awaitable[AuthorizedSettlementRequest]: ...


class ReserveHostedStart(Protocol):
    def __call__(
        self,
        agreement: HostedAcceptedAgreement,
        funding_authorization_ref: str,
    ) -> Awaitable[SettlementObligationRecord]: ...


class FulfillHostedObligation(Protocol):
    def __call__(
        self,
        record: SettlementObligationRecord,
        worker_id: str,
    ) -> Awaitable[SettlementObligationRecord]: ...


class ProjectHostedSettlement(Protocol):
    def __call__(
        self,
        record: SettlementObligationRecord,
        transient_action: Any | None,
        transient_receipt: Mapping[str, Any] | None,
    ) -> Awaitable[Mapping[str, Any]]: ...


class CleanupHostedSettlement(Protocol):
    def __call__(self, agreement_ref: str, reason: str) -> Awaitable[None]: ...
class BeforeHostedReclaim(Protocol):
    def __call__(
        self,
        record: SettlementObligationRecord,
        worker_id: str,
    ) -> Awaitable[SettlementObligationRecord]: ...




@dataclass(frozen=True, slots=True)
class HostedSettlementRouteCallbacks:
    """Domain-owned interpretation injected into common route mechanics."""

    prepare: PrepareHostedAgreement
    authorize: AuthorizeHostedRequest
    reserve: ReserveHostedStart
    fulfill: FulfillHostedObligation
    project: ProjectHostedSettlement
    cleanup: CleanupHostedSettlement
    before_reclaim: BeforeHostedReclaim | None = None


class HostedSettlementRouteError(RuntimeError):
    """HTTP-shaped failure emitted without depending on a web framework."""

    def __init__(self, status_code: int, detail: Any) -> None:
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail


class HostedSettlementRouteService:
    """Run signed start/status/reclaim routes over an injected domain contract."""

    def __init__(
        self,
        *,
        repository: Any,
        runtime: Any,
        callbacks: HostedSettlementRouteCallbacks,
        mechanism_id: str,
        wake: Callable[[str], Awaitable[None]],
        worker_id: Callable[[str], str] | None = None,
    ) -> None:
        self._repository = repository
        self._runtime = runtime
        self._callbacks = callbacks
        self._mechanism_id = mechanism_id
        self._wake = wake
        self._worker_id = worker_id or (
            lambda operation: f"{operation}:{uuid.uuid4().hex}"
        )

    async def _record(self, settlement_ref: str) -> SettlementObligationRecord:
        row = await self._repository.load_settlement_obligation_by_mechanism_ref(
            settlement_ref
        )
        if row is None:
            raise HostedSettlementRouteError(404, "settlement not found")
        record = SettlementObligationRecord.model_validate(row)
        if record.obligation.get("mechanism") != self._mechanism_id:
            raise HostedSettlementRouteError(404, "settlement not found")
        return record

    async def _authorize(
        self,
        request_context: Any,
        *,
        operation: str,
        resource_id: str,
        record: SettlementObligationRecord,
    ) -> AuthorizedSettlementRequest:
        agreement = await self._callbacks.prepare(
            record.agreement_ref,
            record.obligation_ref,
            record,
        )
        auth = await self._callbacks.authorize(
            request_context,
            operation,
            resource_id,
            agreement.buyer_principal,
            None,
        )
        if auth.exact_retry and auth.recorded_outcome is None:
            raise HostedSettlementRouteError(409, "request retry is pending")
        return auth

    @staticmethod
    def _replay(auth: AuthorizedSettlementRequest) -> Mapping[str, Any] | None:
        if not auth.exact_retry:
            return None
        assert auth.recorded_outcome is not None
        status_code, payload = auth.recorded_outcome
        if status_code >= 400:
            raise HostedSettlementRouteError(status_code, payload)
        if not isinstance(payload, Mapping):
            raise HostedSettlementRouteError(500, "recorded response is malformed")
        return payload

    async def start(
        self,
        request_context: Any,
        start: HostedSettlementStart,
    ) -> Mapping[str, Any]:
        """Authorize, reserve, and materialize one accepted obligation."""
        try:
            agreement = await self._callbacks.prepare(
                start.negotiation_id,
                start.obligation_ref,
                None,
            )
        except HostedSettlementRouteError:
            raise
        except ValueError as exc:
            raise HostedSettlementRouteError(404, str(exc)) from exc
        auth = await self._callbacks.authorize(
            request_context,
            "settlement_start",
            agreement.obligation_ref,
            agreement.buyer_principal,
            start.model_dump(mode="json"),
        )
        replay = self._replay(auth)
        if replay is not None:
            return replay
        try:
            record = await self._callbacks.reserve(
                agreement,
                start.funding_authorization_ref,
            )
        except ValueError as exc:
            raise HostedSettlementRouteError(409, str(exc)) from exc
        try:
            outcome = await self._runtime.materialize(
                obligation_ref=record.obligation_ref,
                local_principal=agreement.buyer_principal,
                worker_id=self._worker_id("settlement-start"),
            )
            record = await self._reload(record.obligation_ref)
            if record.mechanism_status == "ready":
                try:
                    record = await self._callbacks.fulfill(
                        record,
                        self._worker_id("settlement-fulfill"),
                    )
                except HostedSettlementRouteError:
                    raise
                except Exception:
                    # Materialization promises a materialized obligation, not a
                    # fulfilled one. An obligation that funded and could not
                    # begin fulfilment is a real state with an owner -- the
                    # resume worker retries it -- so the caller is told what it
                    # actually got. Failing the whole start here reports the
                    # authority as unavailable when the authority did its part,
                    # and hides a funded obligation from the party that funded
                    # it.
                    record = await self._reload(record.obligation_ref)
            return await self._callbacks.project(
                record,
                outcome.action,
                outcome.receipt,
            )
        except HostedSettlementRouteError:
            raise
        except Exception as exc:
            raise HostedSettlementRouteError(
                503,
                "hosted settlement authority is temporarily unavailable",
            ) from exc

    async def status(
        self,
        request_context: Any,
        settlement_ref: str,
    ) -> Mapping[str, Any]:
        """Reconcile and project the exact accepted operation."""
        record = await self._record(settlement_ref)
        auth = await self._authorize(
            request_context,
            operation="settlement_status",
            resource_id=settlement_ref,
            record=record,
        )
        replay = self._replay(auth)
        if replay is not None:
            return replay
        try:
            outcome = await self._runtime.reconcile_status(
                obligation_ref=record.obligation_ref,
                local_principal=record.payer_principal,
                worker_id=self._worker_id("settlement-status"),
            )
            record = await self._reload(record.obligation_ref)
            if record.mechanism_status == "ready" and not record.fulfillment_ref:
                record = await self._callbacks.fulfill(
                    record,
                    self._worker_id("settlement-fulfill"),
                )
            elif (
                record.mechanism_status == "failed"
                and record.fulfillment_ref
                and record.collection_state != "succeeded"
            ):
                await self._wake(record.obligation_ref)
            return await self._callbacks.project(
                record,
                outcome.action,
                outcome.receipt,
            )
        except HostedSettlementRouteError:
            raise
        except Exception as exc:
            raise HostedSettlementRouteError(
                503,
                "hosted settlement status is temporarily unavailable",
            ) from exc

    async def reclaim(
        self,
        request_context: Any,
        settlement_ref: str,
    ) -> Mapping[str, Any]:
        """Reconcile reclaim under the runtime's fulfillment exclusion guards."""
        record = await self._record(settlement_ref)
        auth = await self._authorize(
            request_context,
            operation="settlement_reclaim",
            resource_id=settlement_ref,
            record=record,
        )
        replay = self._replay(auth)
        if replay is not None:
            return replay
        if self._callbacks.before_reclaim is not None:
            try:
                record = await self._callbacks.before_reclaim(
                    record,
                    self._worker_id("settlement-reclaim-reconcile"),
                )
            except HostedSettlementRouteError:
                raise
            except ValueError as exc:
                raise HostedSettlementRouteError(409, str(exc)) from exc
            if record.fulfillment_ref:
                raise HostedSettlementRouteError(
                    409,
                    "settlement fulfillment already committed",
                )
        try:
            outcome = await self._runtime.reclaim(
                obligation_ref=record.obligation_ref,
                local_principal=record.payer_principal,
                worker_id=self._worker_id("settlement-reclaim"),
            )
            if outcome.status == "busy":
                raise HostedSettlementRouteError(
                    409,
                    "settlement fulfillment or collection already reserved",
                )
            if outcome.status == "succeeded":
                await self._callbacks.cleanup(
                    record.agreement_ref,
                    "hosted settlement reclaimed",
                )
            record = await self._reload(record.obligation_ref)
            return await self._callbacks.project(record, None, outcome.receipt)
        except HostedSettlementRouteError:
            raise
        except ValueError as exc:
            raise HostedSettlementRouteError(409, str(exc)) from exc
        except Exception as exc:
            raise HostedSettlementRouteError(
                503,
                "hosted settlement reclaim is temporarily unavailable",
            ) from exc

    async def _reload(self, obligation_ref: str) -> SettlementObligationRecord:
        row = await self._repository.load_settlement_obligation(obligation_ref)
        if row is None:
            raise HostedSettlementRouteError(500, "settlement reservation disappeared")
        return SettlementObligationRecord.model_validate(row)
