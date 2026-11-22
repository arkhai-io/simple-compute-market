"""Exercise the common signed RFQ boundary and real receipt storage."""

from base64 import urlsafe_b64encode
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from threading import Barrier, Event, Lock

import httpx
import injected_time
import pytest
from fastapi import FastAPI, HTTPException, Request
from market_core.registry_descriptor import RegistryPrincipal
from market_core.rfq import (
    RfqAccountClaim,
    RfqAudience,
    RfqInvocation,
    RfqMutationReceipt,
    RfqOperation,
    RfqTarget,
)
from market_identity import Ed25519Signer, Eip191Signer, TrustedIdentitySet
from registry_client.auth import authenticate_request, authentication_headers
from registry_client.rfq_auth import sign_rfq_invocation
from sqlalchemy import Update, create_engine, event, select
from sqlalchemy.orm import Session

from core_registry.api.rfq_auth import RfqTrust
from core_registry.api.rfq_exchange import rfq_exchange
from core_registry.config import settings
from core_registry.db.migrations import migrate_database
from core_registry.db.models import Publisher, PublisherReplayReservation, RfqReplayReservation
from core_registry.main import lifespan
from core_registry.rfq_replay import RfqReplayKeys, execute_rfq_request

# Deterministic fixture credentials. Never use these on a public network.
_OLD = Ed25519Signer(bytes([1]) * 32)
_NEW = Ed25519Signer(bytes([2]) * 32)
_OTHER = Eip191Signer(bytes([3]) * 32)
_REGISTRY = Ed25519Signer(bytes([4]) * 32)
_CREATE = RfqTarget(RfqOperation.CREATE)
_READ = RfqTarget(RfqOperation.READ, "rfq-a")
_SELECT = RfqTarget(RfqOperation.SELECT, "rfq-a", "response-a")


def _audience(*, name="registry-test", signer=_REGISTRY):
    return RfqAudience(
        name=name,
        principal=RegistryPrincipal.model_validate(signer.identity.model_dump(mode="json")),
    )


def _pins(*signers):
    return TrustedIdentitySet(identities=tuple(signer.identity for signer in signers))


@pytest.fixture
def boundary(tmp_path: Path):
    url = f"sqlite:///{tmp_path / 'registry.db'}"
    migrate_database(url)
    engine = create_engine(url, connect_args={"check_same_thread": False})
    app = FastAPI()
    app.state.registry_authority_signer = _REGISTRY
    app.state.rfq_trust = RfqTrust(_audience(), {"alpha": _pins(_OLD), "beta": _pins(_OTHER)})
    app.state.rfq_replay_keys = RfqReplayKeys(
        current="first", keys={"first": bytes([5] * 32).hex()}
    )
    state = {"allow_read": True, "mutation_dispatches": 0}

    def mutate(verified, session):
        state["mutation_dispatches"] += 1
        session.add(Publisher())
        session.flush()
        if verified.invocation.inputs.get("simulate_failure"):
            raise HTTPException(409, "simulated_failure")
        if verified.target == _SELECT:
            return RfqMutationReceipt(
                resource_id="response-a", state="selected", version=2, introduction_id="intro-a"
            )
        return RfqMutationReceipt(resource_id="rfq-a", state="open", version=1)

    def read(_verified):
        if not state["allow_read"]:
            raise HTTPException(404, "not_found")
        return {"contact": "example@example.test"}

    async def exchange(target, *, body, headers):
        # Supply exactly the route-owned request data the HTTP adapter consumes.
        transmitted = httpx.Request(target.method, "http://registry.test", json=body, headers=headers)

        async def receive():
            return {"type": "http.request", "body": transmitted.content}

        request = Request(
            {
                "type": "http",
                "app": app,
                "method": target.method,
                "headers": [(name.lower(), value) for name, value in transmitted.headers.raw],
            },
            receive,
        )
        with Session(engine) as session:
            def dispatch(verified):
                if target.operation.is_read:
                    return read(verified)
                return mutate(verified, session)

            response = await rfq_exchange(request, session, target, dispatch)
        return httpx.Response(response.status_code, headers=response.headers, content=response.body)

    prior = injected_time.installed()
    injected_time.install(injected_time.InjectedTime(start=1_800_000_000))
    try:
        yield exchange, app, engine, state
    finally:
        injected_time.install(prior)
        engine.dispose()


