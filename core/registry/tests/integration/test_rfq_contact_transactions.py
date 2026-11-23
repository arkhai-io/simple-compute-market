"""Concurrent RFQ state changes in independent database sessions."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
import os
from pathlib import Path
from threading import Event, local
from uuid import uuid4

import injected_time
import pytest
from market_core.rfq import RfqAccountClaim, RfqAudience, RfqInvocation, RfqOperation, RfqTarget
from market_identity import Ed25519Signer
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from core_registry.rfq_spec import load_rfq_spec
from core_registry.db.migrations import migrate_database
from core_registry.db.models import (
    RfqContactPayload, RfqIntroduction, RfqPartyReference, RfqReplayReservation, RfqRequest, RfqResponse,
)
from core_registry.rfq_contact_crypto import RfqContactKeys
from core_registry.rfq_context import VerifiedRfqRequest
from core_registry.rfq_replay import RfqReplayKeys, execute_rfq_request
from market_core.rfq import CloseRfq, CreateRfq
from core_registry.rfq_requests import RfqActionError, RfqRequests
from market_core.rfq import OfferResponse, ResponseVersion, ShareContact
from core_registry.rfq_responses import RfqResponses

_SCHEMA = Path(__file__).resolve().parents[4] / "domains/compute/registry/rfq-schema.json"
spec = load_rfq_spec(str(_SCHEMA))

# Deterministic key material and signer for this test. Never use on a public network.
contact_keys = RfqContactKeys.model_validate_json(json.dumps({
    "current": "fixture", "keys": {"fixture": "61" * 32},
}))
replay_keys = RfqReplayKeys(current="fixture", keys={"fixture": "62" * 32})
audience = RfqAudience(
    name="registry-fixture", principal=Ed25519Signer(bytes([63]) * 32).identity.model_dump(mode="json"),
)
buyer = RfqAccountClaim(namespace="fixture", subject="buyer", can_share_contact=True)
seller = RfqAccountClaim(namespace="fixture", subject="respondent", can_share_contact=True)


def provision(sessions):
    deadline = (injected_time.now_datetime() + timedelta(days=14)).isoformat()
    requirements = {
        "shape": {"vcpu_count": 16}, "node_count": 100, "regions": ["fixture"],
        "start_earliest": "2030-01-01", "start_latest": "2030-01-03",
        "term": {"value": 6, "unit": "month"}, "respond_by": deadline,
    }
    with sessions.begin() as db:
        rfq_id = RfqRequests(db, spec, buyer, audience).create(
            CreateRfq(kind="compute", requirements=requirements)
        ).resource_id
        rfq = RfqRequests(db, spec, seller, audience).read(rfq_id)
        source = RfqResponses(db, spec, seller, audience, contact_keys)
        response = source.respond(rfq_id, OfferResponse(
            counterparty=rfq.buyer_reference, version=1, terms_revision=1,
            consent_to_share=True, contact={"email": "seller@example.test"},
        ))
        reference = db.get(RfqPartyReference, (rfq_id, seller.namespace, seller.subject)).reference
    return rfq_id, response.resource_id, reference


def race(sessions, mode, *, select_first):
    rfq_id, response_id, respondent = provision(sessions)
    owner_has_written = Event()
    contender_at_database = Event()
    roles = local()
    engine = sessions.kw["bind"]
    selection = ShareContact(
        version=1, terms_revision=1, counterparty=respondent,
        consent_to_share=True, contact={"email": "buyer@example.test"},
    )
    select_target = RfqTarget(RfqOperation.SELECT, rfq_id, response_id)

    def notice_contender(_connection, _cursor, statement, _parameters, _context, _many):
        if not getattr(roles, "contender", False):
            return
        sql = statement.upper()
        if engine.dialect.name == "sqlite" or mode == "select":
            # SQLite reserves its writer during replay admission. The duplicate
            # selection uses the same replay row on both engines.
            reached = sql.startswith("INSERT") and RfqReplayReservation.__tablename__.upper() in sql
        else:
            reached = "FOR UPDATE" in sql and RfqRequest.__tablename__.upper() in sql
        if reached:
            contender_at_database.set()

    def execute(actor, target, command, action, *, contender):
        roles.contender = contender
        if contender:
            assert owner_has_written.wait(timeout=5), "owner did not reach its durable write"
        request_id = f"select-{rfq_id}" if mode == "select" else uuid4().hex
        verified = VerifiedRfqRequest(target, RfqInvocation(
            account=actor, audience=audience, inputs=command.model_dump(mode="json"),
        ), request_id)
        with sessions() as db:
            def dispatch():
                receipt = action(db)
                if not contender:
                    db.flush()
                    owner_has_written.set()
                    assert contender_at_database.wait(timeout=5), "contender did not reach the database"
                return receipt

            try:
                return execute_rfq_request(db, verified, replay_keys, dispatch)
            except RfqActionError as error:
                assert error.status == 409
                return None

    def select_offer(*, contender):
        def action(db):
            return RfqResponses(db, spec, buyer, audience, contact_keys).select(rfq_id, response_id, selection)

        return execute(buyer, select_target, selection, action, contender=contender)

    def alternate(*, contender):
        if mode == "select":
            return select_offer(contender=contender)
        if mode == "withdraw":
            withdrawal = ResponseVersion(version=1)

            def action(db):
                responses = RfqResponses(db, spec, seller, audience, contact_keys)
                return responses.finish_pending(rfq_id, response_id, withdrawal, "withdrawn")

            target = RfqTarget(RfqOperation.WITHDRAW, rfq_id, response_id)
            return execute(seller, target, withdrawal, action, contender=contender)
        closure = CloseRfq(version=1)
        return execute(
            buyer, RfqTarget(RfqOperation.CLOSE, rfq_id), closure,
            lambda db: RfqRequests(db, spec, buyer, audience).close(rfq_id, closure),
            contender=contender,
        )

    event.listen(engine, "before_cursor_execute", notice_contender)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            selected = executor.submit(select_offer, contender=not select_first)
            other = executor.submit(alternate, contender=select_first)
            selection_receipt, alternative_receipt = selected.result(timeout=15), other.result(timeout=15)
    finally:
        event.remove(engine, "before_cursor_execute", notice_contender)

    with sessions() as db:
        response = db.get(RfqResponse, response_id)
        introductions = db.scalars(select(RfqIntroduction).where(
            RfqIntroduction.response_id == response_id,
        )).all()
        payloads = db.scalars(select(RfqContactPayload).where(
            RfqContactPayload.response_id == response_id,
        )).all()
        if select_first:
            assert selection_receipt.state == "selected"
            assert response.state == "selected" and len(introductions) == 1 and len(payloads) == 2
            assert introductions[0].introduction_id == selection_receipt.introduction_id
        else:
            assert selection_receipt is None
            assert not introductions and not payloads
            assert response.state == ("withdrawn" if mode == "withdraw" else "expired")
        if mode == "select":
            assert alternative_receipt == selection_receipt
        elif mode == "withdraw":
            assert (alternative_receipt is None) == select_first
        else:
            assert alternative_receipt.state == "closed"


@pytest.fixture(params=("sqlite", "postgresql"))
def race_sessions(request, tmp_path):
    if request.param == "postgresql":
        database = os.environ.get("TEST_RFQ_POSTGRES_URL")
        if not database:
            pytest.skip("set TEST_RFQ_POSTGRES_URL to a dedicated PostgreSQL database")
        if not database.startswith(("postgresql://", "postgresql+psycopg2://")):
            pytest.fail("TEST_RFQ_POSTGRES_URL must point to PostgreSQL")
    else:
        database = f"sqlite:///{tmp_path / 'rfq.db'}"
    migrate_database(database)
    engine = create_engine(database)
    previous = injected_time.installed()
    injected_time.install(injected_time.InjectedTime(start=1_800_000_000))
    try:
        yield sessionmaker(engine)
    finally:
        injected_time.install(previous)
        engine.dispose()


@pytest.mark.parametrize(
    "competing_mutation,select_first",
    (("withdraw", True), ("withdraw", False), ("close", True), ("close", False), ("select", True)),
)
def test_serialized_rfq_selection(race_sessions, competing_mutation, select_first):
    race(race_sessions, competing_mutation, select_first=select_first)
