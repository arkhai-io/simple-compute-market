"""Private RFQ responses, consent transitions and pair-specific introductions."""

from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import uuid4

from market_core.rfq import (
    OfferResponse,
    ResponseVersion,
    ShareContact,
    RfqAccountClaim,
    RfqAudience,
    RfqIntroductionDetail,
    RfqMutationReceipt,
    RfqResponseDetail,
    RfqResponseInbox,
)
from sqlalchemy import and_, delete, select
from sqlalchemy.orm import Session

from core_registry.rfq_spec import RfqSpec
from core_registry.db.models import (
    RfqContactPayload,
    RfqIntroduction,
    RfqPartyReference,
    RfqRequest,
    RfqResponse,
    utcnow,
)
from core_registry.rfq_contact_crypto import (
    BUYER_CONTACT,
    PENDING_CONTACT,
    RESPONDENT_CONTACT,
    RfqContactKeys,
)
from core_registry.rfq_contact_store import contact_binding, open_contact, store_contact
from core_registry.rfq_requests import RfqActionError, account_is_buyer, can_view_rfq

_CONTACT_WINDOW = timedelta(days=30)


def _account_is_respondent(response: RfqResponse, account: RfqAccountClaim) -> bool:
    return (response.respondent_namespace, response.respondent_subject) == (account.namespace, account.subject)


def _require_open(rfq: RfqRequest, now: datetime) -> None:
    if rfq.closed_at is not None or now >= rfq.respond_by:
        raise RfqActionError(409, "rfq_not_open")


def _require_version(actual: int, expected: int) -> None:
    if actual != expected:
        raise RfqActionError(409, "stale_rfq_version")


def _require_pending(response: RfqResponse, rfq: RfqRequest) -> None:
    if response.state != "pending" or response.terms_revision != rfq.terms_revision:
        raise RfqActionError(409, "rfq_response_not_pending")


