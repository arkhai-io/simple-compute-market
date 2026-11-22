"""Registry RFQ posting, discovery and buyer-owned request transitions."""

from base64 import b64decode, urlsafe_b64encode
from binascii import Error as Base64Error
from datetime import datetime
from hashlib import sha256
from typing import Any, Literal
from uuid import uuid4

from market_core.rfq import (
    CloseRfq,
    CreateRfq,
    EditRfq,
    RfqAccountClaim,
    RfqAudience,
    RfqDetail,
    RfqInput,
    RfqMutationReceipt,
    RfqReference,
    RfqSearchPage,
    RfqSummary,
    SearchRfqs,
)
from market_identity import canonical_json
from pydantic import Field, JsonValue, NaiveDatetime, ValidationError
from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from core_registry.filter_eval import Criterion, evaluate_path
from core_registry.rfq_spec import RfqSpec
from core_registry.db.models import RfqPartyReference, RfqRequest, RfqTermsRevision, utcnow


class RfqActionError(Exception):
    def __init__(self, status: int, code: str):
        super().__init__(code)
        self.status = status
        self.code = code


class _Cursor(RfqInput):
    created_at: NaiveDatetime
    rfq_id: RfqReference
    query: str = Field(pattern=r"^[0-9a-f]{64}$")

    def encode(self) -> str:
        return urlsafe_b64encode(self.model_dump_json().encode()).decode("ascii")

    @classmethod
    def decode(cls, value: str) -> "_Cursor":
        try:
            raw = b64decode(value, altchars=b"-_", validate=True)
            return cls.model_validate_json(raw)
        except (Base64Error, ValidationError, ValueError) as exc:
            raise RfqActionError(422, "invalid_rfq_cursor") from exc


def _matches(requirements: dict[str, Any], criteria: list[Criterion]) -> bool:
    return all(evaluate_path(requirements, criterion) for criterion in criteria)


def _state(rfq: RfqRequest, now: datetime) -> Literal["open", "closed", "expired"]:
    if rfq.closed_at is not None:
        return "closed"
    return "open" if now < rfq.respond_by else "expired"


def _is_buyer(rfq: RfqRequest, account: RfqAccountClaim) -> bool:
    return (rfq.buyer_namespace, rfq.buyer_subject) == (account.namespace, account.subject)


