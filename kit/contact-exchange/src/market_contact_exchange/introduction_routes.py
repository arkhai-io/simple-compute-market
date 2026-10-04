"""Framework-free introduction reveal mechanics for accepted contact deals.

Mirrors the hosted settlement route service — signed operations keyed by the
negotiation and obligation ref, authorization delegated to the domain through
callbacks — with inverted durability: the contact payloads persist and the
read is idempotent. An introduction that could be lost to a missed poll would
not be an introduction.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
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
    """Server-authoritative accepted introduction loaded by a domain callback.

    ``origin`` is the listing origin recorded on the negotiation's durable
    binding: the one value the seller's contact and seller-side delivery
    routing are resolved from.
    """

    agreement_ref: str
    obligation_ref: str
    buyer_principal: Identity
    seller_principal: Identity
    introduction_package: Mapping[str, Any]
    origin: str | None = None


@dataclass(frozen=True, slots=True)
class AuthorizedIntroductionRequest:
    """Authentication result returned by the owning storefront boundary."""

    principal: Identity
    exact_retry: bool = False
    recorded_outcome: tuple[int, Any] | None = None


class IntroductionRecord(BaseModel):
    """One durably persisted, idempotently re-readable introduction.

    ``payloads_deleted_at`` is set when the contact payloads were redacted; the
    record then holds empty contacts and remains only as the tombstone that
    stops the introduction being revealed again.
    """

    obligation_ref: str
    agreement_ref: str
    buyer_contact: dict[str, str]
    seller_contact: dict[str, str]
    introduction_package: dict[str, Any] = Field(default_factory=dict)
    payloads_deleted_at: str | None = None


#: The stable code of the outcome every introduction surface answers once the
#: payloads have been deleted.
INTRODUCTION_PAYLOADS_DELETED = "introduction_payloads_deleted"

#: The stable code of a start refused because the agreement's origin resolves
#: no seller contact under the running configuration.
SELLER_CONTACT_UNAVAILABLE = "seller_contact_unavailable"


class IntroductionPayloadsDeletedError(ValueError):
    """The introduction's contact payloads have been deleted.

    A ``ValueError`` so persistence callers that already refuse conflicting
    payloads refuse this too; the route service distinguishes it to answer the
    deleted outcome rather than a conflict.
    """

    def __init__(self, payloads_deleted_at: str) -> None:
        super().__init__("introduction contact payloads have been deleted")
        self.payloads_deleted_at = payloads_deleted_at


def introduction_payloads_deleted_detail(payloads_deleted_at: str) -> dict[str, str]:
    """The deleted outcome's body: its stable code and when deletion happened."""

    return {
        "code": INTRODUCTION_PAYLOADS_DELETED,
        "payloads_deleted_at": payloads_deleted_at,
    }


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


#: Returns the retention disclosure to embed in a reveal, read from the running
#: configuration at each call so a reveal never states a stale window.
IntroductionDisclosure = Callable[[], Mapping[str, Any]]

