"""Contact exchange composed over a storefront's accepted state.

Interpreting an accepted deal for this mechanism is the same in every domain:
load the negotiation thread, require it to have succeeded, require a plan with
exactly one contact-exchange obligation, re-derive that obligation's reference,
and drive it to collected. That interpretation lives here once. A composing
storefront supplies only the reads it alone can answer -- its negotiation
thread, its settlement obligation, and the origin its negotiation's binding
recorded -- plus its configuration and route bindings.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Collection, Mapping
from typing import Any, Protocol

from market_core.schemas import SettlementObligation, SettlementPlan
from market_identity import Identity
from market_settlement_runtime import SettlementObligationRecord, derive_obligation_ref

from .introduction_routes import (
    AuthorizeIntroduction,
    introduction_projection,
    DeliverIntroduction,
    IntroductionAgreement,
    IntroductionPayloadsDeletedError,
    IntroductionRecord,
    IntroductionRouteCallbacks,
    IntroductionRouteService,
)
from .retention import IntroductionRetentionPolicy, IntroductionRetentionService
from .settlement_config import (
    MECHANISM,
    ContactSettlementConfig,
    resolve_seller_contact,
    validate_contact_origins,
)
from .store import SQLiteIntroductionStore


class LoadNegotiationThread(Protocol):
    """The storefront's negotiation thread row: terminal state and plan."""

    def __call__(self, *, negotiation_id: str) -> Awaitable[Mapping[str, Any] | None]: ...


class LoadSettlementObligation(Protocol):
    """The storefront's settlement obligation row, for a reference-only read."""

    def __call__(self, obligation_ref: str) -> Awaitable[Mapping[str, Any] | None]: ...


class LoadAgreementOrigin(Protocol):
    """The origin recorded on the negotiation's durable binding, if any."""

    def __call__(self, negotiation_id: str) -> Awaitable[str | None]: ...


class IntroductionSettlementRuntime(Protocol):
    """The settlement-runtime operations the obligation drive uses."""

    def register_plan(self, *, agreement_ref: str, obligations: list[Any]) -> Awaitable[Any]: ...

    def materialize(
        self, *, obligation_ref: str, local_principal: Identity, worker_id: str
    ) -> Awaitable[Any]: ...

    def bind_fulfillment(
        self, obligation_ref: str, fulfillment_ref: str, *, local_principal: Identity
    ) -> Awaitable[Any]: ...

    def check(
        self, *, obligation_ref: str, local_principal: Identity, worker_id: str
    ) -> Awaitable[Any]: ...

    def collect(
        self, *, obligation_ref: str, local_principal: Identity, worker_id: str
    ) -> Awaitable[Any]: ...


async def accepted_introduction(
    *,
    load_thread: LoadNegotiationThread,
    load_origin: LoadAgreementOrigin,
    negotiation_id: str,
    obligation_ref: str,
) -> tuple[IntroductionAgreement, SettlementObligation]:
    """Interpret one accepted introduction deal, or refuse it.

    The ``obligation_ref`` re-derivation is the security check here: it is what
    stops a reveal being requested against an obligation the accepted plan
    does not contain.
    """

    thread = await load_thread(negotiation_id=negotiation_id)
    if thread is None or thread.get("terminal_state") != "success":
        raise ValueError("introduction deal is not accepted")
    plan = SettlementPlan.model_validate(thread.get("settlement_plan"))
    if len(plan.obligations) != 1:
        raise ValueError("introduction agreement must contain one obligation")
    obligation = plan.obligations[0]
    if obligation.mechanism != MECHANISM:
        raise ValueError("accepted deal is not an introduction")
    expected_ref = derive_obligation_ref(
        negotiation_id,
        0,
        obligation.model_dump(mode="json"),
    )
    if expected_ref != obligation_ref:
        raise ValueError("requested obligation does not match the accepted plan")
    package = plan.service_terms.get(MECHANISM)
    return (
        IntroductionAgreement(
            agreement_ref=negotiation_id,
            obligation_ref=obligation_ref,
            buyer_principal=Identity.model_validate(obligation.payer_principal),
            seller_principal=Identity.model_validate(obligation.claimant_principal),
            introduction_package=dict(package) if isinstance(package, Mapping) else {},
            origin=await load_origin(negotiation_id),
        ),
        obligation,
    )


def _worker(operation: str) -> str:
    return f"{operation}:{uuid.uuid4().hex}"


