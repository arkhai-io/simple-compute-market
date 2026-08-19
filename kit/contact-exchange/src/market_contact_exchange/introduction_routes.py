"""Framework-free introduction reveal mechanics for accepted contact deals.

Mirrors the hosted settlement route service — signed operations keyed by the
negotiation and obligation ref, authorization delegated to the domain through
callbacks — with inverted durability: the contact payloads persist and the
read is idempotent. An introduction that could be lost to a missed poll would
not be an introduction.
"""

from __future__ import annotations

from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from market_identity import Identity
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .settlement_config import MECHANISM, validate_contact_payload


class IntroductionStart(BaseModel):
    """The complete caller-controlled input admitted by the start route.

    The buyer's contact payload accompanies start, so "available to both
    parties" is a well-defined terminal condition.
    """

    model_config = ConfigDict(extra="forbid")

    negotiation_id: str = Field(min_length=1)
    obligation_ref: str = Field(pattern=r"^[0-9a-f]{64}$")
    contact_payload: dict[str, str] = Field(min_length=1)

    @field_validator("contact_payload")
    @classmethod
    def bound_contact_payload(cls, value: dict[str, str]) -> dict[str, str]:
        return validate_contact_payload(value)


@dataclass(frozen=True, slots=True)
class IntroductionAgreement:
    """Server-authoritative accepted introduction loaded by a domain callback."""

    agreement_ref: str
    obligation_ref: str
    buyer_principal: Identity
    seller_principal: Identity
    introduction_package: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class AuthorizedIntroductionRequest:
    """Authentication result returned by the owning storefront boundary."""

    principal: Identity
    exact_retry: bool = False
    recorded_outcome: tuple[int, Any] | None = None


class IntroductionRecord(BaseModel):
    """One durably persisted, idempotently re-readable introduction."""

    obligation_ref: str
    agreement_ref: str
    buyer_contact: dict[str, str]
    seller_contact: dict[str, str]
    introduction_package: dict[str, Any] = Field(default_factory=dict)


class PrepareIntroduction(Protocol):
    def __call__(
        self,
        negotiation_id: str | None,
        obligation_ref: str,
    ) -> Awaitable[IntroductionAgreement]: ...


class AuthorizeIntroduction(Protocol):
    def __call__(
        self,
        request_context: Any,
        operation: str,
        resource_id: str,
        allowed_principals: tuple[Identity, ...],
        body: Mapping[str, Any] | None,
    ) -> Awaitable[AuthorizedIntroductionRequest]: ...


class PersistIntroduction(Protocol):
    def __call__(
        self,
        agreement: IntroductionAgreement,
        buyer_contact: Mapping[str, str],
        seller_contact: Mapping[str, str],
    ) -> Awaitable[IntroductionRecord]: ...


class LoadIntroduction(Protocol):
    def __call__(self, obligation_ref: str) -> Awaitable[IntroductionRecord | None]: ...


class CompleteIntroduction(Protocol):
    def __call__(self, agreement: IntroductionAgreement) -> Awaitable[None]: ...


