"""RFQ consent, pair isolation and retention through the registry HTTP boundary."""

from datetime import datetime, timedelta, timezone
import json
import os
import sqlite3
import subprocess
import sys
from uuid import uuid4

import httpx
from market_core.rfq import (
    CloseRfq, EditRfq, OfferResponse, ResponseVersion, RfqAccountClaim,
    RfqInvocation, RfqOperation, RfqTarget, ShareContact,
)
import pytest
from registry_client import RegistryClientError, authenticate_request
from registry_client.rfq_auth import SignedRfqRequest, sign_rfq_invocation
from registry_client.rfq_registry import RfqRegistryClient
from sqlalchemy import create_engine, make_url, select
from sqlalchemy.schema import CreateSchema, DropSchema

from core_registry.db.models import RfqContactPayload, RfqIntroduction, RfqReplayReservation, utcnow
from core_registry.rfq_contact_crypto import RfqContactKeys, RfqContactUnavailable
from core_registry.rfq_contact_store import require_retained_keys, sweep_contact_batch
from .test_rfq_discovery import Registry, _AUTHORITY, registries, requirements


def actor(subject, *, sharing=True):
    return RfqAccountClaim(namespace="test-accounts", subject=subject, can_share_contact=sharing)


@pytest.fixture
def configured_registry(tmp_path, registries, request):
    create, clock = registries
    key_file = tmp_path / "contact-keys.json"
    # Deterministic encryption key for synthetic tests. Never use it on a public network.
    key_file.write_text(json.dumps({"current": "fixture", "keys": {"fixture": "42" * 32}}))
    if getattr(request, "param", "sqlite") == "sqlite":
        registry = create()
        registry.configuration["registry_rfq_contact_keys_file"] = str(key_file)
        yield registry, clock, key_file
        return

    database = os.environ.get("TEST_RFQ_POSTGRES_URL")
    if not database:
        pytest.skip("set TEST_RFQ_POSTGRES_URL to a dedicated PostgreSQL database")
    base = make_url(database)
    if base.drivername not in {"postgresql", "postgresql+psycopg2"}:
        pytest.fail("TEST_RFQ_POSTGRES_URL must point to PostgreSQL")
    engine = create_engine(base)
    schema = f"rfq_{uuid4().hex}"
    try:
        with engine.begin() as db:
            db.execute(CreateSchema(schema))
        try:
            url = base.update_query_dict({"options": f"-csearch_path={schema}"})
            registry = create(url=url.render_as_string(hide_password=False))
            registry.configuration["registry_rfq_contact_keys_file"] = str(key_file)
            try:
                yield registry, clock, key_file
            finally:
                registry.engine.dispose()
        finally:
            with engine.begin() as db:
                db.execute(DropSchema(schema, cascade=True))
    finally:
        engine.dispose()


def client_for(registry, application):
    return RfqRegistryClient(
        "http://test", signer=_AUTHORITY, audience=registry.audience,
        transport=httpx.ASGITransport(app=application),
    )


def selection(response):
    return ShareContact(
        version=response.version, terms_revision=response.terms_revision,
        counterparty=response.respondent_reference, consent_to_share=True,
        contact={"email": "buyer@example.test"},
    )