def _invocation(*, namespace="alpha", audience=None, sharing=False, inputs=None):
    return RfqInvocation(
        audience=_audience() if audience is None else audience,
        account=RfqAccountClaim(namespace=namespace, subject="same-subject",
                                can_share_contact=sharing),
        inputs={} if inputs is None else inputs,
    )


async def _call(exchange, target, invocation, signer=_OLD, request_id="request-1", timestamp=None):
    signed = sign_rfq_invocation(
        signer=signer, target=target, invocation=invocation, request_id=request_id,
        timestamp=timestamp,
    )
    response = await exchange(target, body=signed.body(), headers=signed.headers())
    signed.verify_response(
        response.headers, body=response.json(), status=response.status_code,
    )
    return response


async def test_fresh_authority_signer_can_replay_one_mutation_across_key_rotation(boundary):
    exchange, app, engine, state = boundary
    invocation = _invocation(sharing=True, inputs={
        "consent_to_share": True, "contact": {"email": "example@example.test"}
    })

    first = await _call(exchange, _SELECT, invocation)
    assert first.status_code == 200
    app.state.rfq_trust = RfqTrust(_audience(), {"alpha": _pins(_OLD, _NEW)})
    app.state.rfq_replay_keys = RfqReplayKeys(
        current="second",
        keys={"first": bytes([5] * 32).hex(), "second": bytes([6] * 32).hex()},
    )
    assert (await _call(exchange, _SELECT, invocation)).json() == first.json()
    overlap = await _call(exchange, _SELECT, invocation, signer=_NEW)
    assert overlap.json() == first.json() == {
        "resource_id": "response-a", "state": "selected", "version": 2,
        "introduction_id": "intro-a",
    }
    app.state.rfq_trust = RfqTrust(_audience(), {"alpha": _pins(_NEW)})
    assert (await _call(exchange, _SELECT, invocation)).status_code == 401
    assert (await _call(exchange, _SELECT, invocation, signer=_NEW)).json() == first.json()
    assert state["mutation_dispatches"] == 1
    with Session(engine) as session:
        row = session.scalars(select(RfqReplayReservation)).one()
        assert row.key_id == "first"
        assert row.receipt == first.json()
        assert len(session.scalars(select(Publisher)).all()) == 1
        assert session.scalars(select(PublisherReplayReservation)).first() is None
    app.state.rfq_replay_keys = RfqReplayKeys(
        current="second", keys={"second": bytes([6] * 32).hex()}
    )
    assert (await _call(exchange, _SELECT, invocation, signer=_NEW)).status_code == 503


async def test_wrong_authority_and_changed_reuse_are_refused_before_dispatch(boundary):
    exchange, _, engine, state = boundary
    assert (await _call(exchange, _CREATE, _invocation(namespace="beta"))).status_code == 401
    wrong_name = await _call(
        exchange, _CREATE, _invocation(audience=_audience(name="another-registry")),
    )
    assert wrong_name.status_code == 401
    mistargeted = sign_rfq_invocation(
        signer=_OLD, target=_CREATE, invocation=_invocation(audience=_audience(signer=_OTHER)),
        request_id="request-1",
    )
    refused = await exchange(_CREATE, body=mistargeted.body(), headers=mistargeted.headers())
    assert refused.status_code == 401
    assert (await _call(exchange, _CREATE, _invocation(), signer=_NEW)).status_code == 401
    assert (await _call(exchange, _CREATE, _invocation())).status_code == 200
    changed = await _call(exchange, _CREATE, _invocation(inputs={"node_count": 101}))
    assert changed.status_code == 409
    assert changed.json() == {"detail": "rfq_request_id_reused"}
    assert (await _call(exchange, _CREATE, _invocation(namespace="beta"), signer=_OTHER)).status_code == 200
    assert state["mutation_dispatches"] == 2
    with Session(engine) as session:
        assert len(session.scalars(select(RfqReplayReservation)).all()) == 2