class ContactExchangeComposition:
    """Contact exchange for one storefront, under its running configuration.

    Each product is built from configuration when asked for, so the reveal,
    the retention sweep, an operator's deletion, and every disclosure read the
    same policy. Construction refuses a contact configuration that does not
    fit the storefront's origins, so the mistake surfaces at startup.
    """

    def __init__(
        self,
        *,
        config: Callable[[], ContactSettlementConfig | None],
        store: SQLiteIntroductionStore,
        load_thread: LoadNegotiationThread,
        load_obligation: LoadSettlementObligation,
        load_origin: LoadAgreementOrigin,
        settlement_runtime: IntroductionSettlementRuntime,
        known_origins: Collection[str],
        deliver: DeliverIntroduction | None = None,
    ) -> None:
        self._config = config
        self._store = store
        self._load_thread = load_thread
        self._load_obligation = load_obligation
        self._load_origin = load_origin
        self._settlement_runtime = settlement_runtime
        self._deliver = deliver
        self._known_origins = frozenset(known_origins)
        section = config()
        if section is not None:
            validate_contact_origins(section, known_origins)

    @property
    def store(self) -> SQLiteIntroductionStore:
        return self._store

    def config(self) -> ContactSettlementConfig | None:
        """The contact-exchange section while the mechanism is enabled, else None."""

        return self._config()

    def retention(self) -> IntroductionRetentionService | None:
        """Introduction retention under the running configuration, or None.

        Present whenever contact exchange is enabled, whether or not a contact
        is configured to reveal: payloads already revealed are held under the
        window either way.
        """

        section = self._config()
        if section is None:
            return None
        return IntroductionRetentionService(
            policy=IntroductionRetentionPolicy.from_config(section),
            select_expired=self._store.select_expired,
            delete_payloads=self._store.delete_payloads,
            load=self._store.load,
        )

    def disclosures(self) -> dict[str, dict[str, Any]]:
        """Readiness disclosures, keyed by subject; empty while disabled.

        A buyer weighing whether to start an introduction reads these before
        handing over anything, so the retention window is disclosed here as
        well as in the reveal.
        """

        retention = self.retention()
        if retention is None:
            return {}
        return {"introduction_retention": retention.disclosure()}

    async def _accepted(
        self, negotiation_id: str, obligation_ref: str
    ) -> tuple[IntroductionAgreement, SettlementObligation]:
        return await accepted_introduction(
            load_thread=self._load_thread,
            load_origin=self._load_origin,
            negotiation_id=negotiation_id,
            obligation_ref=obligation_ref,
        )

    def _resolve_seller_contact(
        self, agreement: IntroductionAgreement
    ) -> Mapping[str, str] | None:
        section = self._config()
        if section is None:
            return None
        return resolve_seller_contact(section, agreement.origin, self._known_origins)

    def reveal_service(
        self, authorize: AuthorizeIntroduction
    ) -> IntroductionRouteService | None:
        """The start/read reveal service, or None while the mechanism is disabled."""

        retention = self.retention()
        if retention is None:
            return None

        async def prepare(
            negotiation_id: str | None,
            obligation_ref: str,
        ) -> IntroductionAgreement:
            if negotiation_id is None:
                row = await self._load_obligation(obligation_ref)
                if row is None:
                    raise ValueError("introduction not found")
                negotiation_id = SettlementObligationRecord.model_validate(
                    row
                ).agreement_ref
            agreement, _ = await self._accepted(negotiation_id, obligation_ref)
            return agreement

        async def persist(
            agreement: IntroductionAgreement,
            buyer_contact: Mapping[str, str],
            seller_contact: Mapping[str, str],
        ) -> IntroductionRecord:
            return await self._store.insert(
                IntroductionRecord(
                    obligation_ref=agreement.obligation_ref,
                    agreement_ref=agreement.agreement_ref,
                    buyer_contact=dict(buyer_contact),
                    seller_contact=dict(seller_contact),
                    introduction_package=dict(agreement.introduction_package),
                )
            )

        async def complete(agreement: IntroductionAgreement) -> None:
            """Drive the one non-financial obligation to collected; every step is
            idempotent, so a retried start converges instead of failing."""

            _, obligation = await self._accepted(
                agreement.agreement_ref, agreement.obligation_ref
            )
            runtime = self._settlement_runtime
            await runtime.register_plan(
                agreement_ref=agreement.agreement_ref,
                obligations=[obligation.model_dump(mode="json")],
            )
            await runtime.materialize(
                obligation_ref=agreement.obligation_ref,
                local_principal=agreement.buyer_principal,
                worker_id=_worker("introduction-materialize"),
            )
            await runtime.bind_fulfillment(
                agreement.obligation_ref,
                f"introduction:{agreement.obligation_ref}",
                local_principal=agreement.seller_principal,
            )
            await runtime.check(
                obligation_ref=agreement.obligation_ref,
                local_principal=agreement.seller_principal,
                worker_id=_worker("introduction-check"),
            )
            await runtime.collect(
                obligation_ref=agreement.obligation_ref,
                local_principal=agreement.seller_principal,
                worker_id=_worker("introduction-collect"),
            )

        return IntroductionRouteService(
            callbacks=IntroductionRouteCallbacks(
                prepare=prepare,
                authorize=authorize,
                persist=persist,
                load=self._store.load,
                complete=complete,
            ),
            resolve_seller_contact=self._resolve_seller_contact,
            deliver=self._deliver,
            disclosure=retention.disclosure,
        )

    async def load_revealed(
        self, obligation_ref: str
    ) -> tuple[IntroductionRecord, IntroductionAgreement]:
        """Load one already-revealed introduction and the deal it belongs to.

        The path an operator's re-delivery takes: it reads the durable reveal
        rather than reconstructing one, so a re-send can never invent contact
        data that was never exchanged, and once the payloads are deleted there
        is nothing it may send.
        """

        record = await self._store.load(obligation_ref)
        if record is None:
            raise ValueError("introduction has not been revealed")
        if record.payloads_deleted_at is not None:
            raise IntroductionPayloadsDeletedError(record.payloads_deleted_at)
        agreement, _ = await self._accepted(record.agreement_ref, obligation_ref)
        return record, agreement

    async def seller_view(
        self, obligation_ref: str
    ) -> tuple[dict[str, Any], IntroductionAgreement]:
        """An already-revealed introduction as the seller sees it, for re-delivery."""

        record, agreement = await self.load_revealed(obligation_ref)
        return introduction_projection(record, for_role="seller"), agreement


__all__ = [
    "ContactExchangeComposition",
    "IntroductionSettlementRuntime",
    "LoadAgreementOrigin",
    "LoadNegotiationThread",
    "LoadSettlementObligation",
    "accepted_introduction",
]