@pytest.mark.parametrize("material_change", [
    {"node_count": 80},
    {"description": "Flexible order subject to utilization estimates"},
], ids=["quantity", "ambiguous-commercial-wording"])
@pytest.mark.parametrize("configured_registry", ("sqlite", "postgresql"), indirect=True)
async def test_current_consent_and_independent_introductions(configured_registry, material_change):
    registry, clock, _ = configured_registry
    buyer, alice, bob = actor("buyer"), actor("alice"), actor("bob")
    posted = await registry.create(requirements(), subject=buyer.subject)
    rfq_id = posted.resource_id

    async with registry.running() as application, client_for(registry, application) as client:
        request = await client.read(alice, rfq_id)
        offer_a = OfferResponse(
            version=1, terms_revision=1, counterparty=request.buyer_reference,
            consent_to_share=True, offer={"offered_node_count": 40},
            contact={"email": "alice@example.test"},
        )
        offer_b = offer_a.model_copy(update={"contact": {"email": "bob@example.test"}})
        first = await client.respond(alice, rfq_id, offer_a)
        with pytest.raises(RegistryClientError, match="HTTP 409"):
            await client.respond(alice, rfq_id, offer_a)
        second = await client.respond(bob, rfq_id, offer_b, request_id="response-bob")

        inbox = {entry.response_id: entry for entry in (await client.response_inbox(buyer, rfq_id)).responses}
        row_a, row_b = inbox[first.resource_id], inbox[second.resource_id]
        assert row_a.offered_quantity == row_b.offered_quantity == 40
        assert "contact" not in row_a.model_dump()
        with pytest.raises(RegistryClientError, match="HTTP 404"):
            await client.read_response(bob, rfq_id, first.resource_id)

        consent = selection(row_a)
        accepted = await client.select(buyer, rfq_id, first.resource_id, consent, request_id="first-selection")
        assert await client.select(buyer, rfq_id, first.resource_id, consent, request_id="first-selection") == accepted
        changed = consent.model_copy(update={"contact": {"email": "changed@example.test"}})
        with pytest.raises(RegistryClientError, match="rfq_request_id_reused"):
            await client.select(buyer, rfq_id, first.resource_id, changed, request_id="first-selection")

        await client.edit(buyer, rfq_id, EditRfq(
            version=request.version, requirements=request.requirements | material_change,
        ))
        with pytest.raises(RegistryClientError, match="HTTP 409"):
            await client.select(buyer, rfq_id, second.resource_id, selection(row_b))
        old = await client.read_response(bob, rfq_id, second.resource_id)
        assert old.state == "superseded"
        clock.set(clock.now() + 60)
        renewed_input = offer_b.model_copy(update={"version": old.version, "terms_revision": 2})
        renewed = await client.reconfirm(bob, rfq_id, second.resource_id, renewed_input)
        current = await client.read_response(buyer, rfq_id, renewed.resource_id)
        assert current.respondent_reference == old.respondent_reference
        second_accept = await client.select(buyer, rfq_id, renewed.resource_id, selection(current))
        assert accepted.introduction_id and second_accept.introduction_id

        view_a = await client.read_introduction(buyer, accepted.introduction_id, request_id="read-first")
        assert view_a.contact == offer_a.contact
        assert (await client.read_introduction(alice, accepted.introduction_id)).contact == consent.contact
        with pytest.raises(RegistryClientError, match="HTTP 404"):
            await client.read_introduction(bob, accepted.introduction_id)
        await client.end_introduction(alice, accepted.introduction_id, ResponseVersion(version=view_a.version))
        with pytest.raises(RegistryClientError, match="HTTP 410"):
            await client.read_introduction(buyer, accepted.introduction_id, request_id="read-first")

        rfq = await client.read(buyer, rfq_id)
        pending = await client.respond(actor("charlie"), rfq_id, offer_b.model_copy(update={
            "version": rfq.version, "terms_revision": rfq.terms_revision,
        }))
        await client.close(buyer, rfq_id, CloseRfq(version=rfq.version))
        assert (await client.read_response(buyer, rfq_id, pending.resource_id)).state == "expired"

        retention = application.state.rfq_contact_retention
        await retention.pause()
        view_b = await client.read_introduction(buyer, second_accept.introduction_id)
        assert view_b.contact == offer_b.contact
        with registry.sessions() as db:
            first_intro = db.get(RfqIntroduction, accepted.introduction_id)
            second_intro = db.get(RfqIntroduction, second_accept.introduction_id)
            assert second_intro.completed_at == utcnow()
            assert second_intro.contact_until - second_intro.completed_at == timedelta(days=30)
            assert second_intro.contact_until - first_intro.contact_until == timedelta(minutes=1)
            assert datetime.fromisoformat(view_b.contact_until) == second_intro.contact_until.replace(tzinfo=timezone.utc)
        clock.set(int(datetime.fromisoformat(view_b.contact_until).timestamp()))
        with registry.sessions() as db:
            assert len(db.scalars(select(RfqContactPayload)).all()) == 2
        with pytest.raises(RegistryClientError, match="HTTP 410"):
            await client.read_introduction(bob, second_accept.introduction_id)
        await retention.step()
        with registry.sessions() as db:
            assert not db.scalars(select(RfqContactPayload)).all()
            receipts = db.scalars(select(RfqReplayReservation.receipt)).all()
            assert accepted.model_dump(mode="json", exclude_none=True) in receipts
            allowed_fields = {"resource_id", "state", "version", "terms_revision", "introduction_id"}
            assert all(set(receipt) <= allowed_fields for receipt in receipts if receipt is not None)