class DeliverIntroduction(Protocol):
    """Hand one revealed introduction to the seller's own delivery.

    Injected rather than imported: this kit knows that a reveal is worth
    telling its owner about, not how the owner reads things. The
    implementation is expected to return promptly -- the composition root
    schedules the actual sending -- and anything it raises is swallowed, since
    a convenience must not undo a completed deal.
    """

    def __call__(
        self,
        projection: Mapping[str, Any],
        agreement: IntroductionAgreement,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class IntroductionRouteCallbacks:
    """Domain-owned interpretation injected into common route mechanics."""

    prepare: PrepareIntroduction
    authorize: AuthorizeIntroduction
    persist: PersistIntroduction
    load: LoadIntroduction
    complete: CompleteIntroduction


class IntroductionRouteError(RuntimeError):
    """HTTP-shaped failure emitted without depending on a web framework."""

    def __init__(self, status_code: int, detail: Any) -> None:
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail


def introduction_projection(
    record: IntroductionRecord,
    *,
    for_role: Literal["buyer", "seller"],
    mechanism_id: str = MECHANISM,
) -> dict[str, Any]:
    """The reveal as one side sees it: the counterparty's half, not its own.

    One definition, so a re-delivery outside the request path shows the
    operator exactly what the reveal itself showed them.
    """

    counterparty_contact = (
        record.seller_contact if for_role == "buyer" else record.buyer_contact
    )
    return {
        "obligation_ref": record.obligation_ref,
        "mechanism": mechanism_id,
        "revealed": True,
        "introduction": dict(record.introduction_package),
        "counterparty_contact": dict(counterparty_contact),
    }


class IntroductionRouteService:
    """Run the signed start/read reveal family over an injected domain contract.

    The seller's contact payload binds from configuration at the first
    introduction operation; acceptance stays payload-free by construction, so
    deals that never start persist no contact data at all.
    """

    def __init__(
        self,
        *,
        callbacks: IntroductionRouteCallbacks,
        seller_contact: Mapping[str, str],
        mechanism_id: str = MECHANISM,
        deliver: DeliverIntroduction | None = None,
    ) -> None:
        self._callbacks = callbacks
        self._seller_contact = validate_contact_payload(seller_contact)
        if not self._seller_contact:
            raise ValueError("introduction reveal requires a seller contact payload")
        self._mechanism_id = mechanism_id
        self._deliver = deliver

    async def _prepare(
        self,
        negotiation_id: str | None,
        obligation_ref: str,
    ) -> IntroductionAgreement:
        try:
            return await self._callbacks.prepare(negotiation_id, obligation_ref)
        except IntroductionRouteError:
            raise
        except ValueError as exc:
            raise IntroductionRouteError(404, str(exc)) from exc

    @staticmethod
    def _replay(auth: AuthorizedIntroductionRequest) -> Mapping[str, Any] | None:
        if not auth.exact_retry:
            return None
        if auth.recorded_outcome is None:
            raise IntroductionRouteError(409, "request retry is pending")
        status_code, payload = auth.recorded_outcome
        if status_code >= 400:
            raise IntroductionRouteError(status_code, payload)
        if not isinstance(payload, Mapping):
            raise IntroductionRouteError(500, "recorded response is malformed")
        return payload

    def _projection(
        self,
        record: IntroductionRecord,
        *,
        viewer: Identity,
        buyer_principal: Identity,
    ) -> dict[str, Any]:
        return introduction_projection(
            record,
            for_role="buyer" if viewer == buyer_principal else "seller",
            mechanism_id=self._mechanism_id,
        )

    async def start(
        self,
        request_context: Any,
        start: IntroductionStart,
    ) -> Mapping[str, Any]:
        """Persist both contact payloads and complete the introduction claim."""

        agreement = await self._prepare(start.negotiation_id, start.obligation_ref)
        auth = await self._callbacks.authorize(
            request_context,
            "introduction_start",
            agreement.obligation_ref,
            (agreement.buyer_principal,),
            start.model_dump(mode="json"),
        )
        replay = self._replay(auth)
        if replay is not None:
            return replay
        # "First reveal" has to be observed before persisting, because persist
        # is idempotent: a repeat start with a fresh request id is not a replay
        # and returns the same record, and delivering again for it would tell
        # the seller a second time about one introduction.
        already_revealed = (
            self._deliver is not None
            and await self._callbacks.load(agreement.obligation_ref) is not None
        )
        try:
            record = await self._callbacks.persist(
                agreement,
                start.contact_payload,
                self._seller_contact,
            )
        except ValueError as exc:
            raise IntroductionRouteError(409, str(exc)) from exc
        try:
            await self._callbacks.complete(agreement)
        except Exception as exc:
            raise IntroductionRouteError(
                503,
                "introduction completion is temporarily unavailable",
            ) from exc
        if not already_revealed:
            self._deliver_to_seller(record, agreement)
        return self._projection(
            record,
            viewer=auth.principal,
            buyer_principal=agreement.buyer_principal,
        )

    def _deliver_to_seller(
        self,
        record: IntroductionRecord,
        agreement: IntroductionAgreement,
    ) -> None:
        """Tell the seller's own side, once, about a reveal that just happened.

        Reached only for a reveal that had no record before it: the replay
        branch returns above and a repeat start is filtered by the check its
        caller makes, so one introduction is announced once. The seller's view
        is built explicitly here rather than reusing the response projection,
        whose counterparty half belongs to whoever asked.
        """

        if self._deliver is None:
            return
        try:
            self._deliver(
                self._projection(
                    record,
                    viewer=agreement.seller_principal,
                    buyer_principal=agreement.buyer_principal,
                ),
                agreement,
            )
        except Exception:  # noqa: BLE001 - delivery never undoes a settled deal
            pass

    async def read(
        self,
        request_context: Any,
        obligation_ref: str,
    ) -> Mapping[str, Any]:
        """Serve the counterparty payload and agreed context, idempotently."""

        agreement = await self._prepare(None, obligation_ref)
        auth = await self._callbacks.authorize(
            request_context,
            "introduction_read",
            agreement.obligation_ref,
            (agreement.buyer_principal, agreement.seller_principal),
            None,
        )
        replay = self._replay(auth)
        if replay is not None:
            return replay
        record = await self._callbacks.load(agreement.obligation_ref)
        if record is None:
            raise IntroductionRouteError(409, "introduction has not been started")
        return self._projection(
            record,
            viewer=auth.principal,
            buyer_principal=agreement.buyer_principal,
        )


__all__ = [
    "AuthorizedIntroductionRequest",
    "DeliverIntroduction",
    "IntroductionAgreement",
    "IntroductionRecord",
    "IntroductionRouteCallbacks",
    "IntroductionRouteError",
    "IntroductionRouteService",
    "IntroductionStart",
    "introduction_projection",
]