class RfqResponses:
    """Use the RFQ row as the write lock shared with edits, closure and selection."""

    def __init__(
        self, db: Session, spec: RfqSpec, account: RfqAccountClaim, registry: RfqAudience,
        keys: RfqContactKeys,
    ):
        self.db = db
        self.spec = spec
        self.account = account
        self.registry = registry
        self.keys = keys

    def _rfq(
        self, rfq_id: str, *, lock: bool = False, not_found: str = "rfq_response_not_found",
    ) -> RfqRequest:
        statement = select(RfqRequest).where(RfqRequest.rfq_id == rfq_id, RfqRequest.kind == self.spec.kind)
        row = self.db.scalar(statement.with_for_update() if lock else statement)
        if row is None:
            raise RfqActionError(404, not_found)
        return row

    def _response(self, rfq_id: str, response_id: str) -> RfqResponse:
        row = self.db.get(RfqResponse, response_id)
        if row is None or row.rfq_id != rfq_id:
            raise RfqActionError(404, "rfq_response_not_found")
        return row

    def _party_reference(self, rfq_id: str, namespace: str, subject: str) -> RfqPartyReference:
        row = self.db.get(RfqPartyReference, (rfq_id, namespace, subject))
        if row is None:
            raise RfqActionError(409, "rfq_counterparty_changed")
        return row

    def _require_buyer_recipient(self, rfq: RfqRequest, inputs: ShareContact) -> None:
        if account_is_buyer(rfq, self.account):
            raise RfqActionError(409, "rfq_own_response")
        buyer = self._party_reference(rfq.rfq_id, rfq.buyer_namespace, rfq.buyer_subject)
        if inputs.counterparty != buyer.reference:
            raise RfqActionError(409, "rfq_counterparty_changed")
        if inputs.terms_revision != rfq.terms_revision:
            raise RfqActionError(409, "stale_rfq_terms")

    def _offer(self, rfq: RfqRequest, inputs: OfferResponse) -> RfqMutationReceipt:
        self._require_buyer_recipient(rfq, inputs)
        offered = self.spec.offered_quantity(inputs.offer, request=rfq.requirements)
        who = (rfq.rfq_id, self.account.namespace, self.account.subject)
        pending = self.db.scalar(select(RfqResponse.response_id).where(
            RfqResponse.rfq_id == who[0], RfqResponse.respondent_namespace == who[1],
            RfqResponse.respondent_subject == who[2], RfqResponse.terms_revision == rfq.terms_revision,
            RfqResponse.state == "pending",
        ))
        if pending is not None:
            raise RfqActionError(409, "rfq_response_already_pending")
        if self.db.get(RfqPartyReference, who) is None:
            self.db.add(RfqPartyReference(
                rfq_id=who[0], namespace=who[1], subject=who[2], reference=uuid4().hex,
            ))
            self.db.flush()
        now = utcnow()
        _require_open(rfq, now)
        response = RfqResponse(
            response_id=uuid4().hex, rfq_id=rfq.rfq_id,
            respondent_namespace=self.account.namespace, respondent_subject=self.account.subject,
            offered_quantity=offered, terms_revision=rfq.terms_revision,
            state="pending", version=1, created_at=now,
        )
        self.db.add(response)
        self.db.flush()
        binding = contact_binding(self.registry.name, rfq, response, PENDING_CONTACT, rfq.respond_by)
        store_contact(self.db, self.keys, response.response_id, inputs.contact, binding)
        return self._receipt(response)

    def respond(self, rfq_id: str, inputs: OfferResponse) -> RfqMutationReceipt:
        rfq = self._rfq(rfq_id, lock=True, not_found="rfq_not_found")
        if not can_view_rfq(self.db, rfq, self.account, utcnow()):
            raise RfqActionError(404, "rfq_not_found")
        _require_version(rfq.version, inputs.version)
        return self._offer(rfq, inputs)

    def reconfirm(self, rfq_id: str, response_id: str, inputs: OfferResponse) -> RfqMutationReceipt:
        rfq = self._rfq(rfq_id, lock=True)
        previous = self._response(rfq_id, response_id)
        if not _account_is_respondent(previous, self.account):
            raise RfqActionError(404, "rfq_response_not_found")
        _require_version(previous.version, inputs.version)
        if previous.state != "superseded" or previous.terms_revision >= rfq.terms_revision:
            raise RfqActionError(409, "rfq_response_not_superseded")
        return self._offer(rfq, inputs)

    def _receipt(self, response: RfqResponse, intro: RfqIntroduction | None = None) -> RfqMutationReceipt:
        return RfqMutationReceipt(
            resource_id=response.response_id, state=response.state, version=response.version,
            terms_revision=response.terms_revision, introduction_id=intro.introduction_id if intro else None,
        )

    def finish_pending(
        self, rfq_id: str, response_id: str, inputs: ResponseVersion,
        state: Literal["withdrawn", "dismissed"],
    ) -> RfqMutationReceipt:
        rfq = self._rfq(rfq_id, lock=True)
        response = self._response(rfq_id, response_id)
        permitted = (
            _account_is_respondent(response, self.account)
            if state == "withdrawn"
            else account_is_buyer(rfq, self.account)
        )
        if not permitted:
            raise RfqActionError(404, "rfq_response_not_found")
        _require_version(response.version, inputs.version)
        _require_pending(response, rfq)
        _require_open(rfq, utcnow())
        self._delete_contact(response_id, pending_only=True)
        response.state = state
        response.version += 1
        return self._receipt(response)

    def _delete_contact(self, response_id: str, *, pending_only: bool = False) -> None:
        statement = delete(RfqContactPayload).where(RfqContactPayload.response_id == response_id)
        if pending_only:
            statement = statement.where(RfqContactPayload.purpose == PENDING_CONTACT)
        self.db.execute(statement)

    def select(self, rfq_id: str, response_id: str, inputs: ShareContact) -> RfqMutationReceipt:
        rfq = self._rfq(rfq_id, lock=True)
        if not account_is_buyer(rfq, self.account):
            raise RfqActionError(404, "rfq_response_not_found")
        response = self._response(rfq_id, response_id)
        _require_version(response.version, inputs.version)
        if inputs.terms_revision != rfq.terms_revision:
            raise RfqActionError(409, "stale_rfq_terms")
        _require_pending(response, rfq)
        respondent = self._party_reference(rfq_id, response.respondent_namespace, response.respondent_subject)
        if inputs.counterparty != respondent.reference:
            raise RfqActionError(409, "rfq_counterparty_changed")

        _require_open(rfq, utcnow())
        pending = contact_binding(self.registry.name, rfq, response, PENDING_CONTACT, rfq.respond_by)
        respondent_contact = open_contact(self.db, self.keys, response_id, pending)
        now = utcnow()
        _require_open(rfq, now)
        intro = RfqIntroduction(
            introduction_id=uuid4().hex, response_id=response_id,
            completed_at=now, contact_until=now + _CONTACT_WINDOW, version=1,
        )
        self.db.add(intro)
        self._delete_contact(response_id, pending_only=True)
        for purpose, plaintext in ((RESPONDENT_CONTACT, respondent_contact), (BUYER_CONTACT, inputs.contact)):
            binding = contact_binding(
                self.registry.name, rfq, response, purpose, intro.contact_until,
                introduction_id=intro.introduction_id,
            )
            store_contact(self.db, self.keys, response_id, plaintext, binding)
        response.state = "selected"
        response.version += 1
        return self._receipt(response, intro)

    def _view(self, rfq: RfqRequest, response: RfqResponse, reference: str, intro: str | None,
              now: datetime) -> RfqResponseDetail:
        state = response.state
        if state == "pending" and (rfq.closed_at is not None or now >= rfq.respond_by):
            state = "expired"
        return RfqResponseDetail(
            registry=self.registry, rfq_id=rfq.rfq_id, response_id=response.response_id,
            respondent_reference=reference, offered_quantity=response.offered_quantity,
            state=state, version=response.version, terms_revision=response.terms_revision,
            introduction_id=intro,
        )

    def _views(self, rfq_id: str):
        return select(RfqResponse, RfqPartyReference.reference, RfqIntroduction.introduction_id).join(
            RfqPartyReference, and_(
                RfqPartyReference.rfq_id == RfqResponse.rfq_id,
                RfqPartyReference.namespace == RfqResponse.respondent_namespace,
                RfqPartyReference.subject == RfqResponse.respondent_subject,
            ),
        ).outerjoin(RfqIntroduction, RfqIntroduction.response_id == RfqResponse.response_id).where(
            RfqResponse.rfq_id == rfq_id,
        )

    def inbox(self, rfq_id: str) -> RfqResponseInbox:
        rfq = self._rfq(rfq_id)
        if not account_is_buyer(rfq, self.account):
            raise RfqActionError(404, "rfq_response_not_found")
        rows = self.db.execute(self._views(rfq_id).order_by(RfqResponse.created_at, RfqResponse.response_id))
        now = utcnow()
        return RfqResponseInbox(responses=[self._view(rfq, *row, now) for row in rows])

    def read(self, rfq_id: str, response_id: str) -> RfqResponseDetail:
        rfq = self._rfq(rfq_id)
        row = self.db.execute(self._views(rfq_id).where(
            RfqResponse.response_id == response_id,
        )).one_or_none()
        if row is None or not (account_is_buyer(rfq, self.account) or _account_is_respondent(row[0], self.account)):
            raise RfqActionError(404, "rfq_response_not_found")
        return self._view(rfq, *row, utcnow())

    def _introduction(self, introduction_id: str, *, lock: bool = False):
        statement = select(RfqIntroduction, RfqResponse, RfqRequest).join(
            RfqResponse, RfqResponse.response_id == RfqIntroduction.response_id,
        ).join(RfqRequest, RfqRequest.rfq_id == RfqResponse.rfq_id).where(
            RfqIntroduction.introduction_id == introduction_id, RfqRequest.kind == self.spec.kind,
        )
        row = self.db.execute(statement.with_for_update(of=RfqIntroduction) if lock else statement).one_or_none()
        if row is None or not (account_is_buyer(row[2], self.account) or _account_is_respondent(row[1], self.account)):
            raise RfqActionError(404, "rfq_introduction_not_found")
        return row

    def _require_contact_access(self, intro: RfqIntroduction) -> datetime:
        now = utcnow()
        if intro.ended_at is not None or now >= intro.contact_until:
            raise RfqActionError(410, "rfq_contact_ended")
        return now

    def read_introduction(self, introduction_id: str) -> RfqIntroductionDetail:
        intro, response, rfq = self._introduction(introduction_id)
        self._require_contact_access(intro)
        purpose = RESPONDENT_CONTACT if account_is_buyer(rfq, self.account) else BUYER_CONTACT
        binding = contact_binding(
            self.registry.name, rfq, response, purpose, intro.contact_until,
            introduction_id=intro.introduction_id,
        )
        contact = open_contact(self.db, self.keys, response.response_id, binding)
        self._require_contact_access(intro)
        return RfqIntroductionDetail(
            registry=self.registry, rfq_id=rfq.rfq_id, introduction_id=intro.introduction_id,
            version=intro.version, contact_until=intro.contact_until.replace(tzinfo=timezone.utc).isoformat(),
            contact=contact,
        )

    def end_introduction(self, introduction_id: str, inputs: ResponseVersion) -> RfqMutationReceipt:
        intro, response, _ = self._introduction(introduction_id, lock=True)
        _require_version(intro.version, inputs.version)
        intro.ended_at = self._require_contact_access(intro)
        intro.version += 1
        self._delete_contact(response.response_id)
        return RfqMutationReceipt(resource_id=intro.introduction_id, state="ended", version=intro.version)