async def test_permission_is_rechecked_before_replaying_an_offer(configured_registry):
    registry, _, _ = configured_registry
    rfq_id = (await registry.create()).resource_id
    respondent = actor("respondent")
    async with registry.running() as application, client_for(registry, application) as client:
        request = await client.read(respondent, rfq_id)
        offer = OfferResponse(
            version=1, terms_revision=1, counterparty=request.buyer_reference,
            consent_to_share=True, contact={"email": "respondent@example.test"},
        )
        await client.respond(respondent, rfq_id, offer, request_id="permission-retry")
        target = RfqTarget(RfqOperation.RESPOND, rfq_id)
        invocation = RfqInvocation(
            account=actor(respondent.subject, sharing=False), audience=registry.audience,
            inputs=offer.model_dump(mode="json"),
        )
        # Use the producer's lower-level signer to exercise a claim the authority API refuses to issue.
        signed = SignedRfqRequest(authenticate_request(
            signer=_AUTHORITY, role=target.caller_role, method=target.method,
            operation=target.operation.value, resource=target.resource,
            body=invocation.model_dump(mode="json"), request_id="permission-retry",
        ), invocation)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application), base_url="http://test",
        ) as raw_client:
            response = await raw_client.post(target.path, headers=signed.headers(), json=signed.body())
        assert response.status_code == 403
        signed.verify_response(response.headers, status=response.status_code, body=response.json())


async def test_rotation_and_restore_keep_contact_ciphertext_out_of_live_reads(configured_registry, tmp_path):
    registry, _, key_file = configured_registry
    buyer, seller = actor("buyer"), actor("seller")
    created = await registry.create(subject=buyer.subject)
    async with registry.running() as application, client_for(registry, application) as client:
        rfq = await client.read(seller, created.resource_id)
        offer = OfferResponse(
            version=1, terms_revision=1, counterparty=rfq.buyer_reference,
            consent_to_share=True, contact={"email": "seller@example.test"},
        )
        response = await client.respond(seller, rfq.rfq_id, offer)
        current = await client.read_response(buyer, rfq.rfq_id, response.resource_id)
        accepted = await client.select(buyer, rfq.rfq_id, response.resource_id, selection(current))
        intro_id = accepted.introduction_id
        assert intro_id is not None

    renewed = {"current": "replacement", "keys": {"replacement": "41" * 32}}
    renewed_keys = RfqContactKeys.model_validate_json(json.dumps(renewed))
    mixed = renewed | {"keys": renewed["keys"] | {"fixture": "42" * 32}}
    with registry.sessions() as db:
        rows = db.scalars(select(RfqContactPayload)).all()
        assert len(rows) == 2
        assert all(len(row.nonce) == 12 and b"example.test" not in row.ciphertext for row in rows)
        with pytest.raises(RfqContactUnavailable):
            require_retained_keys(db, renewed_keys)
    key_file.write_text(json.dumps(renewed))
    with pytest.raises(RfqContactUnavailable, match="retained RFQ contact key"):
        async with registry.running():
            pytest.fail("startup must stay closed while a retained key is missing")
    key_file.write_text(json.dumps(mixed))
    rotated = subprocess.run(
        [sys.executable, "-c", "from core_registry.rfq_contact_admin import main; main()", "rotate"],
        cwd=tmp_path,
        env={
            **{key: os.environ[key] for key in ("PATH", "PYTHONPATH") if key in os.environ},
            "DATABASE_URL": registry.configuration["database_url"],
            "REGISTRY_AUTHORITY_ID": registry.audience.name,
            "REGISTRY_RFQ_CONTACT_KEYS_FILE": str(key_file),
            "TIME_SOURCE": "injected",
        },
        capture_output=True, text=True, timeout=10,
    )
    assert rotated.returncode == 0, rotated.stderr
    assert "Re-encrypted payloads: 2." in rotated.stdout
    key_file.write_text(json.dumps(renewed))

    backup = tmp_path / "before-end.db"
    with sqlite3.connect(registry.engine.url.database) as live, sqlite3.connect(backup) as saved:
        live.backup(saved)
    async with registry.running() as application, client_for(registry, application) as client:
        view = await client.read_introduction(buyer, intro_id)
        assert view.contact == offer.contact
        await client.end_introduction(seller, intro_id, ResponseVersion(version=view.version))

    restored = Registry(backup, name=registry.audience.name, seed=bytes([23]) * 32, configured=True)
    restored.configuration["registry_rfq_contact_keys_file"] = str(key_file)
    restored.configuration["registry_rfq_redact_restored_contacts"] = True
    try:
        async with restored.running() as application, client_for(restored, application) as client:
            with pytest.raises(RegistryClientError, match="HTTP 503"):
                await client.read_introduction(buyer, intro_id)
            with restored.sessions() as db:
                assert not db.scalars(select(RfqContactPayload)).all()
        restored.configuration["registry_rfq_redact_restored_contacts"] = False
        async with restored.running() as application, client_for(restored, application) as client:
            with pytest.raises(RegistryClientError, match="rfq_contact_ended"):
                await client.read_introduction(buyer, intro_id)
    finally:
        restored.engine.dispose()