#: Returns the seller contact for one agreement under the running
#: configuration, or None when its origin has none.
ResolveSellerContact = Callable[[IntroductionAgreement], Mapping[str, str] | None]


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
    retention: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The reveal as one side sees it: the counterparty's half, not its own.

    One definition, so a re-delivery outside the request path shows the
    operator exactly what the reveal itself showed them. A redacted record is
    refused rather than rendered: its contacts are empty, and a projection of
    it would present no contact as though it were a reveal.
    """

    if record.payloads_deleted_at is not None:
        raise IntroductionPayloadsDeletedError(record.payloads_deleted_at)
    counterparty_contact = (
        record.seller_contact if for_role == "buyer" else record.buyer_contact
    )
    projection: dict[str, Any] = {
        "obligation_ref": record.obligation_ref,
        "mechanism": mechanism_id,
        "revealed": True,
        "introduction": dict(record.introduction_package),
        "counterparty_contact": dict(counterparty_contact),
    }
    if retention is not None:
        projection["retention"] = dict(retention)
    return projection


class IntroductionRouteService:
    """Run the signed start/read reveal family over an injected domain contract.

    The seller's contact payload binds from configuration at the first
    introduction operation, resolved from the agreement's origin; acceptance
    stays payload-free by construction, so deals that never start persist no
    contact data at all.
    """

    def __init__(
        self,
        *,
        callbacks: IntroductionRouteCallbacks,
        resolve_seller_contact: ResolveSellerContact,
        mechanism_id: str = MECHANISM,
        deliver: DeliverIntroduction | None = None,
        disclosure: IntroductionDisclosure | None = None,
    ) -> None:
        self._callbacks = callbacks
        self._resolve_seller_contact = resolve_seller_contact
        self._mechanism_id = mechanism_id
        self._deliver = deliver
        self._disclosure = disclosure

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
            retention=self._disclosure() if self._disclosure is not None else None,
        )

    @staticmethod
    def _deleted(payloads_deleted_at: str) -> IntroductionRouteError:
        return IntroductionRouteError(
            410, introduction_payloads_deleted_detail(payloads_deleted_at)
        )

    async def _complete(self, agreement: IntroductionAgreement) -> None:
        try:
            await self._callbacks.complete(agreement)
        except Exception as exc:
            raise IntroductionRouteError(
                503,
                "introduction completion is temporarily unavailable",
            ) from exc

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
        # The record is read before persisting for two reasons. "First reveal"
        # has to be observed before persisting, because persist is idempotent:
        # a repeat start with a fresh request id is not a replay and returns
        # the same record, and delivering again for it would tell the seller a
        # second time about one introduction. And a redacted record must stop
        # the start before anything is persisted or delivered.
        existing = await self._callbacks.load(agreement.obligation_ref)
        if existing is not None and existing.payloads_deleted_at is not None:
            # Completion still runs: it is idempotent, and it is how a deal
            # whose earlier completion failed converges after deletion.
            await self._complete(agreement)
            raise self._deleted(existing.payloads_deleted_at)
        seller_contact = self._seller_contact_for(agreement)
        try:
            record = await self._callbacks.persist(
                agreement,
                start.contact_payload,
                seller_contact,
            )
        except IntroductionPayloadsDeletedError as exc:
            # Redacted between the read above and the persist.
            await self._complete(agreement)
            raise self._deleted(exc.payloads_deleted_at) from exc
        except ValueError as exc:
            raise IntroductionRouteError(409, str(exc)) from exc
        await self._complete(agreement)
        if existing is None:
            self._deliver_to_seller(record, agreement)
        return self._projection(
            record,
            viewer=auth.principal,
            buyer_principal=agreement.buyer_principal,
        )

    def _seller_contact_for(self, agreement: IntroductionAgreement) -> dict[str, str]:
        """The contact configured for this agreement's origin, or a refusal.

        Resolved before anything is persisted, driven, or delivered, and never
        substituted: an origin with no contact refuses the reveal rather than
        revealing another origin's.
        """

        contact = self._resolve_seller_contact(agreement)
        if not contact:
            raise IntroductionRouteError(
                503,
                {
                    "code": SELLER_CONTACT_UNAVAILABLE,
                    "message": "no seller contact is configured for this listing's origin",
                },
            )
        return validate_contact_payload(contact)

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
        if record.payloads_deleted_at is not None:
            raise self._deleted(record.payloads_deleted_at)
        return self._projection(
            record,
            viewer=auth.principal,
            buyer_principal=agreement.buyer_principal,
        )


__all__ = [
    "INTRODUCTION_PAYLOADS_DELETED",
    "SELLER_CONTACT_UNAVAILABLE",
    "AuthorizedIntroductionRequest",
    "DeliverIntroduction",
    "IntroductionAgreement",
    "IntroductionDisclosure",
    "IntroductionPayloadsDeletedError",
    "IntroductionRecord",
    "IntroductionRouteCallbacks",
    "IntroductionRouteError",
    "IntroductionRouteService",
    "IntroductionStart",
    "LoadIntroduction",
    "ResolveSellerContact",
    "introduction_payloads_deleted_detail",
    "introduction_projection",
]
