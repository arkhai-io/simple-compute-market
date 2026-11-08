"""One compute deal's delivery order, driven a step at a time.

``drive`` reconciles what the deal's records say before it acts and is safe to
repeat: a lost acknowledgement at any step is recovered by repeating that step
against the same resource, never by placing another. Its order is the
Agreement window, commit, the future-start wait, dispatch, readiness,
activation, billing start, availability and the domain's continuation; an
undelivered deal is handed to the end operation instead. The caller serializes
drives of one deal, as each domain's claim or lock already does.

See openspec/specs/compute-delivery/spec.md.
"""

from __future__ import annotations

import base64
import logging
import sqlite3
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any, TypeVar

from compute_provisioning_contracts import (
    FulfillmentAcceptanceResponse,
    FulfillmentRequestBody,
    FulfillmentStatusResponse,
    LeaseState,
    LeaseView,
)
from market_capacity_publication import CapacityEffects
from market_core import VersionedEnvelope
from market_deal_lifecycle.delivery import (
    ActivatedDeliveryRef,
    DeliveryAuthorization,
    DeliveryEvidence,
    DeliveryPhase,
    ReadyEvidenceRef,
)
from market_deal_lifecycle_contracts.models import Accepted, EvidenceItem, Rejected
from market_deal_servicing import (
    Admission,
    Classification,
    DeliveryRecord,
    EndService,
    EndSession,
    FinalRequest,
)
from market_deal_servicing.evidence import EvidenceSession, in_transaction
from market_deal_servicing.journal import ClassificationKind
from market_identity import canonical_json
from market_site_client import SiteCapacityAuthenticationError, SiteCapacityClientError
from pydantic import ValidationError

from .outcome import AccessRefused, DeliveryOutcome, OutcomeKind, RepairReason
from .ports import (
    AcceptedDeal,
    AcceptedHold,
    ComputeDeliveryDomain,
    ContinuationState,
    DeliveryProgress,
    DeliveryStep,
    ReserveClaim,
    SiteFulfillment,
)
from .progress import Progress, ProgressUnreadable, read_progress, recorded_identities
from .window import (
    AgreementWindow,
    TimingInvalid,
    agreement_window,
    require_committed_window,
    utc_seconds,
)

logger = logging.getLogger(__name__)

#: Reservation states in which the site holds no capacity for the reservation.
_RELEASED_STATES = frozenset({"released", "force_released"})
#: Fulfillment states of a create that has not settled yet.
_SETTLING_STATES = frozenset({"assigned", "dispatch_pending", "dispatching"})
#: Fulfillment states in which the dispatched resource never became, or no
#: longer is, available: its create failed or was abandoned, or it is torn down.
_UNDELIVERED_STATES = frozenset({
    "failed", "abandoned", "teardown_dispatch_pending", "tearing_down", "teardown_failed", "torn_down",
})
#: Lease states a refused activation is explained by: an end claimed the lease.
_ENDING_LEASE_STATES = frozenset({LeaseState.RELEASING, LeaseState.RELEASED})

T = TypeVar("T")


def _site_refused(exc: SiteCapacityClientError) -> bool:
    """A site answer that refuses the effect, as opposed to no usable answer.

    A signed 404 or 409 is the site's decision. An unsigned answer, a transport
    failure or any other status says nothing about what the site recorded, so
    the effect may have happened and is repeated, never replaced.
    """
    return not isinstance(exc, SiteCapacityAuthenticationError) and exc.status_code in (404, 409)


@dataclass
class _Deal:
    negotiation_id: str
    record: DeliveryRecord
    window: AgreementWindow
    accepted: AcceptedDeal
    progress: Progress

    @property
    def site_id(self) -> str:
        return self.accepted.binding.site_id

    def evidence(self, phase: DeliveryPhase, ready: ReadyEvidenceRef | None = None) -> DeliveryEvidence:
        """The evidence a phase is authorized on: only what is fixed before it starts.

        End service journals an authorization under its phase and admission
        revision, and refuses a retry at the same revision whose evidence
        differs. So commit, which may place the reservation, binds only the
        commitment; dispatch adds the reservation it dispatches; billing start
        and disclosure bind the whole delivered bundle, the same one billing
        start journals.
        """
        if phase is DeliveryPhase.COMMIT:
            return DeliveryEvidence(
                negotiation_id=self.negotiation_id, commitment_ref=self.record.commitment_ref,
            )
        if phase is DeliveryPhase.DISPATCH:
            return DeliveryEvidence(
                negotiation_id=self.negotiation_id, commitment_ref=self.record.commitment_ref,
                reservation_ref=self.progress.capacity_reservation_id,
            )
        reservation_id = self.progress.capacity_reservation_id
        activated_at = self.progress.activated_at
        assert reservation_id is not None and activated_at is not None
        return DeliveryEvidence(
            negotiation_id=self.negotiation_id,
            commitment_ref=self.record.commitment_ref,
            reservation_ref=reservation_id,
            fulfillment_ref=self.progress.fulfillment_id,
            # The reservation identity is the activation's stable reference.
            activated_delivery=ActivatedDeliveryRef(record_ref=reservation_id, activated_at=activated_at),
            ready=ready,
        )


@dataclass(frozen=True)
class _Failure:
    """A seller-side failure the path observed, handed to the end operation.

    ``source_ref`` is fixed by what failed, so a retry finds the end it already
    recorded rather than recording a second one.
    """

    kind: ClassificationKind
    cause: str
    source_ref: str
    evidence: Mapping[str, Any]