@pytest.mark.parametrize("configured_registry", ("sqlite", "postgresql"), indirect=True)
async def test_cosmetic_edits_preserve_pending_consent_but_deadline_stops_selection(configured_registry):
    registry, clock, _ = configured_registry
    buyer, seller = actor("buyer"), actor("seller")
    created = await registry.create(subject=buyer.subject)
    async with registry.running() as application, client_for(registry, application) as client:
        rfq = await client.read(seller, created.resource_id)
        offer = OfferResponse(
            version=1, terms_revision=1, counterparty=rfq.buyer_reference,
            consent_to_share=True, contact={"email": "seller@example.test"},
        )
        response = await client.respond(seller, rfq.rfq_id, offer)
        await client.respond(actor("other-seller"), rfq.rfq_id, offer)
        await application.state.rfq_contact_retention.pause()
        await client.edit(buyer, rfq.rfq_id, EditRfq(
            version=rfq.version,
            requirements=rfq.requirements | {"regions": list(reversed(rfq.requirements["regions"]))},
        ))
        current = await client.read_response(buyer, rfq.rfq_id, response.resource_id)
        assert current.state == "pending" and current.terms_revision == 1

        clock.set(int(datetime.fromisoformat(rfq.requirements["respond_by"]).timestamp()))
        with pytest.raises(RegistryClientError, match="rfq_not_open"):
            await client.select(buyer, rfq.rfq_id, response.resource_id, selection(current))
        assert (await client.read_response(buyer, rfq.rfq_id, response.resource_id)).state == "expired"
        with registry.sessions.begin() as db:
            assert len(db.scalars(select(RfqContactPayload)).all()) == 2
            assert sweep_contact_batch(db, utcnow(), batch_size=1).removed == 1
        with registry.sessions() as db:
            assert len(db.scalars(select(RfqContactPayload)).all()) == 1
    registry.configuration["registry_rfq_contact_keys_file"] = None
    registry.configuration["registry_rfq_spec_path"] = None
    async with registry.running():
        with registry.sessions() as db:
            assert not db.scalars(select(RfqContactPayload)).all()