class RfqRequests:
    """Operate in the signed exchange's transaction without committing it."""

    def __init__(self, db: Session, spec: RfqSpec, account: RfqAccountClaim, registry: RfqAudience):
        self.db = db
        self.spec = spec
        self.account = account
        self.registry = registry

    def _require_kind(self, kind: str) -> None:
        if kind != self.spec.kind:
            raise RfqActionError(503, "rfq_kind_not_supported")

    def _require_future_deadline(self, body: dict[str, JsonValue], now: datetime) -> datetime:
        deadline = self.spec.response_deadline(body)
        if deadline <= now:
            raise RfqActionError(422, "rfq_deadline_not_in_future")
        return deadline

    def create(self, inputs: CreateRfq) -> RfqMutationReceipt:
        self._require_kind(inputs.kind)
        self.spec.validate_requirements(inputs.requirements)
        now = utcnow()
        deadline = self._require_future_deadline(inputs.requirements, now)
        rfq_id = uuid4().hex
        self.db.add(RfqRequest(
            rfq_id=rfq_id, kind=inputs.kind, buyer_namespace=self.account.namespace,
            buyer_subject=self.account.subject, requirements=inputs.requirements,
            version=1, terms_revision=1, created_at=now, respond_by=deadline,
        ))
        self.db.flush()
        self.db.add_all([
            RfqPartyReference(
                rfq_id=rfq_id, namespace=self.account.namespace, subject=self.account.subject,
                reference=uuid4().hex,
            ),
            RfqTermsRevision(rfq_id=rfq_id, revision=1, requirements=inputs.requirements, created_at=now),
        ])
        return RfqMutationReceipt(resource_id=rfq_id, state="open", version=1, terms_revision=1)

    def _summary(self, rfq: RfqRequest, now: datetime) -> RfqSummary:
        return RfqSummary(
            rfq_id=rfq.rfq_id, kind=rfq.kind, registry=self.registry,
            requirements=rfq.requirements, version=rfq.version,
            terms_revision=rfq.terms_revision, state=_state(rfq, now),
        )

    def read(self, rfq_id: str) -> RfqDetail:
        result = self.db.execute(
            select(RfqRequest, RfqPartyReference.reference)
            .join(RfqPartyReference, and_(
                RfqPartyReference.rfq_id == RfqRequest.rfq_id,
                RfqPartyReference.namespace == RfqRequest.buyer_namespace,
                RfqPartyReference.subject == RfqRequest.buyer_subject,
            ))
            .where(RfqRequest.rfq_id == rfq_id, RfqRequest.kind == self.spec.kind)
        ).one_or_none()
        if result is None:
            raise RfqActionError(404, "rfq_not_found")
        record, reference = result
        summary = self._summary(record, utcnow())
        if summary.state != "open" and not _is_buyer(record, self.account):
            raise RfqActionError(404, "rfq_not_found")
        return RfqDetail(**summary.model_dump(), buyer_reference=reference)

    def search(self, inputs: SearchRfqs) -> RfqSearchPage:
        self._require_kind(inputs.kind)
        criteria = self.spec.search_criteria(inputs.filters)
        now = utcnow()
        query = sha256(canonical_json({
            "registry": self.registry.model_dump(mode="json"), "kind": inputs.kind,
            "filters": inputs.filters,
        })).hexdigest()
        open_requests = select(RfqRequest).where(
            RfqRequest.kind == inputs.kind, RfqRequest.closed_at.is_(None), RfqRequest.respond_by > now,
        )
        if inputs.cursor is not None:
            cursor = _Cursor.decode(inputs.cursor)
            if cursor.query != query:
                raise RfqActionError(409, "stale_rfq_cursor")
            anchor = self.db.scalar(open_requests.where(
                RfqRequest.rfq_id == cursor.rfq_id, RfqRequest.created_at == cursor.created_at,
            ))
            if anchor is None or not _matches(anchor.requirements, criteria):
                raise RfqActionError(409, "stale_rfq_cursor")
            open_requests = open_requests.where(or_(
                RfqRequest.created_at < cursor.created_at,
                and_(RfqRequest.created_at == cursor.created_at, RfqRequest.rfq_id < cursor.rfq_id),
            ))

        results: list[RfqSummary] = []
        last: _Cursor | None = None
        ordered = open_requests.order_by(RfqRequest.created_at.desc(), RfqRequest.rfq_id.desc())
        with self.db.scalars(ordered.execution_options(yield_per=100)) as records:
            for record in records:
                if not _matches(record.requirements, criteria):
                    continue
                if len(results) == inputs.page_size:
                    assert last is not None
                    return RfqSearchPage(results=results, next_cursor=last.encode())
                results.append(self._summary(record, now))
                last = _Cursor(created_at=record.created_at, rfq_id=record.rfq_id, query=query)
        return RfqSearchPage(results=results)

    def _lock_buyer_request(self, rfq_id: str, version: int) -> RfqRequest:
        record = self.db.scalar(select(RfqRequest).where(
            RfqRequest.rfq_id == rfq_id, RfqRequest.kind == self.spec.kind,
            RfqRequest.buyer_namespace == self.account.namespace,
            RfqRequest.buyer_subject == self.account.subject,
        ).with_for_update())
        if record is None:
            raise RfqActionError(404, "rfq_not_found")
        if record.version != version:
            raise RfqActionError(409, "stale_rfq_version")
        return record

    def _replace_open(self, rfq_id: str, version: int, now: datetime, **values: Any) -> None:
        result = self.db.execute(update(RfqRequest).where(
            RfqRequest.rfq_id == rfq_id, RfqRequest.version == version,
            RfqRequest.closed_at.is_(None), RfqRequest.respond_by > now,
        ).values(version=version + 1, **values))
        if result.rowcount != 1:
            raise RfqActionError(409, "rfq_not_open")

    def edit(self, rfq_id: str, inputs: EditRfq) -> RfqMutationReceipt:
        record = self._lock_buyer_request(rfq_id, inputs.version)
        self.spec.validate_requirements(inputs.requirements)
        changed = self.spec.canonical_terms(record.requirements) != self.spec.canonical_terms(inputs.requirements)
        revision = record.terms_revision + int(changed)
        now = utcnow()
        deadline = self._require_future_deadline(inputs.requirements, now)
        self._replace_open(
            rfq_id, inputs.version, now, requirements=inputs.requirements,
            respond_by=deadline, terms_revision=revision,
        )
        if changed:
            self.db.add(RfqTermsRevision(
                rfq_id=rfq_id, revision=revision, requirements=inputs.requirements, created_at=now,
            ))
        return RfqMutationReceipt(
            resource_id=rfq_id, state="open", version=inputs.version + 1, terms_revision=revision,
        )

    def close(self, rfq_id: str, inputs: CloseRfq) -> RfqMutationReceipt:
        record = self._lock_buyer_request(rfq_id, inputs.version)
        now = utcnow()
        self._replace_open(rfq_id, inputs.version, now, closed_at=now)
        return RfqMutationReceipt(
            resource_id=rfq_id, state="closed", version=inputs.version + 1,
            terms_revision=record.terms_revision,
        )