async def test_each_private_read_is_current_and_keeps_no_response_body(boundary):
    exchange, _, engine, state = boundary
    first = await _call(exchange, _READ, _invocation())
    assert first.json() == {"contact": "example@example.test"}
    assert first.headers["cache-control"] == "no-store"
    state["allow_read"] = False
    revoked = await _call(exchange, _READ, _invocation())
    assert revoked.status_code == 404
    assert "contact" not in revoked.json()
    changed = await _call(exchange, _READ, _invocation(inputs={"added_field": True}))
    assert changed.status_code == 409
    with Session(engine) as session:
        assert session.scalars(select(RfqReplayReservation)).one().receipt is None


async def test_revoked_sharing_permission_is_checked_before_a_receipt_is_served(boundary):
    exchange, _, engine, state = boundary
    inputs = {"consent_to_share": True}
    assert (await _call(exchange, _SELECT, _invocation(sharing=True, inputs=inputs))).status_code == 200
    invocation = _invocation(sharing=False, inputs=inputs)
    body = invocation.model_dump(mode="json")
    signed = authenticate_request(
        signer=_OLD, role="service", method="POST", operation=_SELECT.operation.value,
        resource=_SELECT.resource, body=body, request_id="request-1",
    )
    refused = await exchange(_SELECT, body=body, headers=authentication_headers(signed))
    assert refused.status_code == 403
    assert state["mutation_dispatches"] == 1
    with Session(engine) as session:
        assert len(session.scalars(select(RfqReplayReservation)).all()) == 1


async def test_failed_mutation_keeps_the_binding_but_rolls_back_domain_write(boundary):
    exchange, _, engine, _ = boundary
    failed = await _call(exchange, _CREATE, _invocation(inputs={"simulate_failure": True}))
    assert failed.status_code == 409
    changed = await _call(exchange, _CREATE, _invocation())
    assert changed.json() == {"detail": "rfq_request_id_reused"}
    with Session(engine) as session:
        assert session.scalars(select(RfqReplayReservation)).one().receipt is None
        assert session.scalars(select(Publisher)).first() is None


async def test_client_rejects_changed_status_of_real_registry_refusal(boundary):
    exchange, _, _, _ = boundary
    signed = sign_rfq_invocation(
        signer=_NEW, target=_CREATE, invocation=_invocation(), request_id="request-1",
    )
    response = await exchange(_CREATE, body=signed.body(), headers=signed.headers())
    assert response.status_code == 401
    signed.verify_response(
        response.headers, status=response.status_code, body=response.json(),
    )
    with pytest.raises(ValueError, match="invalid registry response"):
        signed.verify_response(
            response.headers, status=200, body=response.json(),
            )


async def test_stale_proof_is_refused_even_for_a_committed_retry(boundary):
    exchange, _, engine, state = boundary
    invocation = _invocation()
    assert (await _call(exchange, _CREATE, invocation)).status_code == 200
    stale = await _call(
        exchange, _CREATE, invocation,
        timestamp=injected_time.now() - 301,
    )
    assert stale.status_code == 401
    assert state["mutation_dispatches"] == 1
    with Session(engine) as session:
        assert len(session.scalars(select(RfqReplayReservation)).all()) == 1


def test_concurrent_requests_share_one_mutation_and_receipt(boundary):
    _, app, engine, _ = boundary
    both_bound = Barrier(2)
    attempted_lock = Event()
    second_attempting_lock = Event()
    attempts_lock = Lock()
    signed = sign_rfq_invocation(
        signer=_OLD, target=_CREATE, invocation=_invocation(), request_id="request-1",
    )
    verified = app.state.rfq_trust.verify(
        headers=signed.headers(), method=_CREATE.method, target=_CREATE, body=signed.body(),
    )

    class BoundRequestSession(Session):
        def commit(self):
            super().commit()
            if not self.info.get("first_commit"):
                self.info["first_commit"] = True
                both_bound.wait(timeout=5)

    def notice_competing_lock(_connection, _cursor, _statement, _parameters, context, _many):
        statement = getattr(context.compiled, "statement", None)
        if isinstance(statement, Update) and statement.table.name == RfqReplayReservation.__tablename__:
            with attempts_lock:
                if attempted_lock.is_set():
                    second_attempting_lock.set()
                attempted_lock.set()

    def submit():
        with BoundRequestSession(engine) as session:
            def mutate():
                session.add(Publisher())
                session.flush()
                assert second_attempting_lock.wait(timeout=5)
                return RfqMutationReceipt(resource_id="rfq-a", state="open", version=1)

            return execute_rfq_request(session, verified, app.state.rfq_replay_keys, mutate)

    event.listen(engine, "before_cursor_execute", notice_competing_lock)
    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            first = workers.submit(submit)
            second = workers.submit(submit)
            receipts = first.result(timeout=10), second.result(timeout=10)
    finally:
        event.remove(engine, "before_cursor_execute", notice_competing_lock)

    assert receipts[0] == receipts[1]
    with Session(engine) as session:
        assert len(session.scalars(select(RfqReplayReservation)).all()) == 1
        assert len(session.scalars(select(Publisher)).all()) == 1