async def test_dismissal_and_withdrawal_remove_only_their_pending_contact(configured_registry):
    registry, _, _ = configured_registry
    buyer, alice, bob = actor("buyer"), actor("alice"), actor("bob")
    rfq_id = (await registry.create(subject=buyer.subject)).resource_id
    async with registry.running() as application, client_for(registry, application) as client:
        request = await client.read(alice, rfq_id)
        offer = OfferResponse(
            version=request.version, terms_revision=request.terms_revision,
            counterparty=request.buyer_reference, consent_to_share=True,
            contact={"email": "respondent@example.test"},
        )
        first = await client.respond(alice, rfq_id, offer)
        second = await client.respond(bob, rfq_id, offer, request_id="original-offer")
        with pytest.raises(RegistryClientError, match="HTTP 404"):
            await client.dismiss(alice, rfq_id, first.resource_id, ResponseVersion(version=first.version))
        dismissed = await client.dismiss(buyer, rfq_id, first.resource_id, ResponseVersion(version=first.version))
        assert dismissed.state == "dismissed"
        with registry.sessions() as db:
            assert db.scalars(select(RfqContactPayload.response_id)).all() == [second.resource_id]

        withdrawn = await client.withdraw(
            bob, rfq_id, second.resource_id, ResponseVersion(version=second.version), request_id="withdraw-offer",
        )
        assert withdrawn.state == "withdrawn"
        assert await client.withdraw(
            bob, rfq_id, second.resource_id, ResponseVersion(version=second.version), request_id="withdraw-offer",
        ) == withdrawn
        with registry.sessions() as db:
            assert not db.scalars(select(RfqContactPayload)).all()
        assert await client.respond(bob, rfq_id, offer, request_id="original-offer") == second
        with registry.sessions() as db:
            assert not db.scalars(select(RfqContactPayload)).all()
        replacement = await client.respond(bob, rfq_id, offer)
        assert replacement.resource_id != second.resource_id
        assert replacement.terms_revision == second.terms_revision



async def test_unknown_and_unauthorized_private_records_have_the_same_refusal(configured_registry):
    registry, _, _ = configured_registry
    buyer, seller, outsider = actor("buyer"), actor("seller"), actor("outsider")
    created = await registry.create(subject=buyer.subject)
    async with registry.running() as application, client_for(registry, application) as client:
        rfq = await client.read(seller, created.resource_id)
        offer = OfferResponse(
            version=rfq.version, terms_revision=rfq.terms_revision,
            counterparty=rfq.buyer_reference, consent_to_share=True,
            contact={"email": "seller@example.test"},
        )
        response = await client.respond(seller, rfq.rfq_id, offer)
        await client.close(buyer, rfq.rfq_id, CloseRfq(version=rfq.version))
        for requested_id in (rfq.rfq_id, "unknown-rfq"):
            with pytest.raises(RegistryClientError, match=r"HTTP 404\nrfq_response_not_found"):
                await client.response_inbox(outsider, requested_id)
            with pytest.raises(RegistryClientError, match=r"HTTP 404\nrfq_response_not_found"):
                await client.read_response(outsider, requested_id, response.resource_id)
            with pytest.raises(RegistryClientError, match=r"HTTP 404\nrfq_response_not_found"):
                await client.reconfirm(outsider, requested_id, response.resource_id, offer)
            with pytest.raises(RegistryClientError, match=r"HTTP 404\nrfq_not_found"):
                await client.respond(outsider, requested_id, offer)



async def test_malformed_wire_input_leaves_no_replay_binding(configured_registry):
    registry, _, _ = configured_registry
    buyer, seller = actor("buyer"), actor("seller")
    created = await registry.create(subject=buyer.subject)
    # Rejection path for malformed inputs the typed RFQ client cannot construct.
    async with registry.running() as application, client_for(registry, application) as client:
        rfq = await client.read(seller, created.resource_id)
        offer = OfferResponse(
            version=rfq.version, terms_revision=rfq.terms_revision,
            counterparty=rfq.buyer_reference, consent_to_share=True,
            contact={"email": "seller@example.test"},
        )
        malformed = offer.model_dump(mode="json", exclude={"version"})
        target = RfqTarget(RfqOperation.RESPOND, rfq.rfq_id)
        signed = sign_rfq_invocation(
            signer=_AUTHORITY, target=target, request_id="corrected-wire-input",
            invocation=RfqInvocation(account=seller, audience=registry.audience, inputs=malformed),
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application), base_url="http://test",
        ) as raw_client:
            response = await raw_client.post(target.path, headers=signed.headers(), json=signed.body())
        assert response.status_code == 422
        signed.verify_response(response.headers, status=response.status_code, body=response.json())
        assert (await client.respond(seller, rfq.rfq_id, offer, request_id="corrected-wire-input")).state == "pending"