@dataclass(frozen=True)
class _Snapshot:
    record: DeliveryRecord | None
    recorded: object
    #: Why a servicing record that exists could not be read, and how.
    unreadable: tuple[RepairReason, str] | None = None


class ComputeDeliveryPath:
    """The compute family's delivery order over one storefront's two ports.

    ``end`` is the storefront's end service; the path opens its transactions on
    the database end service journals to, and reads time from end service's
    clock, so admission and the path agree on the instant.
    """

    def __init__(
        self,
        *,
        end: EndService,
        progress: DeliveryProgress,
        domain: ComputeDeliveryDomain,
        capacity: CapacityEffects,
        fulfillment: SiteFulfillment,
    ) -> None:
        self._end = end
        self._progress = progress
        self._domain = domain
        self._capacity = capacity
        self._fulfillment = fulfillment
        self._clock: Callable[[], int] = end.clock

    async def _transaction(self, operation: Callable[[sqlite3.Connection], Any]) -> Any:
        return await in_transaction(self._end.path, operation)

    async def drive(self, negotiation_id: str) -> DeliveryOutcome:
        """Advance one deal as far as it can go now, and report where it stands.

        An exception from a fulfillment or lease read, or from billing start's
        payment authority, propagates with every step before it recorded, so
        the next drive resumes there.
        """
        nid = negotiation_id
        snapshot: _Snapshot = await self._transaction(lambda conn: self._snapshot(conn, nid))
        reservation_id, fulfillment_id = recorded_identities(snapshot.recorded)
        if snapshot.unreadable is not None:
            reason, detail = snapshot.unreadable
            return self._repair(reason, reservation_id, fulfillment_id, f"servicing_delivery:{nid}", detail)
        if snapshot.record is None:
            return self._repair(
                RepairReason.NO_ACCEPTED_DEAL, reservation_id, fulfillment_id,
                f"servicing_delivery:{nid}", "the deal has no servicing delivery record",
            )
        record = snapshot.record
        try:
            window = agreement_window(record)
        except TimingInvalid as exc:
            return self._repair(
                RepairReason.TIMING_INVALID, reservation_id, fulfillment_id,
                f"servicing_delivery:{nid}", str(exc),
            )
        accepted = await self._domain.accepted_deal(nid)
        if accepted is None:
            return self._repair(
                RepairReason.NO_ACCEPTED_DEAL, reservation_id, fulfillment_id,
                f"settlement:{nid}", "the deal has no verified settlement evidence",
            )
        if not isinstance(accepted, AcceptedDeal):
            return self._repair(
                RepairReason.DOMAIN_RESULT_INVALID, reservation_id, fulfillment_id,
                f"settlement:{nid}", f"accepted_deal returned {type(accepted).__name__}",
            )
        if accepted.commitment_ref != record.commitment_ref:
            return self._repair(
                RepairReason.NO_ACCEPTED_DEAL, reservation_id, fulfillment_id,
                f"settlement:{nid}", "verified settlement names another commitment",
            )
        if snapshot.recorded is None:
            admission: Admission = await self._transaction(lambda conn: self._start(conn, nid))
            progress = Progress(DeliveryStep.RESERVE)
            deal = _Deal(nid, record, window, accepted, progress)
            if admission.status == "ended":
                return await self._ended(deal)
            if admission.status == "retry":
                return self._outcome(OutcomeKind.PENDING, deal, detail="stale admission revision")
        else:
            try:
                progress = read_progress(snapshot.recorded)
            except ProgressUnreadable as exc:
                return self._repair(
                    RepairReason.PROGRESS_UNREADABLE, reservation_id, fulfillment_id,
                    f"delivery_progress:{nid}", str(exc),
                )
            deal = _Deal(nid, record, window, accepted, progress)
        return await self._advance(deal)

    def _snapshot(self, conn: sqlite3.Connection, nid: str) -> _Snapshot:
        try:
            record = EndSession(conn).read(nid)
        except KeyError:
            record = None
        except ValidationError as exc:
            problems = "; ".join(
                ".".join(str(part) for part in error["loc"]) + " " + error["msg"].lower()
                for error in exc.errors()
            )
            # The record's only whole-model check is its term's order.
            timing = all(error["loc"][:1] in ((), ("start_at",), ("term_end",)) for error in exc.errors())
            return _Snapshot(None, self._progress.load(conn, nid), unreadable=(
                RepairReason.TIMING_INVALID if timing else RepairReason.NO_ACCEPTED_DEAL,
                "the servicing delivery record is unreadable: " + problems,
            ))
        return _Snapshot(record, self._progress.load(conn, nid))

    def _start(self, conn: sqlite3.Connection, nid: str) -> Admission:
        """Create the progress row under admission for ``reserve``, in one transaction."""
        session = EndSession(conn)
        record = session.read(nid)
        admission = session.admit(nid, DeliveryPhase.RESERVE, record.revision, now=self._clock())
        if admission.status == "admitted":
            self._progress.create(conn, nid)
        return admission

    async def _advance(self, deal: _Deal) -> DeliveryOutcome:
        if deal.progress.step in (DeliveryStep.RESERVE, DeliveryStep.COMMIT):
            outcome = await self._commit(deal)
            if outcome is not None:
                return outcome
            if self._clock() < deal.window.start:
                # Capacity is committed; nothing physical, financial or
                # disclosed happens before the Agreement start. The domain's
                # worker brings the deal back, and admission is checked again.
                await self._transaction(
                    lambda conn: self._progress.release_claim(conn, deal.negotiation_id)
                )
                return self._outcome(OutcomeKind.WAITING, deal, wake_at=deal.window.start)
        if deal.progress.step in (DeliveryStep.COMMIT, DeliveryStep.DISPATCH):
            outcome = await self._dispatch(deal)
            if outcome is not None:
                return outcome
        return await self._fulfil(deal)

    # -- commit ------------------------------------------------------------

    async def _commit(self, deal: _Deal) -> DeliveryOutcome | None:
        """Hold the Agreement window at the site under the deal's one reservation."""
        claim = await self._domain.reserve_claim(deal.negotiation_id)
        if not isinstance(claim, ReserveClaim):
            return self._repair_deal(
                deal, RepairReason.DOMAIN_RESULT_INVALID, f"reserve_claim:{deal.negotiation_id}",
                f"reserve_claim returned {type(claim).__name__}",
            )
        blocked = await self._authorized(deal, DeliveryPhase.COMMIT)
        if blocked is not None:
            return blocked
        if deal.progress.capacity_reservation_id is None:
            placed = await self._place(deal, claim)
            if isinstance(placed, DeliveryOutcome):
                return placed
            if placed:
                return None
        reservation_id = deal.progress.capacity_reservation_id
        assert reservation_id is not None
        answer = await self._site_commit(deal, reservation_id, claim)
        if isinstance(answer, SiteCapacityClientError):
            if not _site_refused(answer):
                return self._outcome(OutcomeKind.PENDING, deal, detail=f"commit unanswered: {answer}")
            return await self._hand_off(deal, self._commit_refused(reservation_id, answer))
        return self._committed(deal, reservation_id, answer)

    async def _site_commit(
        self, deal: _Deal, reservation_id: str, claim: ReserveClaim,
    ) -> Mapping[str, Any] | SiteCapacityClientError:
        try:
            committed = await self._capacity.commit(
                deal.accepted.binding,
                resource_id=None,
                capacity_reservation_id=reservation_id,
                lease_start_utc=deal.window.start_utc,
                lease_end_utc=deal.window.end_utc,
                deal_ref=dict(claim.deal_ref) or None,
            )
        except SiteCapacityClientError as exc:
            return exc
        if committed is None:
            return SiteCapacityClientError("the site answered the commit with no reservation")
        return committed

    def _committed(
        self, deal: _Deal, reservation_id: str, committed: Mapping[str, Any],
    ) -> DeliveryOutcome | None:
        if committed.get("capacity_reservation_id") != reservation_id:
            return self._repair_deal(
                deal, RepairReason.SITE_UNANSWERED, f"reservation:{reservation_id}",
                "the site's commit answer names another reservation",
            )
        try:
            require_committed_window(deal.window, committed)
        except TimingInvalid as exc:
            return self._repair_deal(
                deal, RepairReason.TIMING_INVALID, f"reservation:{reservation_id}", str(exc),
            )
        return None

    async def _place(self, deal: _Deal, claim: ReserveClaim) -> DeliveryOutcome | bool:
        """Give the deal its reservation: its live hold, else a settlement placement.

        Returns ``True`` when an adopted hold is already committed, ``False``
        when a placement was recorded and still needs its commit.
        """
        hold = await self._domain.accepted_hold(deal.negotiation_id)
        if hold is not None:
            adopted = await self._adopt_hold(deal, hold, claim)
            if adopted is not None:
                return adopted
        return await self._reserve_settlement(deal, claim)

    async def _adopt_hold(
        self, deal: _Deal, hold: object, claim: ReserveClaim,
    ) -> DeliveryOutcome | bool | None:
        """Commit the domain's acceptance hold before anything else is placed.

        ``None`` means the hold is verified lapsed and may be replaced. A commit
        whose answer was lost may have succeeded, so it is retried, never
        replaced: a second reservation beside it is an orphan.
        """
        nid = deal.negotiation_id
        if (
            not isinstance(hold, AcceptedHold)
            or not isinstance(hold.capacity_reservation_id, str)
            or not hold.capacity_reservation_id
        ):
            return self._repair_deal(
                deal, RepairReason.DOMAIN_RESULT_INVALID, f"accepted_hold:{nid}",
                f"accepted_hold returned {hold!r}",
            )
        hold_id = hold.capacity_reservation_id
        answer = await self._site_commit(deal, hold_id, claim)
        if isinstance(answer, Mapping):
            await self._record_reservation(deal, hold_id)
            return self._committed(deal, hold_id, answer) or True
        if not _site_refused(answer):
            return DeliveryOutcome(
                OutcomeKind.PENDING, capacity_reservation_id=hold_id,
                detail=f"hold commit unanswered: {answer}",
            )
        lapsed = await self._hold_lapsed(deal, hold)
        if isinstance(lapsed, DeliveryOutcome):
            return lapsed
        if lapsed:
            return None
        await self._record_reservation(deal, hold_id)
        return await self._hand_off(deal, self._commit_refused(hold_id, answer))

    async def _hold_lapsed(self, deal: _Deal, hold: AcceptedHold) -> DeliveryOutcome | bool:
        """Whether a refused hold is verified lapsed rather than live.

        A keyed hold's replay under ``:hold`` returns it in whatever state it is
        in; a hold placed with no key is lapsed only once its recorded expiry
        has passed. Anything less proves nothing, and the hold counts as live.
        """
        nid = deal.negotiation_id
        if hold.placement is None:
            return hold.expires_at is not None and hold.expires_at <= self._clock()
        placement = hold.placement
        try:
            replay = await self._capacity.reserve(
                deal.accepted.binding,
                claim=placement.claim,
                deal_ref={**placement.deal_ref, "negotiation_id": nid, "placement_key": f"{nid}:hold"},
                ttl_seconds=placement.ttl_seconds,
                lease_start_utc=placement.lease_start_utc,
                lease_duration_seconds=placement.lease_duration_seconds,
            )
        except SiteCapacityClientError as exc:
            if _site_refused(exc):
                return self._repair_deal(
                    deal, RepairReason.DOMAIN_RESULT_INVALID, f"accepted_hold:{nid}",
                    f"the site refused the hold's recorded placement: {exc}",
                )
            return DeliveryOutcome(
                OutcomeKind.PENDING, capacity_reservation_id=hold.capacity_reservation_id,
                detail=f"hold replay unanswered: {exc}",
            )
        if replay is None or replay.get("capacity_reservation_id") != hold.capacity_reservation_id:
            # The site answers a replay that found a reservation under the key
            # and one that placed a new one alike, so the path releases neither:
            # the reservation may be the deal's live hold. A placed one carries
            # the hold's TTL and lapses unless repair adopts it.
            found = replay.get("capacity_reservation_id") if replay is not None else None
            return self._repair_deal(
                deal, RepairReason.DOMAIN_RESULT_INVALID, f"accepted_hold:{nid}",
                f"the hold's replay under its placement key answered reservation {found!r}, "
                f"not the hold {hold.capacity_reservation_id!r}",
            )
        return replay.get("state") in _RELEASED_STATES

    async def _reserve_settlement(self, deal: _Deal, claim: ReserveClaim) -> DeliveryOutcome | bool:
        """Reserve under ``<negotiation_id>:settlement``, the placement a replay finds.

        The site returns the recorded reservation in whatever state it is in;
        one that comes back released is never replaced by a fresh hold.
        """
        nid = deal.negotiation_id
        try:
            reserved = await self._capacity.reserve(
                deal.accepted.binding,
                claim=claim.claim,
                deal_ref={**claim.deal_ref, "negotiation_id": nid, "placement_key": f"{nid}:settlement"},
                lease_start_utc=deal.window.start_utc,
                lease_duration_seconds=deal.window.duration_seconds,
            )
        except SiteCapacityClientError as exc:
            if _site_refused(exc):
                return await self._hand_off(deal, _Failure(
                    kind="start_failure", cause="reserve_refused",
                    source_ref=f"delivery:reserve-refused:{nid}",
                    evidence={"site_id": deal.site_id, "status_code": exc.status_code, "detail": str(exc)},
                ))
            return self._outcome(OutcomeKind.PENDING, deal, detail=f"reserve unanswered: {exc}")
        if reserved is None:
            return await self._hand_off(deal, _Failure(
                kind="start_failure", cause="capacity_unavailable",
                source_ref=f"delivery:no-capacity:{nid}",
                evidence={"site_id": deal.site_id, "reservation": None},
            ))
        reservation_id = reserved.get("capacity_reservation_id")
        if not isinstance(reservation_id, str) or not reservation_id:
            return self._repair_deal(
                deal, RepairReason.SITE_UNANSWERED, f"reserve_claim:{nid}",
                "the site's reserve answer names no reservation",
            )
        # Recorded whatever its state, so the end operation releases what the
        # site holds for the deal.
        await self._record_reservation(deal, reservation_id)
        if reserved.get("state") in _RELEASED_STATES:
            return await self._hand_off(deal, _Failure(
                kind="start_failure", cause="reservation_released",
                source_ref=f"delivery:reservation-released:{reservation_id}",
                evidence={"site_id": deal.site_id, "reservation": dict(reserved)},
            ))
        return False

    async def _record_reservation(self, deal: _Deal, reservation_id: str) -> None:
        # Not admitted: a reservation the site holds is recorded even when an
        # end won meanwhile, because the end operation releases what is recorded.
        await self._transaction(lambda conn: self._progress.record_reservation(
            conn, deal.negotiation_id, reservation_id,
        ))
        deal.progress = replace(
            deal.progress, step=DeliveryStep.COMMIT, capacity_reservation_id=reservation_id,
        )

    def _commit_refused(self, reservation_id: str, answer: SiteCapacityClientError) -> _Failure:
        return _Failure(
            kind="start_failure", cause="commit_refused",
            source_ref=f"delivery:commit-refused:{reservation_id}",
            evidence={
                "capacity_reservation_id": reservation_id,
                "status_code": answer.status_code,
                "detail": str(answer),
            },
        )

    # -- dispatch ----------------------------------------------------------

    async def _dispatch(self, deal: _Deal) -> DeliveryOutcome | None:
        """Begin the deal's one fulfillment, recording the dispatch before it begins.

        A recorded dispatch with no fulfillment identity repeats the same
        request, which provisioning answers with the fulfillment it already
        accepted for the reservation.
        """
        nid = deal.negotiation_id
        reservation_id = deal.progress.capacity_reservation_id
        assert reservation_id is not None
        request = await self._domain.fulfillment_request(
            nid, capacity_reservation_id=reservation_id, window=deal.window,
        )
        if (
            not isinstance(request, FulfillmentRequestBody)
            or request.capacity_reservation_id != reservation_id
        ):
            return self._repair_deal(
                deal, RepairReason.DOMAIN_RESULT_INVALID, f"fulfillment_request:{nid}",
                "the fulfillment request does not name the deal's reservation",
            )
        first = deal.progress.step is not DeliveryStep.DISPATCH

        def record_dispatch(session: EndSession, _: DeliveryAuthorization) -> None:
            if first:
                self._progress.record_dispatch(session.conn, nid)

        blocked = await self._authorized(deal, DeliveryPhase.DISPATCH, apply=record_dispatch)
        if blocked is not None:
            return blocked
        deal.progress = replace(deal.progress, step=DeliveryStep.DISPATCH)
        accepted = await self._fulfillment.begin_fulfillment(request, site_id=deal.site_id)
        if (
            not isinstance(accepted, FulfillmentAcceptanceResponse)
            or accepted.capacity_reservation_id != reservation_id
            or not accepted.fulfillment_id
        ):
            return self._repair_deal(
                deal, RepairReason.SITE_UNANSWERED, f"reservation:{reservation_id}",
                "provisioning acknowledged no fulfillment for the deal's reservation",
            )
        fulfillment_id = accepted.fulfillment_id
        await self._transaction(lambda conn: self._progress.record_fulfillment(conn, nid, fulfillment_id))
        deal.progress = replace(deal.progress, step=DeliveryStep.FULFILLMENT, fulfillment_id=fulfillment_id)
        return None

    # -- readiness ---------------------------------------------------------

    async def _fulfil(self, deal: _Deal) -> DeliveryOutcome:
        """Carry the recorded fulfillment to availability; never schedule or begin another.

        Activation precedes billing start and availability, and available means
        readiness, activation, billing start and disclose authorization are all
        durable, whether or not the buyer ever reads.
        """
        if deal.record.available_at is not None:
            return await self._converge(deal)
        # A create that never settles must not outlast a due end or the window.
        if await self._transaction(lambda conn: self._end_due(conn, deal.negotiation_id)):
            return await self._ended(deal)
        ready = await self._ready(deal)
        if isinstance(ready, DeliveryOutcome):
            return ready
        if deal.progress.activated_at is None:
            outcome = await self._activate(deal)
            if outcome is not None:
                return outcome
        outcome = await self._start_billing(deal, ready)
        if outcome is not None:
            return outcome
        outcome = await self._disclose(deal, ready)
        if outcome is not None:
            return outcome
        return await self._converge(deal)

    async def _ready(self, deal: _Deal) -> DeliveryOutcome | ReadyEvidenceRef:
        reservation_id = deal.progress.capacity_reservation_id
        fulfillment_id = deal.progress.fulfillment_id
        assert reservation_id is not None and fulfillment_id is not None
        status = await self._fulfillment.get_fulfillment_status(
            fulfillment_id, capacity_reservation_id=reservation_id, site_id=deal.site_id,
        )
        # A status for another fulfillment or reservation proves nothing about
        # this deal's: acting on it could make this deal available on another's
        # readiness, or end it for another's failure.
        if (
            not isinstance(status, FulfillmentStatusResponse)
            or status.fulfillment_id != fulfillment_id
            or status.capacity_reservation_id != reservation_id
        ):
            return self._repair_deal(
                deal, RepairReason.SITE_UNANSWERED, f"fulfillment:{fulfillment_id}",
                "provisioning's status answer names another fulfillment or reservation",
            )
        if status.state in _SETTLING_STATES:
            return self._outcome(OutcomeKind.PENDING, deal, detail=f"fulfillment is {status.state}")
        if status.state in _UNDELIVERED_STATES:
            # Dispatched work is adopted and ended through the end operation,
            # never replaced.
            return await self._hand_off(deal, _Failure(
                kind="provisioning_failure", cause="provisioning_failed",
                source_ref=f"delivery:fulfillment-failed:{fulfillment_id}",
                evidence={
                    "fulfillment_id": fulfillment_id, "state": status.state,
                    "failure_reason": status.failure_reason, "failure_message": status.failure_message,
                },
            ))
        if status.state != "active":
            return self._repair_deal(
                deal, RepairReason.SITE_UNANSWERED, f"fulfillment:{fulfillment_id}",
                f"provisioning reports an unknown fulfillment state {status.state!r}",
            )
        result = await self._fulfillment.get_fulfillment_result(
            fulfillment_id, capacity_reservation_id=reservation_id, site_id=deal.site_id,
        )
        if not isinstance(result, VersionedEnvelope) or not result.payload:
            return self._repair_deal(
                deal, RepairReason.DOMAIN_RESULT_INVALID, f"fulfillment:{fulfillment_id}",
                "the fulfillment result is empty",
            )
        ready = await self._domain.ready_evidence(deal.negotiation_id, result)
        if not isinstance(ready, ReadyEvidenceRef):
            return self._repair_deal(
                deal, RepairReason.DOMAIN_RESULT_INVALID, f"fulfillment:{fulfillment_id}",
                "the fulfillment result shows no ready evidence",
            )
        return ready

    # -- activation, billing start, availability -----------------------------

    async def _activate(self, deal: _Deal) -> DeliveryOutcome | None:
        """Activate the lease at its site, after readiness and admission for ``activate``.

        The site writes the instant once from its own clock and keeps the
        lease's current end, an earlier truncation included; a retry after a
        lost answer returns the same instant. A site that cannot be asked, does
        not know the reservation, or answers unsigned has not activated.
        """
        nid = deal.negotiation_id
        reservation_id = deal.progress.capacity_reservation_id
        assert reservation_id is not None
        admission: Admission = await self._transaction(
            lambda conn: self._admit(conn, nid, DeliveryPhase.ACTIVATE)
        )
        if admission.status == "ended":
            return await self._ended(deal)
        if admission.status == "retry":
            return self._outcome(OutcomeKind.PENDING, deal, detail="stale admission revision")
        try:
            activated = await self._capacity.activate_lease(
                deal.accepted.binding, capacity_reservation_id=reservation_id,
            )
        except SiteCapacityClientError as exc:
            if _site_refused(exc) and exc.status_code == 409:
                return await self._activation_refused(deal, reservation_id, exc)
            return self._repair_deal(
                deal, RepairReason.SITE_UNANSWERED, f"reservation:{reservation_id}",
                f"the site has not activated the lease: {exc}",
            )
        if activated is None or activated.get("capacity_reservation_id") != reservation_id:
            return self._repair_deal(
                deal, RepairReason.SITE_UNANSWERED, f"reservation:{reservation_id}",
                "the site's activation answer names no activated reservation",
            )
        try:
            activated_at = utc_seconds(activated.get("activated_at_utc"))
        except TimingInvalid as exc:
            return self._repair_deal(
                deal, RepairReason.SITE_UNANSWERED, f"reservation:{reservation_id}",
                f"the site's activation answer carries no instant: {exc}",
            )
        await self._transaction(lambda conn: self._progress.record_activation(conn, nid, activated_at))
        deal.progress = replace(deal.progress, step=DeliveryStep.ACTIVATED, activated_at=activated_at)
        return None

    async def _activation_refused(
        self, deal: _Deal, reservation_id: str, refusal: SiteCapacityClientError,
    ) -> DeliveryOutcome:
        """Explain a refused activation from the lease as the site records it."""
        lease = await self._fulfillment.get_lease(reservation_id, site_id=deal.site_id)
        if not isinstance(lease, LeaseView) or lease.capacity_reservation_id != reservation_id:
            # Another lease's state cannot explain this one's refusal.
            return self._repair_deal(
                deal, RepairReason.ACTIVATION_UNEXPLAINED, f"lease:{reservation_id}",
                f"the site refused activation ({refusal}) and its lease read names another reservation",
            )
        if lease.status in _ENDING_LEASE_STATES:
            return await self._hand_off(deal, _Failure(
                kind="activation_lapse", cause="activation_lapsed",
                source_ref=f"delivery:activation-lapsed:{reservation_id}",
                evidence={
                    "capacity_reservation_id": reservation_id, "lease_status": lease.status.value,
                    "refusal": str(refusal),
                },
            ))
        return self._repair_deal(
            deal, RepairReason.ACTIVATION_UNEXPLAINED, f"lease:{reservation_id}",
            f"the site refused activation ({refusal}) of a lease it reports {lease.status.value}",
        )

    async def _start_billing(self, deal: _Deal, ready: ReadyEvidenceRef) -> DeliveryOutcome | None:
        """Start billing through end service's one intent for the deal.

        End service journals the key and evidence before the payment
        authority is asked; a retry repeats the same key and adopts the
        recorded outcome, so the path keeps no billing intent of its own.
        """
        nid = deal.negotiation_id
        key = f"{nid}:billing-start"
        evidence = deal.evidence(DeliveryPhase.START, ready)
        activated_at = deal.progress.activated_at
        assert activated_at is not None
        if activated_at > self._clock():
            # The instant is the site's; end service refuses an activation it
            # sees in its own future, so billing waits for this clock to reach it.
            return self._outcome(
                OutcomeKind.PENDING, deal, detail="the site's activation instant is ahead of this clock",
            )
        journaled = await self._transaction(lambda conn: [
            intent for intent in EndSession(conn).intents(nid) if intent.kind == "billing"
        ])
        if journaled and journaled[0].payload != evidence.model_dump(mode="json"):
            return self._repair_deal(
                deal, RepairReason.DOMAIN_RESULT_INVALID, journaled[0].intent_ref,
                "the ready evidence differs from what billing start journaled",
            )
        blocked = await self._authorized(deal, DeliveryPhase.START, ready=ready)
        if blocked is not None:
            return blocked
        started = await self._end.begin_billing(key, evidence, adapter=deal.accepted.payment)
        outcome = started.result.outcome
        if isinstance(outcome, Accepted):
            return None
        if isinstance(outcome, Rejected):
            if await self._transaction(lambda conn: self._end_due(conn, nid)):
                return await self._ended(deal)
            intent = await self._transaction(lambda conn: EndSession(conn).intent(started.intent_ref))
            return self._repair_deal(
                deal, RepairReason.NO_ACCEPTED_DEAL,
                started.intent_ref if intent is not None else f"billing:{nid}", outcome.reason,
            )
        return self._outcome(OutcomeKind.PENDING, deal, detail=f"billing start is {outcome.status}")

    async def _disclose(self, deal: _Deal, ready: ReadyEvidenceRef) -> DeliveryOutcome | None:
        """Record the deal available in the disclose authorization's transaction.

        The instant is read before the authorization, so it is no later than
        the one the authorization admits at: an end due at it would have
        refused the authorization too, and availability is written whenever the
        authorization allows.
        """
        nid = deal.negotiation_id
        now = self._clock()

        def record_available(session: EndSession, _: DeliveryAuthorization) -> None:
            record = session.read(nid)
            session.available(nid, at=now, expected_revision=record.revision, now=now)

        return await self._authorized(deal, DeliveryPhase.DISCLOSE, ready=ready, apply=record_available)

    async def _converge(self, deal: _Deal) -> DeliveryOutcome:
        """Converged once the domain's continuation is acknowledged, or it has none.

        The continuation runs even when an end is due after availability: it
        settles service already delivered, such as the seller's claim of an
        Alkahest escrow, which a buyer's reclaim would take back if an end
        stopped it. The end is still reconciled on every drive: while the
        continuation is unacknowledged the deal is pending, so its worker keeps
        driving it, and once nothing is left the deal is ended.
        """
        nid = deal.negotiation_id
        state = await self._domain.continuation(nid)
        if not isinstance(state, ContinuationState):
            return self._repair_deal(
                deal, RepairReason.DOMAIN_RESULT_INVALID, f"continuation:{nid}",
                f"continuation returned {state!r}",
            )
        end_due = await self._transaction(lambda conn: self._end_due(conn, nid))
        if state is ContinuationState.PENDING:
            if end_due:
                return self._outcome(
                    OutcomeKind.PENDING, deal, detail="delivery has ended; its continuation is pending",
                )
            return self._outcome(OutcomeKind.AVAILABLE, deal)
        if end_due:
            return await self._ended(deal)
        return self._outcome(OutcomeKind.CONVERGED, deal)

    # -- access ------------------------------------------------------------

    async def read_access(
        self, negotiation_id: str, fetch: Callable[[str, str], Awaitable[T]],
    ) -> T:
        """Fetch a deal's access material for its buyer, only while delivery stands.

        The deal must be available, its Agreement started, and admitted for
        disclosure. ``fetch`` receives the fulfillment and reservation
        identities and reads provisioning's live result outside any
        transaction. Admission is asked again afterwards at the revision it
        first admitted, and at the current one if that changed, so an end due
        now discards the fetched material while a truncation still in the future
        does not. No payment snapshot is read. Material returned before an end is not
        retracted: physical teardown revokes the access it grants.
        """
        nid = negotiation_id
        progress, revision = await self._transaction(lambda conn: self._access_admitted(conn, nid))
        assert progress.fulfillment_id is not None and progress.capacity_reservation_id is not None
        material = await fetch(progress.fulfillment_id, progress.capacity_reservation_id)
        if not await self._transaction(lambda conn: self._disclosure_admitted(conn, nid, revision)):
            raise AccessRefused("ended", "an end was admitted while access was read")
        return material

    def _access_admitted(self, conn: sqlite3.Connection, nid: str) -> tuple[Progress, int]:
        session = EndSession(conn)
        try:
            record = session.read(nid)
            progress = read_progress(self._progress.load(conn, nid))
        except (KeyError, ValidationError, ProgressUnreadable) as exc:
            raise AccessRefused("not_available", f"delivery cannot be read: {exc}") from None
        if record.available_at is None or progress.fulfillment_id is None:
            raise AccessRefused("not_available", "the deal is not available")
        now = self._clock()
        if now < record.start_at:
            raise AccessRefused("not_started", "the Agreement has not started")
        admission = session.admit(nid, DeliveryPhase.DISCLOSE, record.revision, now=now)
        if admission.status != "admitted":
            raise AccessRefused("ended", "delivery has ended")
        return progress, admission.revision

    def _disclosure_admitted(self, conn: sqlite3.Connection, nid: str, revision: int) -> bool:
        # Admitted again at the current instant even when nothing was written,
        # since an end recorded earlier can fall due while the fetch runs.
        session = EndSession(conn)
        now = self._clock()
        admission = session.admit(nid, DeliveryPhase.DISCLOSE, revision, now=now)
        if admission.status == "retry":
            admission = session.admit(nid, DeliveryPhase.DISCLOSE, admission.revision, now=now)
        return admission.status == "admitted"

    # -- authorization and ends ----------------------------------------------

    async def _authorized(
        self,
        deal: _Deal,
        phase: DeliveryPhase,
        *,
        ready: ReadyEvidenceRef | None = None,
        apply: Callable[[EndSession, DeliveryAuthorization], None] | None = None,
    ) -> DeliveryOutcome | None:
        """``None`` when end service allows the phase; otherwise where the deal stands.

        A refusal because an end is due goes to the end hand-off; an unknown
        or pending answer leaves the deal pending, and the next drive resolves
        the same authorization; any other refusal is the payment authority's
        refusal of the commitment, which no retry changes.
        """
        nid = deal.negotiation_id
        revision = await self._transaction(lambda conn: EndSession(conn).read(nid).revision)
        authorization = await self._end.authorize_delivery(
            phase, deal.evidence(phase, ready), adapter=deal.accepted.payment,
            expected_revision=revision, apply=apply,
        )
        if authorization.status == "allow":
            return None
        if await self._transaction(lambda conn: self._end_due(conn, nid)):
            return await self._ended(deal)
        if authorization.status == "pending":
            return self._outcome(OutcomeKind.PENDING, deal, detail=authorization.reason)
        return self._repair_deal(
            deal, RepairReason.NO_ACCEPTED_DEAL, authorization.operation_id, authorization.reason,
        )

    def _end_due(self, conn: sqlite3.Connection, nid: str) -> bool:
        session = EndSession(conn)
        record = session.read(nid)
        return session.admit(nid, record.phase, record.revision, now=self._clock()).status == "ended"

    def _admit(self, conn: sqlite3.Connection, nid: str, phase: DeliveryPhase) -> Admission:
        session = EndSession(conn)
        record = session.read(nid)
        return session.admit(nid, phase, record.revision, now=self._clock())

    async def _hand_off(self, deal: _Deal, failure: _Failure) -> DeliveryOutcome:
        """Record an undelivered deal's end with its classified evidence, then end it."""
        now = self._clock()
        await self._transaction(lambda conn: self._record_failure(conn, deal, failure, now))
        return await self._ended(deal)

    def _record_failure(
        self, conn: sqlite3.Connection, deal: _Deal, failure: _Failure, now: int,
    ) -> None:
        """Journal the end, its evidence and its filing in one transaction.

        Admission runs first so a missed delivery deadline is established
        before this end could obscure it. The path supplies the failure's own
        classification from what it observed, and adopts an earlier lawful end
        that is already due as the controlling one, filing no self-penalty for
        it; otherwise the end is a seller failure whose ``delivery_end`` filing
        is journaled with it and acts no earlier than the Agreement start. End
        service validates that pairing, and suppresses the filing under an
        earlier classified end. The path computes no amount and sends no
        payment stop or reverse.
        """
        nid = deal.negotiation_id
        session = EndSession(conn)
        record = session.read(nid)
        session.admit(nid, record.phase, record.revision, now=now)
        record = session.read(nid)
        requests = session.requests(nid)
        if any(request.source_ref == failure.source_ref for request in requests):
            return
        selected = requests[0] if requests else None
        controlling = _classification(conn, nid, selected.source_ref) if selected else None
        lawful = (
            selected is not None and controlling is not None
            and controlling.lawful and selected.ended_at <= now
        )
        EvidenceSession(conn).put(nid, EvidenceItem(
            evidence_id=failure.source_ref, kind=f"delivery_{failure.cause}",
            classification="seller_assertion", recorded_at=now,
            body=base64.b64encode(canonical_json(dict(failure.evidence))),
        ))
        request = FinalRequest(
            negotiation_id=nid, source_ref=failure.source_ref, ended_at=now, observed_at=now,
            actor=record.seller, cause=failure.cause, source="delivery",
            evidence_refs=[failure.source_ref],
            controlling_source_ref=selected.source_ref if lawful and selected else None,
        )
        if lawful and selected is not None and controlling is not None:
            session.record_end(request, now=now, classification=Classification(
                kind=controlling.kind, evidence_refs=[failure.source_ref, selected.source_ref],
            ))
            return
        session.record_end(
            request, now=now,
            classification=Classification(kind=failure.kind, evidence_refs=[failure.source_ref]),
            filing_intent=session.failure_filing(
                request, now=now, delivered=record.available_at is not None,
            ),
        )

    async def _ended(self, deal: _Deal) -> DeliveryOutcome:
        """Report an ended deal once its end is durable, driving its physical end.

        End service ends the physical side through the domain's end port under
        each intent's stable key: a reservation nothing was dispatched for is
        released, and dispatched work is adopted and torn down. A failure there
        leaves the intent pending for the next drive or the domain's worker to
        repeat under the same key; it never changes that the deal ended.
        """
        nid = deal.negotiation_id
        selected, record = await self._transaction(
            lambda conn: (EndSession(conn).selected_end(nid), EndSession(conn).read(nid))
        )
        if selected is None and record.available_at is None and self._clock() >= record.term_end:
            # The window elapsed with nothing delivered and no end recorded,
            # settlement after the Agreement's end included: never-delivered
            # evidence, with no buyer fault inferred from the lateness.
            return await self._hand_off(deal, _Failure(
                kind="non_delivery", cause="window_elapsed",
                source_ref=f"delivery:window-elapsed:{nid}",
                evidence={"term_end": record.term_end, "available_at": None},
            ))
        try:
            await self._end.drive_physical(nid)
        except Exception:
            logger.exception("physical end of %s is pending; it is repeated under the same key", nid)
        return self._outcome(
            OutcomeKind.ENDED, deal,
            evidence_ref=selected.source_ref if selected is not None else f"servicing_delivery:{nid}",
            detail=selected.cause if selected is not None else "the accepted term has ended",
        )

    # -- outcomes ----------------------------------------------------------

    @staticmethod
    def _outcome(kind: OutcomeKind, deal: _Deal, **fields: Any) -> DeliveryOutcome:
        return DeliveryOutcome(
            kind,
            capacity_reservation_id=deal.progress.capacity_reservation_id,
            fulfillment_id=deal.progress.fulfillment_id,
            **fields,
        )

    def _repair_deal(
        self, deal: _Deal, reason: RepairReason, evidence_ref: str, detail: str,
    ) -> DeliveryOutcome:
        return self._outcome(
            OutcomeKind.REPAIR_REQUIRED, deal, reason=reason, evidence_ref=evidence_ref, detail=detail,
        )

    @staticmethod
    def _repair(
        reason: RepairReason,
        reservation_id: str | None,
        fulfillment_id: str | None,
        evidence_ref: str,
        detail: str,
    ) -> DeliveryOutcome:
        return DeliveryOutcome(
            OutcomeKind.REPAIR_REQUIRED,
            capacity_reservation_id=reservation_id,
            fulfillment_id=fulfillment_id,
            reason=reason,
            evidence_ref=evidence_ref,
            detail=detail,
        )


def _classification(conn: sqlite3.Connection, nid: str, source_ref: str) -> Classification | None:
    """The classification end service recorded for one end request, if resolved."""
    row = conn.execute(
        "SELECT classification FROM servicing_final_requests WHERE negotiation_id=? AND source_ref=?",
        (nid, source_ref),
    ).fetchone()
    return Classification.model_validate_json(row[0]) if row and row[0] else None
