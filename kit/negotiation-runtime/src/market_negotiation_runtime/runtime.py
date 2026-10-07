"""Schema-opaque synchronous negotiation lifecycle.

The runtime owns protocol order, durable transcript handling, principal checks, and
acceptance chokepoints.  A resolver supplies one authoritative listing binding and
its domain hooks; the runtime never selects a domain from request payloads or
interprets listing, message, proposal, terms, or accepted-artifact schemas.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Protocol

from market_identity import Identity
from market_policy.listing_source import ListingSourceVerdict, classify_listing_source
from market_policy.negotiation_middleware import NegotiationDecision, NegotiationRound

BuyerAction = Literal["counter", "accept", "exit"]
ActorRole = Literal["buyer", "admin"]
StageEventHook = Callable[..., None]


class StorefrontPausedError(Exception):
    """Raised when a new negotiation is attempted while unavailable."""

    def __init__(self, reason: str = "paused") -> None:
        super().__init__(reason)
        self.reason = reason


class OfferUnfulfillableError(Exception):
    """Raised when the seller refuses an otherwise valid opening."""

    def __init__(self, reason: str, *, listing_id: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.listing_id = listing_id


class NegotiationUnavailableError(Exception):
    """Raised when the listing's source cannot be confirmed; a retry may succeed.

    Not a ``ValueError``: nothing about the request or the listing is known to be
    wrong, only not yet known to be right.
    """

    def __init__(self, reason: str, *, listing_id: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.listing_id = listing_id


class NegotiationStateError(ValueError):
    """Raised when durable negotiation state cannot be resumed exactly."""


@dataclass(frozen=True, slots=True)
class NegotiationTerms:
    """Domain-decoded terms plus their exact JSON persistence carrier."""

    decoded: Any
    wire: Mapping[str, Any] | None
    requested_duration_seconds: int | None = None
    requested_start_utc: str | None = None


@dataclass(frozen=True, slots=True)
class AgreementTerms:
    """Protocol fields persisted for one accepted agreement."""

    duration_seconds: int
    start_utc: str | None = None


@dataclass(frozen=True, slots=True)
class RoundRequest:
    """Schema-opaque input to a domain policy adapter."""

    repository: Any
    listing: Any
    listing_record: Mapping[str, Any]
    history: tuple[NegotiationRound, ...]
    terms: NegotiationTerms
    buyer_principal: Identity
    strategy_label: str | None
    # The same opaque binding the runtime resolved and validated for this
    # negotiation. A policy that must judge the listing against its own source
    # reads it here rather than resolving a second time, which could drift from
    # what the runtime checked.
    binding: Any = None
    # The listing checked against its own source for this round, which the
    # domain hands its policy chain; ``None`` where the domain contributes no
    # check. The runtime enforces the verdict itself whatever the chain does.
    listing_source: ListingSourceVerdict | None = None


@dataclass(frozen=True, slots=True)
class RoundEvaluation:
    """Domain-normalized result consumed by the protocol state machine."""

    our_amount: int
    strategy_label: str
    decision: NegotiationDecision
    pinned_proposal: Mapping[str, Any] | None
    uses_scalar_amount: bool
    buyer_amount: int | None = None
    domain_state: Any = None


@dataclass(frozen=True, slots=True)
class OpeningRecord:
    """Accepted round-zero state supplied to an optional domain persistence hook."""

    negotiation_id: str
    listing_id: str
    listing: Any
    listing_record: Mapping[str, Any]
    terms: NegotiationTerms
    buyer_principal: Identity
    seller_principal: Identity
    pinned_proposal: Mapping[str, Any] | None
    evaluation: RoundEvaluation
    binding: Any = None


@dataclass(frozen=True, slots=True)
class Acceptance:
    """Complete immutable input to domain-owned artifact construction."""

    negotiation_id: str
    listing_id: str
    listing: Any
    listing_record: Mapping[str, Any]
    terms: NegotiationTerms
    pinned_proposal: Mapping[str, Any] | None
    agreed_amount: int
    agreement: AgreementTerms
    uses_scalar_amount: bool
    buyer_principal: Identity
    seller_principal: Identity
    policy_state: Any = None
    binding: Any = None


@dataclass(frozen=True, slots=True)
class OpeningPreview:
    """What ``NegotiationRuntime.start`` would decide for an opening.

    ``refused`` is true when the opening would be refused before or by seller
    policy; ``refusal`` then names the refusal and the decision fields are empty.
    """

    listing_id: str
    refused: bool
    refusal: str | None = None
    our_amount: int | None = None
    their_amount: int | None = None
    strategy: str | None = None
    decision: str | None = None
    decision_amount: int | None = None
    decision_proposal: Mapping[str, Any] | None = None
    decision_reason: str | None = None


@dataclass(frozen=True, slots=True)
class _OpeningPlan:
    """Everything an opening establishes before its first durable write."""

    hooks: "NegotiationDomainHooks"
    evaluation: RoundEvaluation
    acceptance: Acceptance
    accepted: bool
    artifacts: dict[str, Any]
    their_amount: int
    decision_amount: int | None


@dataclass(frozen=True, slots=True)
class _ResumedThread:
    """A recorded thread resolved against its binding, ready for a round."""

    listing_id: str
    resolved: "ResolvedNegotiation"
    terms: NegotiationTerms
    pinned_proposal: Mapping[str, Any] | None
    messages: Any
    uses_scalar_amount: bool
    reference_amount: int
    agreement: AgreementTerms


@dataclass(frozen=True, slots=True)
class ResolvedNegotiation:
    """Authoritative domain/listing resolution returned by a composition root."""

    listing_id: str
    listing: Any
    listing_record: Mapping[str, Any]
    hooks: "NegotiationDomainHooks"
    binding: Any = None


class OpeningResolver(Protocol):
    async def __call__(
        self,
        repository: Any,
        listing_id: str,
    ) -> ResolvedNegotiation: ...


class ContinuationResolver(Protocol):
    async def __call__(
        self,
        repository: Any,
        thread: Mapping[str, Any],
    ) -> ResolvedNegotiation: ...


DecodeTermsHook = Callable[[Any], NegotiationTerms]
ValidateOpeningHook = Callable[[Any, Mapping[str, Any], NegotiationTerms], None]
ValidateContinuationHook = Callable[
    [Any, Any, Mapping[str, Any], NegotiationTerms, Mapping[str, Any]],
    Awaitable[None],
]
EvaluateRoundHook = Callable[[RoundRequest], Awaitable[RoundEvaluation]]
DetermineStrategyHook = Callable[[Any, Mapping[str, Any]], str]
#: ``(listing, listing_record, terms, uses_scalar_amount, pinned_proposal)``. The
#: pinned proposal is the buyer's, as recorded on the thread: the option it
#: selects is the one whose rate the seller negotiates from.
ReferenceAmountHook = Callable[
    [Any, Mapping[str, Any], NegotiationTerms, bool, Mapping[str, Any] | None], int
]
AmountFromProposalHook = Callable[[Mapping[str, Any] | None], int | None]
ProposalFromAmountHook = Callable[
    [Mapping[str, Any] | None, int | None], Mapping[str, Any] | None
]
AgreementHook = Callable[
    [Any, Mapping[str, Any], NegotiationTerms], AgreementTerms
]
BuildArtifactsHook = Callable[[Acceptance, bool], Mapping[str, Any]]
PersistOpeningHook = Callable[[Any, OpeningRecord], Awaitable[None]]
PlaceHoldHook = Callable[[Any, Acceptance], Awaitable[None]]
PersistArtifactsHook = Callable[
    [Any, Acceptance, Mapping[str, Any]], Awaitable[None]
]
DecisionWireHook = Callable[[NegotiationDecision], Mapping[str, Any]]
ListingLiveHook = Callable[[Mapping[str, Any]], bool]
ListingPausedHook = Callable[[Any, str], Awaitable[bool]]
#: ``(repository, resolved)``: the listing checked against its own source.
ListingSourceCheckHook = Callable[
    [Any, "ResolvedNegotiation"], Awaitable[ListingSourceVerdict]
]


@dataclass(frozen=True, slots=True)
class NegotiationDomainHooks:
    """Complete injected domain surface required by the kit lifecycle."""

    decode_terms: DecodeTermsHook
    validate_opening: ValidateOpeningHook
    validate_continuation: ValidateContinuationHook
    evaluate_round: EvaluateRoundHook
    determine_strategy: DetermineStrategyHook
    reference_amount: ReferenceAmountHook
    amount_from_proposal: AmountFromProposalHook
    proposal_from_amount: ProposalFromAmountHook
    agreement_terms: AgreementHook
    build_artifacts: BuildArtifactsHook
    decision_wire: DecisionWireHook
    listing_is_live: ListingLiveHook
    listing_is_paused: ListingPausedHook
    storefront_is_paused: Callable[[], bool]
    stage_event: StageEventHook
    persist_opening: PersistOpeningHook | None = None
    place_hold: PlaceHoldHook | None = None
    persist_artifacts: PersistArtifactsHook | None = None
    # Checks the listing against the declaration it was published from before
    # every seller decision and every acceptance. Unset for a domain whose
    # listings derive from no declaration.
    check_listing_source: ListingSourceCheckHook | None = None


#: Refusals an opening raises before or at seller policy; a preview reports them.
_OPENING_REFUSALS = (
    NegotiationStateError,
    NegotiationUnavailableError,
    OfferUnfulfillableError,
    StorefrontPausedError,
    ValueError,
)


class NegotiationRuntime:
    """One signed, durable negotiation state machine for every market domain."""

    def __init__(
        self,
        *,
        resolve_opening: OpeningResolver,
        resolve_continuation: ContinuationResolver,
        id_factory: Callable[[], str] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._resolve_opening = resolve_opening
        self._resolve_continuation = resolve_continuation
        self._id_factory = id_factory or (lambda: "neg_" + uuid.uuid4().hex)
        self._now = now or (lambda: datetime.now(UTC))

    async def start(
        self,
        *,
        repository: Any,
        listing_id: str,
        buyer_principal: Identity | Mapping[str, Any],
        seller_principal: Identity | Mapping[str, Any],
        actor_principal: Identity | Mapping[str, Any],
        proposal: Mapping[str, Any] | None,
        terms: Any,
        seller_agent_url: str,
        buyer_agent_url: str,
    ) -> dict[str, Any]:
        """Create and drive round zero after authenticating the claimed buyer."""

        buyer = Identity.model_validate(buyer_principal)
        actor = Identity.model_validate(actor_principal)
        if actor != buyer:
            raise NegotiationStateError(
                "authenticated actor does not match opening buyer principal"
            )
        plan = await self._plan_opening(
            repository=repository,
            listing_id=listing_id,
            buyer_principal=buyer,
            seller_principal=seller_principal,
            proposal=proposal,
            terms=terms,
            negotiation_id=self._id_factory(),
        )
        hooks = plan.hooks
        evaluation = plan.evaluation
        decision = evaluation.decision
        acceptance = plan.acceptance
        negotiation_id = acceptance.negotiation_id
        decoded_terms = acceptance.terms
        buyer = acceptance.buyer_principal
        seller = acceptance.seller_principal

        await repository.create_negotiation_thread(
            negotiation_id=negotiation_id,
            our_listing_id=listing_id,
            their_listing_id="",
            our_agent_id=seller_agent_url,
            their_agent_id=buyer_agent_url,
            buyer_principal=buyer,
            seller_principal=seller,
            owner_id=seller_agent_url,
            our_initial_price=int(evaluation.our_amount),
            our_strategy=evaluation.strategy_label,
            requested_duration_seconds=decoded_terms.requested_duration_seconds,
            requested_start_utc=decoded_terms.requested_start_utc,
            buyer_escrow_proposal=acceptance.pinned_proposal,
            provision_terms=(
                dict(decoded_terms.wire) if decoded_terms.wire is not None else None
            ),
        )
        await self._append_message(
            repository,
            negotiation_id=negotiation_id,
            sender_principal=buyer,
            sender_role="buyer",
            our_amount=int(evaluation.our_amount),
            their_amount=plan.their_amount,
            proposed_amount=plan.their_amount,
            action_taken="make_offer",
            message_type="offer",
        )
        opening = OpeningRecord(
            negotiation_id=negotiation_id,
            listing_id=listing_id,
            listing=acceptance.listing,
            listing_record=acceptance.listing_record,
            terms=decoded_terms,
            buyer_principal=buyer,
            seller_principal=seller,
            pinned_proposal=acceptance.pinned_proposal,
            evaluation=evaluation,
            binding=acceptance.binding,
        )
        if hooks.persist_opening is not None:
            await hooks.persist_opening(repository, opening)
        terminal_state = await self._record_seller_decision(
            repository=repository,
            negotiation_id=negotiation_id,
            seller_principal=seller,
            our_amount=int(evaluation.our_amount),
            their_amount=plan.their_amount,
            decision=decision,
            decision_amount=plan.decision_amount,
        )
        if plan.accepted:
            await self._commit_acceptance(
                repository, hooks, acceptance, plan.artifacts
            )
        await self._record_terminal_state(repository, negotiation_id, terminal_state)

        hooks.stage_event(
            "negotiation",
            "round_decided",
            negotiation_id=negotiation_id,
            round=0,
            our_amount=int(evaluation.our_amount),
            their_amount=plan.their_amount,
            decision=decision.action,
            decision_amount=(
                int(plan.decision_amount)
                if plan.decision_amount is not None
                else None
            ),
            decision_reason=decision.reason,
        )
        response: dict[str, Any] = {
            "negotiation_id": negotiation_id,
            "buyer_principal": buyer.model_dump(mode="json"),
            "seller_principal": seller.model_dump(mode="json"),
            **dict(hooks.decision_wire(decision)),
            **plan.artifacts,
        }
        if decoded_terms.wire is not None:
            response["accepted_provision_terms"] = dict(decoded_terms.wire)
        return response

    async def preview_opening(
        self,
        *,
        repository: Any,
        listing_id: str,
        buyer_principal: Identity | Mapping[str, Any],
        seller_principal: Identity | Mapping[str, Any],
        proposal: Mapping[str, Any] | None,
        terms: Any,
    ) -> OpeningPreview:
        """Report what ``start`` would decide for this opening, writing nothing.

        Runs the same resolution, decoding, opening validation, pause and
        liveness checks, round-zero evaluation, agreement, and artifact
        construction as ``start`` and stops before the first write. A refusal
        any of those steps would raise is reported, not raised. Unlike ``start``,
        the caller is an administrator previewing on the buyer's behalf, so no
        actor is checked.
        """

        try:
            plan = await self._plan_opening(
                repository=repository,
                listing_id=listing_id,
                buyer_principal=Identity.model_validate(buyer_principal),
                seller_principal=seller_principal,
                proposal=proposal,
                terms=terms,
                negotiation_id="preview",
            )
        except _OPENING_REFUSALS as exc:
            return OpeningPreview(
                listing_id=listing_id,
                refused=True,
                refusal=f"{type(exc).__name__}: {exc}",
            )
        decision = plan.evaluation.decision
        return OpeningPreview(
            listing_id=listing_id,
            refused=False,
            our_amount=int(plan.evaluation.our_amount),
            their_amount=plan.their_amount,
            strategy=plan.evaluation.strategy_label,
            decision=decision.action,
            decision_amount=(
                int(plan.decision_amount) if plan.decision_amount is not None else None
            ),
            decision_proposal=_proposal_mapping(decision.proposal),
            decision_reason=decision.reason,
        )

    async def _plan_opening(
        self,
        *,
        repository: Any,
        listing_id: str,
        buyer_principal: Identity,
        seller_principal: Identity | Mapping[str, Any],
        proposal: Mapping[str, Any] | None,
        terms: Any,
        negotiation_id: str,
    ) -> _OpeningPlan:
        """Every step of an opening that precedes its first durable write."""

        buyer = buyer_principal
        seller = Identity.model_validate(seller_principal)
        resolved = await self._resolve_opening(repository, listing_id)
        self._require_listing_binding(resolved, listing_id)
        hooks = resolved.hooks
        decoded_terms = hooks.decode_terms(terms)
        hooks.validate_opening(
            resolved.listing,
            resolved.listing_record,
            decoded_terms,
        )
        if hooks.storefront_is_paused():
            raise StorefrontPausedError("global")
        if await hooks.listing_is_paused(repository, listing_id):
            raise StorefrontPausedError(f"order:{listing_id}")
        if not hooks.listing_is_live(resolved.listing_record):
            status = resolved.listing_record.get("status")
            raise OfferUnfulfillableError(
                f"listing_not_open (status={status!r})",
                listing_id=listing_id,
            )
        listing_source = await self._listing_source(repository, resolved)

        proposal_wire = (
            proposal.model_dump(mode="json")
            if hasattr(proposal, "model_dump")
            else dict(proposal)
            if proposal is not None
            else None
        )
        opening_history = (
            NegotiationRound(
                round_number=0,
                sender="them",
                action="initial",
                proposal=proposal_wire,
            ),
        )
        try:
            evaluation = await hooks.evaluate_round(
                RoundRequest(
                    repository=repository,
                    listing=resolved.listing,
                    listing_record=resolved.listing_record,
                    history=opening_history,
                    terms=decoded_terms,
                    buyer_principal=buyer,
                    strategy_label=None,
                    binding=resolved.binding,
                    listing_source=listing_source,
                )
            )
        except ValueError as exc:
            if "price-less" in str(exc) or "default_min_price" in str(exc):
                raise OfferUnfulfillableError(
                    "no_floor_price", listing_id=listing_id
                ) from exc
            raise
        self._validate_evaluation(evaluation)
        evaluation = self._enforce_on_decision(
            hooks, listing_source, evaluation, listing_id
        )
        decision = evaluation.decision
        if decision.action == "reject":
            raise OfferUnfulfillableError(
                decision.reason or "rejected",
                listing_id=listing_id,
            )

        pinned_proposal = (
            dict(evaluation.pinned_proposal)
            if evaluation.pinned_proposal is not None
            else proposal_wire
        )
        buyer_amount = hooks.amount_from_proposal(proposal_wire)
        their_amount = int(buyer_amount) if buyer_amount is not None else 0
        agreement = hooks.agreement_terms(
            resolved.listing,
            resolved.listing_record,
            decoded_terms,
        )
        decision_amount = hooks.amount_from_proposal(
            _proposal_mapping(decision.proposal)
        )
        agreed_amount = (
            int(decision_amount)
            if decision_amount is not None
            else int(evaluation.our_amount)
        )
        acceptance = Acceptance(
            negotiation_id=negotiation_id,
            listing_id=listing_id,
            listing=resolved.listing,
            listing_record=resolved.listing_record,
            terms=decoded_terms,
            pinned_proposal=pinned_proposal,
            agreed_amount=agreed_amount,
            agreement=agreement,
            uses_scalar_amount=evaluation.uses_scalar_amount,
            buyer_principal=buyer,
            seller_principal=seller,
            policy_state=evaluation.domain_state,
            binding=resolved.binding,
        )
        accepted = decision.action == "accept"
        return _OpeningPlan(
            hooks=hooks,
            evaluation=evaluation,
            acceptance=acceptance,
            accepted=accepted,
            artifacts=dict(hooks.build_artifacts(acceptance, accepted)),
            their_amount=their_amount,
            decision_amount=decision_amount,
        )

    async def accept_administratively(
        self,
        *,
        repository: Any,
        listing_id: str,
        negotiation_id: str,
        amount: int,
        actor_principal: Identity | Mapping[str, Any],
    ) -> dict[str, Any]:
        """Accept a non-terminal negotiation at an administrator's amount.

        The acceptance is built through the recorded domain's hooks and
        committed through the same path a negotiated acceptance takes, so the
        domain's hold and accepted artifacts are always recorded. The
        administrator is recorded as the accepting author.
        """

        actor = Identity.model_validate(actor_principal)
        thread = await self._load_open_thread(repository, negotiation_id)
        if thread.get("our_listing_id") != listing_id:
            raise NegotiationStateError(
                f"Negotiation {negotiation_id} does not belong to listing {listing_id}"
            )
        resumed = await self._resume_thread(repository, thread, negotiation_id)
        hooks = resumed.resolved.hooks
        self._refuse_incomplete_thread(thread, resumed.messages, negotiation_id)
        await self._enforce_on_acceptance(
            repository, hooks, resumed.resolved, listing_id
        )
        agreed_amount = int(amount)
        acceptance = Acceptance(
            negotiation_id=negotiation_id,
            listing_id=listing_id,
            listing=resumed.resolved.listing,
            listing_record=resumed.resolved.listing_record,
            terms=resumed.terms,
            pinned_proposal=resumed.pinned_proposal,
            agreed_amount=agreed_amount,
            agreement=resumed.agreement,
            uses_scalar_amount=resumed.uses_scalar_amount,
            buyer_principal=Identity.model_validate(thread.get("buyer_principal")),
            seller_principal=Identity.model_validate(thread.get("seller_principal")),
            binding=resumed.resolved.binding,
        )
        artifacts = dict(hooks.build_artifacts(acceptance, True))
        await self._append_message(
            repository,
            negotiation_id=negotiation_id,
            sender_principal=actor,
            sender_role="admin",
            our_amount=agreed_amount,
            their_amount=agreed_amount,
            proposed_amount=agreed_amount,
            action_taken="accept_offer",
            message_type="accepted",
        )
        await self._commit_acceptance(repository, hooks, acceptance, artifacts)
        await self._record_terminal_state(repository, negotiation_id, "success")
        hooks.stage_event(
            "negotiation",
            "force_accepted",
            negotiation_id=negotiation_id,
            listing_id=listing_id,
            agreed_amount=agreed_amount,
            source="admin",
            actor_principal=actor.model_dump(mode="json"),
        )
        return {
            "negotiation_id": negotiation_id,
            "listing_id": listing_id,
            "action": "accept",
            "amount": agreed_amount,
            "source": "admin_force_accept",
            **artifacts,
        }

    async def _load_open_thread(
        self, repository: Any, negotiation_id: str
    ) -> Mapping[str, Any]:
        thread = await repository.load_negotiation_thread_row(
            negotiation_id=negotiation_id
        )
        if not thread:
            raise NegotiationStateError(f"Unknown negotiation {negotiation_id}")
        if thread.get("terminal_state"):
            raise NegotiationStateError(
                f"Negotiation {negotiation_id} is already in terminal state "
                f"{thread.get('terminal_state')!r}"
            )
        return thread

    async def _resume_thread(
        self, repository: Any, thread: Mapping[str, Any], negotiation_id: str
    ) -> _ResumedThread:
        """Resolve a recorded thread's binding and the values every round reads."""

        listing_id = thread.get("our_listing_id")
        if not isinstance(listing_id, str) or not listing_id:
            raise NegotiationStateError(
                f"Negotiation {negotiation_id} has no recorded listing"
            )
        resolved = await self._resolve_continuation(repository, thread)
        self._require_listing_binding(resolved, listing_id)
        hooks = resolved.hooks
        decoded_terms = hooks.decode_terms(thread.get("provision_terms"))
        await hooks.validate_continuation(
            repository,
            resolved.listing,
            resolved.listing_record,
            decoded_terms,
            thread,
        )
        pinned_proposal = _stored_mapping(thread.get("buyer_escrow_proposal"))
        messages = await repository.load_negotiation_thread(
            negotiation_id=negotiation_id
        )
        uses_scalar_amount = hooks.amount_from_proposal(pinned_proposal) is not None
        return _ResumedThread(
            listing_id=listing_id,
            resolved=resolved,
            terms=decoded_terms,
            pinned_proposal=pinned_proposal,
            messages=messages,
            uses_scalar_amount=uses_scalar_amount,
            reference_amount=hooks.reference_amount(
                resolved.listing,
                resolved.listing_record,
                decoded_terms,
                uses_scalar_amount,
                pinned_proposal,
            ),
            agreement=hooks.agreement_terms(
                resolved.listing,
                resolved.listing_record,
                decoded_terms,
            ),
        )

    async def continue_negotiation(
        self,
        *,
        repository: Any,
        negotiation_id: str,
        buyer_action: BuyerAction,
        buyer_proposal: Mapping[str, Any] | None,
        buyer_reason: str | None,
        buyer_principal: Identity | Mapping[str, Any],
        actor_principal: Identity | Mapping[str, Any],
        actor_role: ActorRole,
        seller_principal: Identity | Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Resume only the exact durable thread and its recorded domain binding."""

        thread = await self._load_open_thread(repository, negotiation_id)
        stored_buyer = Identity.model_validate(thread.get("buyer_principal"))
        stored_seller = Identity.model_validate(thread.get("seller_principal"))
        expected_buyer = Identity.model_validate(buyer_principal)
        actor = Identity.model_validate(actor_principal)
        if expected_buyer != stored_buyer:
            raise NegotiationStateError(
                "buyer principal does not own this negotiation"
            )
        if seller_principal is not None:
            expected_seller = Identity.model_validate(seller_principal)
            if expected_seller != stored_seller:
                raise NegotiationStateError(
                    "seller principal does not own this negotiation"
                )
        if actor_role == "buyer" and actor != stored_buyer:
            raise NegotiationStateError(
                "authenticated actor does not match negotiation buyer"
            )
        if actor_role not in ("buyer", "admin"):
            raise NegotiationStateError(
                f"unsupported negotiation actor role {actor_role!r}"
            )

        resumed = await self._resume_thread(repository, thread, negotiation_id)
        listing_id = resumed.listing_id
        resolved = resumed.resolved
        hooks = resolved.hooks
        decoded_terms = resumed.terms
        pinned_proposal = resumed.pinned_proposal
        messages = resumed.messages
        history = self._history_from_messages(
            messages=messages,
            seller_principal=stored_seller,
            buyer_principal=stored_buyer,
            pinned_proposal=pinned_proposal,
            proposal_from_amount=hooks.proposal_from_amount,
        )
        uses_scalar_amount = resumed.uses_scalar_amount
        reference_amount = resumed.reference_amount
        agreement = resumed.agreement
        if buyer_action != "exit":
            # A buyer may always leave, including a thread an interrupted request
            # left incomplete or whose listing's source cannot be reached.
            self._refuse_incomplete_thread(thread, messages, negotiation_id)

        if buyer_action == "accept":
            await self._enforce_on_acceptance(repository, hooks, resolved, listing_id)
            accepted_amount = self._last_seller_amount(
                messages,
                stored_seller,
                fallback=reference_amount,
            )
            acceptance = Acceptance(
                negotiation_id=negotiation_id,
                listing_id=listing_id,
                listing=resolved.listing,
                listing_record=resolved.listing_record,
                terms=decoded_terms,
                pinned_proposal=pinned_proposal,
                agreed_amount=accepted_amount,
                agreement=agreement,
                uses_scalar_amount=uses_scalar_amount,
                buyer_principal=stored_buyer,
                seller_principal=stored_seller,
                binding=resolved.binding,
            )
            artifacts = dict(hooks.build_artifacts(acceptance, True))
            await self._append_message(
                repository,
                negotiation_id=negotiation_id,
                sender_principal=actor,
                sender_role=actor_role,
                our_amount=reference_amount,
                their_amount=accepted_amount,
                proposed_amount=accepted_amount,
                action_taken="accept_offer",
                message_type="accepted",
            )
            await self._commit_acceptance(repository, hooks, acceptance, artifacts)
            await self._record_terminal_state(repository, negotiation_id, "success")
            hooks.stage_event(
                "negotiation",
                "accepted",
                negotiation_id=negotiation_id,
                agreed_amount=accepted_amount,
                our_initial_amount=reference_amount,
            )
            return {
                "action": "accept",
                "buyer_principal": stored_buyer.model_dump(mode="json"),
                "seller_principal": stored_seller.model_dump(mode="json"),
                **artifacts,
            }

        if buyer_action == "exit":
            await self._append_message(
                repository,
                negotiation_id=negotiation_id,
                sender_principal=actor,
                sender_role=actor_role,
                our_amount=reference_amount,
                their_amount=None,
                proposed_amount=None,
                action_taken="exit_negotiation",
                message_type="exit",
            )
            await repository.update_negotiation_thread_terminal(
                negotiation_id=negotiation_id,
                terminal_state="failure",
            )
            hooks.stage_event(
                "negotiation",
                "exited",
                negotiation_id=negotiation_id,
                reason=buyer_reason or "buyer_exit",
            )
            return {
                "action": "exit",
                "reason": "buyer_exit",
                "buyer_principal": stored_buyer.model_dump(mode="json"),
                "seller_principal": stored_seller.model_dump(mode="json"),
            }

        if buyer_action != "counter":
            raise NegotiationStateError(
                f"Unsupported buyer action {buyer_action!r}"
            )
        proposal_wire = (
            dict(buyer_proposal) if buyer_proposal is not None else pinned_proposal
        )
        listing_source = await self._listing_source(repository, resolved)
        incoming_round = len(history)
        round_history = (*history, NegotiationRound(
            round_number=incoming_round,
            sender="them",
            action="counter",
            proposal=proposal_wire,
        ))
        evaluation = await hooks.evaluate_round(
            RoundRequest(
                repository=repository,
                listing=resolved.listing,
                listing_record=resolved.listing_record,
                history=round_history,
                terms=decoded_terms,
                buyer_principal=stored_buyer,
                strategy_label=hooks.determine_strategy(
                    resolved.listing,
                    resolved.listing_record,
                ),
                binding=resolved.binding,
                listing_source=listing_source,
            )
        )
        self._validate_evaluation(evaluation)
        evaluation = self._enforce_on_decision(
            hooks, listing_source, evaluation, listing_id
        )
        fallback_buyer_amount = hooks.amount_from_proposal(proposal_wire)
        buyer_amount = (
            int(evaluation.buyer_amount)
            if evaluation.buyer_amount is not None
            else int(fallback_buyer_amount)
            if fallback_buyer_amount is not None
            else 0
        )
        decision = evaluation.decision
        decision_amount = hooks.amount_from_proposal(
            _proposal_mapping(decision.proposal)
        )
        agreed_amount = (
            int(decision_amount)
            if decision_amount is not None
            else int(evaluation.our_amount)
        )
        acceptance = Acceptance(
            negotiation_id=negotiation_id,
            listing_id=listing_id,
            listing=resolved.listing,
            listing_record=resolved.listing_record,
            terms=decoded_terms,
            pinned_proposal=pinned_proposal,
            agreed_amount=agreed_amount,
            agreement=agreement,
            uses_scalar_amount=evaluation.uses_scalar_amount,
            buyer_principal=stored_buyer,
            seller_principal=stored_seller,
            policy_state=evaluation.domain_state,
            binding=resolved.binding,
        )
        accepted = decision.action == "accept"
        artifacts = (
            dict(hooks.build_artifacts(acceptance, True)) if accepted else {}
        )

        await self._append_message(
            repository,
            negotiation_id=negotiation_id,
            sender_principal=actor,
            sender_role=actor_role,
            our_amount=int(evaluation.our_amount),
            their_amount=buyer_amount,
            proposed_amount=buyer_amount,
            action_taken="counter_offer",
            message_type="counter_proposal",
        )
        terminal_state = await self._record_seller_decision(
            repository=repository,
            negotiation_id=negotiation_id,
            seller_principal=stored_seller,
            our_amount=int(evaluation.our_amount),
            their_amount=buyer_amount,
            decision=decision,
            decision_amount=decision_amount,
        )
        if accepted:
            await self._commit_acceptance(repository, hooks, acceptance, artifacts)
        await self._record_terminal_state(repository, negotiation_id, terminal_state)
        hooks.stage_event(
            "negotiation",
            "round_decided",
            negotiation_id=negotiation_id,
            round=self._seller_decision_round(messages, stored_seller),
            our_amount=int(evaluation.our_amount),
            their_amount=buyer_amount,
            decision=decision.action,
            decision_amount=(
                int(decision_amount) if decision_amount is not None else None
            ),
            decision_reason=decision.reason,
        )
        return {
            **dict(hooks.decision_wire(decision)),
            "buyer_principal": stored_buyer.model_dump(mode="json"),
            "seller_principal": stored_seller.model_dump(mode="json"),
            **artifacts,
        }

    @staticmethod
    def _require_listing_binding(
        resolved: ResolvedNegotiation,
        expected_listing_id: str,
    ) -> None:
        if resolved.listing_id != expected_listing_id:
            raise NegotiationStateError(
                "resolved listing does not match recorded negotiation listing"
            )

    @staticmethod
    def _validate_evaluation(evaluation: RoundEvaluation) -> None:
        if evaluation.decision.action not in {
            "counter",
            "accept",
            "exit",
            "reject",
        }:
            raise NegotiationStateError(
                f"unsupported seller decision {evaluation.decision.action!r}"
            )
        if not evaluation.strategy_label:
            raise NegotiationStateError("domain policy returned no strategy label")

    async def _commit_acceptance(
        self,
        repository: Any,
        hooks: NegotiationDomainHooks,
        acceptance: Acceptance,
        artifacts: Mapping[str, Any],
    ) -> None:
        await repository.commit_agreed_terms(
            negotiation_id=acceptance.negotiation_id,
            agreed_price=acceptance.agreed_amount,
            agreed_duration_seconds=acceptance.agreement.duration_seconds,
            agreed_start_utc=acceptance.agreement.start_utc,
        )
        if hooks.place_hold is not None:
            await hooks.place_hold(repository, acceptance)
        if hooks.persist_artifacts is not None:
            await hooks.persist_artifacts(repository, acceptance, artifacts)

    async def _append_message(
        self,
        repository: Any,
        *,
        negotiation_id: str,
        sender_principal: Identity,
        sender_role: str,
        our_amount: int | None,
        their_amount: int | None,
        proposed_amount: int | None,
        action_taken: str,
        message_type: str,
    ) -> int:
        return await repository.save_negotiation_message(
            negotiation_id=negotiation_id,
            round=None,
            sender_principal=sender_principal,
            sender_role=sender_role,
            our_price=our_amount,
            their_price=their_amount,
            proposed_price=proposed_amount,
            action_taken=action_taken,
            message_type=message_type,
            timestamp=self._now().isoformat(),
        )

    async def _record_seller_decision(
        self,
        *,
        repository: Any,
        negotiation_id: str,
        seller_principal: Identity,
        our_amount: int,
        their_amount: int,
        decision: NegotiationDecision,
        decision_amount: int | None,
    ) -> str | None:
        """Record the seller's message; return the terminal state it implies.

        The caller records that state, so an acceptance's state is written only
        after the acceptance itself is.
        """
        actions = {
            "counter": ("counter_offer", "counter_proposal", None),
            "accept": ("accept_offer", "accepted", "success"),
            "exit": ("exit_negotiation", "exit", "failure"),
            "reject": ("exit_negotiation", "exit", "failure"),
        }
        action_taken, message_type, terminal = actions[decision.action]
        await self._append_message(
            repository,
            negotiation_id=negotiation_id,
            sender_principal=seller_principal,
            sender_role="seller",
            our_amount=our_amount,
            their_amount=their_amount,
            proposed_amount=(
                decision_amount if decision_amount is not None else their_amount
            ),
            action_taken=action_taken,
            message_type=message_type,
        )
        return terminal

    @staticmethod
    async def _record_terminal_state(
        repository: Any, negotiation_id: str, terminal_state: str | None
    ) -> None:
        if terminal_state is not None:
            await repository.update_negotiation_thread_terminal(
                negotiation_id=negotiation_id,
                terminal_state=terminal_state,
            )

    @staticmethod
    async def _listing_source(
        repository: Any, resolved: ResolvedNegotiation
    ) -> ListingSourceVerdict | None:
        check = resolved.hooks.check_listing_source
        return None if check is None else await check(repository, resolved)

    @staticmethod
    def _enforce_on_decision(
        hooks: NegotiationDomainHooks,
        listing_source: ListingSourceVerdict | None,
        evaluation: RoundEvaluation,
        listing_id: str,
    ) -> RoundEvaluation:
        """Apply the source verdict to a seller decision, whatever the chain did.

        Applied after the chain so its guards refuse a malformed request for its
        own reason first; a decision that already ends the round stands.
        """
        if hooks.check_listing_source is None or evaluation.decision.action in {
            "reject",
            "exit",
        }:
            return evaluation
        refusal = classify_listing_source(listing_source)
        if refusal is None:
            return evaluation
        if refusal.retryable:
            raise NegotiationUnavailableError(refusal.reason, listing_id=listing_id)
        return replace(
            evaluation,
            decision=NegotiationDecision(action="reject", reason=refusal.reason),
        )

    async def _enforce_on_acceptance(
        self,
        repository: Any,
        hooks: NegotiationDomainHooks,
        resolved: ResolvedNegotiation,
        listing_id: str,
    ) -> None:
        """Refuse an acceptance whose listing its source no longer supports.

        Checked before the acceptance writes anything.
        """
        if hooks.check_listing_source is None:
            return
        refusal = classify_listing_source(
            await self._listing_source(repository, resolved)
        )
        if refusal is None:
            return
        if refusal.retryable:
            raise NegotiationUnavailableError(refusal.reason, listing_id=listing_id)
        raise OfferUnfulfillableError(refusal.reason, listing_id=listing_id)

    @staticmethod
    def _refuse_incomplete_thread(
        thread: Mapping[str, Any],
        messages: list[Mapping[str, Any]],
        negotiation_id: str,
    ) -> None:
        """Refuse to resume a thread an interrupted request left incomplete.

        A thread open for another round ends with the seller's counter, the offer
        a buyer's accept takes. One that ends otherwise was interrupted after the
        buyer's message and before the seller's decision (at the opening or in a
        later round), or while an acceptance was being recorded; so was one whose
        agreed terms or plan are already recorded. None is resumed: the buyer may
        exit, and the negotiation watchdog abandons it.
        """
        last = messages[-1] if messages else None
        ends_with_seller_counter = (
            last is not None
            and last.get("sender_role") == "seller"
            and last.get("action_taken") == "counter_offer"
        )
        if (
            not ends_with_seller_counter
            or thread.get("agreed_at")
            or thread.get("settlement_plan")
        ):
            raise NegotiationStateError(
                f"Negotiation {negotiation_id} was interrupted before it was complete "
                "and cannot be resumed"
            )

    @staticmethod
    def _history_from_messages(
        *,
        messages: list[Mapping[str, Any]],
        seller_principal: Identity,
        buyer_principal: Identity,
        pinned_proposal: Mapping[str, Any] | None,
        proposal_from_amount: ProposalFromAmountHook,
    ) -> tuple[NegotiationRound, ...]:
        history: list[NegotiationRound] = []
        expected_round = 0
        for message in messages:
            round_number = message.get("round")
            if round_number != expected_round:
                raise NegotiationStateError(
                    "negotiation transcript round sequence is not contiguous"
                )
            expected_round += 1
            role = message.get("sender_role")
            principal = Identity.model_validate(message.get("sender_principal"))
            if role == "seller":
                if principal != seller_principal:
                    raise NegotiationStateError(
                        "seller transcript principal does not match negotiation"
                    )
                sender: Literal["us", "them"] = "us"
            elif role == "buyer":
                if principal != buyer_principal:
                    raise NegotiationStateError(
                        "buyer transcript principal does not match negotiation"
                    )
                sender = "them"
            elif role == "admin":
                sender = "them"
            else:
                raise NegotiationStateError(
                    f"unsupported transcript sender role {role!r}"
                )
            action = _stored_action(message.get("action_taken"))
            amount = _stored_amount(message.get("proposed_price"))
            history.append(
                NegotiationRound(
                    round_number=round_number,
                    sender=sender,
                    action=action,
                    proposal=proposal_from_amount(pinned_proposal, amount),
                )
            )
        return tuple(history)

    @staticmethod
    def _last_seller_amount(
        messages: list[Mapping[str, Any]],
        seller_principal: Identity,
        *,
        fallback: int,
    ) -> int:
        seller_wire = seller_principal.model_dump(mode="json")
        for message in reversed(messages):
            if (
                message.get("action_taken") == "counter_offer"
                and message.get("sender_principal") == seller_wire
            ):
                amount = _stored_amount(message.get("proposed_price"))
                if amount is None:
                    raise NegotiationStateError(
                        "seller counter has no recoverable amount"
                    )
                return amount
        return int(fallback)

    @staticmethod
    def _seller_decision_round(
        messages: list[Mapping[str, Any]],
        seller_principal: Identity,
    ) -> int:
        seller_wire = seller_principal.model_dump(mode="json")
        return 1 + sum(
            1
            for message in messages
            if message.get("sender_principal") == seller_wire
            and message.get("action_taken") == "counter_offer"
        )


def _stored_action(value: Any) -> Literal[
    "initial", "counter", "accept", "exit", "reject"
]:
    actions: dict[str, Literal["initial", "counter", "accept", "exit", "reject"]] = {
        "make_offer": "initial",
        "counter_offer": "counter",
        "accept_offer": "accept",
        "exit_negotiation": "exit",
    }
    try:
        return actions[str(value)]
    except KeyError as exc:
        raise NegotiationStateError(
            f"unsupported persisted negotiation action {value!r}"
        ) from exc


def _stored_amount(value: Any) -> int | None:
    try:
        return int(Decimal(str(value))) if value is not None else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def _stored_mapping(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return dict(value)
    raise NegotiationStateError("persisted negotiation payload is not an object")


def _proposal_mapping(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        if isinstance(dumped, Mapping):
            return dict(dumped)
    raise NegotiationStateError("domain decision proposal is not an object")