async def test_client_accepts_only_the_registry_principal_in_its_signed_audience(boundary):
    exchange, app, _, _ = boundary
    signed = sign_rfq_invocation(
        signer=_OLD, target=_CREATE, invocation=_invocation(), request_id="request-1",
    )
    app.state.registry_authority_signer = _OTHER
    response = await exchange(_CREATE, body=signed.body(), headers=signed.headers())

    with pytest.raises(ValueError, match="wrong_principal"):
        signed.verify_response(
            response.headers, status=response.status_code, body=response.json(),
        )


@pytest.mark.parametrize(
    "has_pins,has_key_file,schema",
    [(False, True, "disabled"), (True, False, "disabled"), (True, True, "disabled"),
     (True, True, "compute"), (True, True, "malformed")],
)
async def test_lifespan_loads_rfq_authority_and_schema_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, has_pins, has_key_file, schema,
):
    database_file = tmp_path / "startup.db"
    url = f"sqlite:///{database_file}"
    if schema == "malformed":
        # If startup probes persistence first, this file fails the database
        # check and masks the configuration error.
        database_file.write_bytes(b"invalid SQLite database")
    else:
        migrate_database(url)
    authority_file = tmp_path / "authority.key"
    # A deterministic fixture credential. Never use it on a public network.
    authority_file.write_bytes(urlsafe_b64encode(bytes([4]) * 32).rstrip(b"="))
    key_file = tmp_path / "rfq-digests.json"
    key_file.write_text(json.dumps({"current": "test", "keys": {"test": bytes([5] * 32).hex()}}))
    schema_path = None
    if schema == "compute":
        root = Path(__file__).resolve().parents[4]
        schema_path = root / "domains" / "compute" / "registry" / "rfq-schema.json"
    elif schema == "malformed":
        schema_path = tmp_path / "rfq-schema.json"
        schema_path.write_text('{"kind": "compute"}')
    config = {
        "database_url": url,
        "bootstrap_api_key": None,
        "registry_authority_id": "registry-test",
        "registry_authority_scheme": "ed25519",
        "registry_authority_identifier": _REGISTRY.identity.identifier,
        "registry_authority_credential_file": str(authority_file),
        "registry_descriptor_base_url": "http://registry.test",
        "registry_descriptor_display_name": "Test registry",
        "registry_descriptor_operator_identity": "test-operator",
        "require_read_api_key": False,
        "registry_descriptor_access_acquisition_pointer": None,
        "registry_rfq_authorities": {"alpha": _pins(_OLD)} if has_pins else {},
        "registry_rfq_replay_keys_file": str(key_file) if has_key_file else None,
        "registry_rfq_spec_path": str(schema_path) if schema_path else None,
    }
    for name, value in config.items():
        monkeypatch.setattr(settings, name, value)
    app = FastAPI()
    if schema == "malformed":
        with pytest.raises(RuntimeError, match="invalid REGISTRY_RFQ_SPEC_PATH configuration"):
            async with lifespan(app):
                pytest.fail("invalid RFQ configuration must fail before startup")
        assert database_file.read_bytes() == b"invalid SQLite database"
        assert not hasattr(app.state, "registry_authority_signer")
        return
    async with lifespan(app):
        assert app.state.registry_descriptor.authority.name == "registry-test"
        if schema == "compute":
            assert app.state.rfq_spec.kind == "compute"
        else:
            assert app.state.rfq_spec is None
        if has_pins and has_key_file:
            assert app.state.rfq_trust.audience == _audience()
            assert app.state.rfq_replay_keys.current == "test"
        else:
            assert app.state.rfq_trust is None
            assert app.state.rfq_replay_keys is None
