"""Installed typed signed HTTP, SQLite restart, and a synthetic SMTP boundary."""

import asyncio
import copy
import json
import sqlite3
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from email.message import EmailMessage
from email.parser import BytesParser
from email.policy import default

import httpx
import pytest
from arkhai_bare_metal_storefront import delivery, server
from market_contact_exchange import MECHANISM
from market_contact_exchange.delivery_contract import finalization_resource
from market_contact_exchange.fixtures.delivery import DELIVERY_CONFIG, POLICY, REVIEW
from market_delivery.builtin.smtp_attempt import smtp_attempt
from market_settlement_runtime import (
    ConditionOutcome,
    MaterializationOutcome,
    SettlementManualRequired,
    derive_obligation_ref,
)
from test_contact_only_runtime import (
    BUYER,
    CONFIG,
    OUTSIDER,
    SELLER,
    SELLER_CONTACT,
    _accept_contact,
    _server,
    _signed_headers,
    _transport,
)
from test_contact_only_runtime import (
    environment as environment,
)


class RecordingSMTP:
    def __init__(self, received, *args, **kwargs):
        self.received = received
        self.sock = self
        self.tls = False

    def settimeout(self, value):
        assert 0 < value <= 10

    def ehlo(self):
        pass

    def has_extn(self, name):
        return name == "starttls"

    def starttls(self, *, context):
        assert context.check_hostname and context.verify_mode == 2
        self.tls = True

    def login(self, username, password):
        assert self.tls

    def mail(self, sender):
        return 250, b"ok"

    def rcpt(self, address):
        self.address = address
        return 250, b"ok"

    def data(self, body):
        self.received.append((self.address, body))
        return 250, b"ok"

    def quit(self):
        raise OSError("synthetic QUIT failure after positive DATA ACK")

    def close(self):
        pass


@pytest.fixture
def delivery_environment(environment, monkeypatch):
    config = copy.deepcopy(CONFIG)
    config["contact"]["profiles"]["default"]["delivery_policy"] = POLICY
    monkeypatch.setenv("BARE_METAL_STOREFRONT_SETTLEMENT", json.dumps(config))
    monkeypatch.setenv("BARE_METAL_STOREFRONT_DELIVERY", json.dumps(DELIVERY_CONFIG))
    return install_smtp_boundary(monkeypatch)


def install_smtp_boundary(monkeypatch):
    sent, workers = [], []
    factory = server.build_contact_delivery_worker

    async def idle():
        await asyncio.Event().wait()

    def worker(runtime, service):
        value = factory(runtime, service)
        value.run = idle
        workers.append(value)
        return value

    def send(config, address, rendered, ref, message_id, *, deadline, before_data):
        message = EmailMessage()
        message["To"] = address
        message.set_content(rendered)
        return smtp_attempt(
            config,
            address,
            message,
            deadline=deadline,
            before_data=before_data,
            smtp_factory=lambda *a, **kw: RecordingSMTP(sent, *a, **kw),
        )

    monkeypatch.setattr(server, "build_contact_delivery_worker", worker)
    monkeypatch.setattr(delivery, "send_bounded_smtp", send)
    return sent, workers


def accepted(url, runtime):
    agreed = _accept_contact(url, runtime)
    assert agreed.status == "agreed"
    ref = derive_obligation_ref(
        agreed.negotiation_id,
        0,
        agreed.settlement_plan.obligations[0].model_dump(mode="json"),
    )
    body = {
        **copy.deepcopy(REVIEW),
        "negotiation_id": agreed.negotiation_id,
        "obligation_ref": ref,
        "finalization_id": str(uuid.uuid4()),
    }
    return body


def finalize_body(body, review):
    return {
        **body,
        "review_token": review["review_token"],
        "consent": "exchange-contacts-and-deliver.v1",
    }


def counts(runtime):
    with sqlite3.connect(runtime.db.db_path) as conn:
        return tuple(
            conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("contact_introductions", "contact_delivery_intents")
        )


def test_typed_review_finalize_replay_restart_and_per_recipient_mail(
    delivery_environment, monkeypatch
):
    sent, workers = delivery_environment
    with _server(monkeypatch) as (url, runtime):
        body = accepted(url, runtime)
        buyer = _transport(url, BUYER)
        assert counts(runtime) == (0, 0)
        assert (
            buyer.delivery_read(obligation_ref=body["obligation_ref"])["status"]
            == "not_requested"
        )
        with pytest.raises(RuntimeError, match="409"):
            buyer.start(
                negotiation_id=body["negotiation_id"],
                obligation_ref=body["obligation_ref"],
                contact_payload=body["contact_payload"],
            )
        review = buyer.review(body=body)
        assert counts(runtime) == (0, 0) and sent == []
        assert "seller-route" not in json.dumps(review) and SELLER_CONTACT[
            "email"
        ] not in json.dumps(review)
        request = finalize_body(body, review)
    # Review metadata, not either raw contact or route, restores the consent fence.
    with _server(monkeypatch) as (url, runtime):
        buyer = _transport(url, BUYER)
        assert (
            buyer.finalization_read(
                obligation_ref=body["obligation_ref"],
                finalization_id=body["finalization_id"],
            )["status"]
            == "reviewed"
        )
        with ThreadPoolExecutor(2) as pool:
            responses = list(pool.map(lambda _: buyer.finalize(body=request), range(2)))
        assert responses[0] == responses[1]
        assert responses[0]["counterparty_contact"] == SELLER_CONTACT
        assert counts(runtime) == (1, 2)
        # Reconcile a lost HTTP acknowledgement by exact identity, not a new send.
        assert (
            buyer.finalization_read(
                obligation_ref=body["obligation_ref"],
                finalization_id=body["finalization_id"],
            )["status"]
            == "committed"
        )
        assert (
            buyer.read(obligation_ref=body["obligation_ref"])["counterparty_contact"]
            == SELLER_CONTACT
        )

        async def drain():
            await workers[-1].tick()
            await asyncio.gather(*workers[-1]._sends)

        asyncio.run(drain())
        assert len(sent) == 2
        delivered = {
            address: BytesParser(policy=default).parsebytes(mail).get_content()
            for address, mail in sent
        }
        assert (
            body["contact_payload"]["name😀"]
            in delivered["seller-route@example.invalid"]
        )
        assert SELLER_CONTACT["email"] in delivered[body["delivery_route"]["address"]]
        assert (
            "seller-route@example.invalid"
            not in delivered[body["delivery_route"]["address"]]
        )
        assert (
            "Buyer+Route@Example.invalid"
            not in delivered["seller-route@example.invalid"]
        )
        assert (
            buyer.delivery_read(obligation_ref=body["obligation_ref"])["status"]
            == "accepted"
        )
        with sqlite3.connect(runtime.db.db_path) as conn:
            assert (
                conn.execute(
                    "SELECT count(*) FROM contact_delivery_intents WHERE route IS NOT NULL"
                ).fetchone()[0]
                == 0
            )
    with _server(monkeypatch) as (url, runtime):
        assert (
            _transport(url, BUYER).finalization_read(
                obligation_ref=body["obligation_ref"],
                finalization_id=body["finalization_id"],
            )["status"]
            == "committed"
        )
        asyncio.run(workers[-1].tick())
        assert len(sent) == 2


def test_route_role_signature_and_privacy_refusals(delivery_environment, monkeypatch):
    with _server(monkeypatch) as (url, runtime):
        body = accepted(url, runtime)
        buyer = _transport(url, BUYER)
        review = buyer.review(body=body)
        request = finalize_body(body, review)
        for signer in (SELLER, OUTSIDER):
            with pytest.raises(RuntimeError, match="403"):
                _transport(url, signer).finalize(body=request)
        ref, fid = body["obligation_ref"], body["finalization_id"]
        other = str(uuid.uuid4())
        resource = finalization_resource(ref, fid)
        headers = _signed_headers(BUYER, "introduction_finalization_read", resource)
        response = httpx.get(
            f"{url}/api/v1/introductions/{ref}/finalizations/{other}",
            headers=headers,
            trust_env=False,
        )
        assert response.status_code in (401, 403)
        assert response.headers["cache-control"] == "no-store"
        response = httpx.get(
            f"{url}/api/v1/introductions/{ref}/delivery?role=seller",
            headers=_signed_headers(BUYER, "introduction_delivery_read", ref),
            trust_env=False,
        )
        assert response.status_code == 422
        bad = {
            **request,
            "delivery_route": {"kind": "email", "address": "PRIVATE-CANARY\r\n"},
        }
        response = httpx.post(
            f"{url}/api/v1/introductions",
            json=bad,
            headers=_signed_headers(
                BUYER, "introduction_start", ref, method="POST", body=bad
            ),
            trust_env=False,
        )
        assert response.status_code == 422 and "PRIVATE-CANARY" not in response.text
        assert counts(runtime) == (0, 0)
        cancel = dict(
            schema_version=2,
            obligation_ref=ref,
            finalization_id=fid,
            consent="fence-unresolved-finalization.v1",
        )
        assert buyer.cancel_finalization(body=cancel)["status"] == "cancelled"
        with pytest.raises(RuntimeError, match="409"):
            buyer.finalize(body=request)
        assert (
            buyer.finalization_read(obligation_ref=ref, finalization_id=fid)["status"]
            == "cancelled"
        )
        assert counts(runtime) == (0, 0)


def test_capture_survives_completion_failure_and_recovers_without_new_consent(
    delivery_environment, monkeypatch
):
    sent, workers = delivery_environment
    with _server(monkeypatch) as (url, runtime):
        body = accepted(url, runtime)
        buyer = _transport(url, BUYER)
        request = finalize_body(body, buyer.review(body=body))
        collect = runtime.settlement_runtime.collect

        async def unavailable(**kwargs):
            raise RuntimeError("synthetic completion interruption")

        monkeypatch.setattr(runtime.settlement_runtime, "collect", unavailable)
        with pytest.raises(RuntimeError, match="503"):
            buyer.finalize(body=request)
        assert counts(runtime) == (1, 2)
        assert (
            buyer.delivery_read(obligation_ref=body["obligation_ref"])["status"]
            == "awaiting_completion"
        )
        assert sent == []
        assert (
            buyer.finalization_read(
                obligation_ref=body["obligation_ref"],
                finalization_id=body["finalization_id"],
            )["status"]
            == "committed"
        )
        monkeypatch.setattr(runtime.settlement_runtime, "collect", collect)

        async def drain():
            await workers[-1].tick()
            await asyncio.gather(*workers[-1]._sends)

        asyncio.run(drain())
        assert len(sent) == 2
        assert (
            buyer.delivery_read(obligation_ref=body["obligation_ref"])["status"]
            == "accepted"
        )


def assert_awaiting_completion(runtime, sent):
    assert counts(runtime) == (1, 2)
    with sqlite3.connect(runtime.db.db_path) as conn:
        assert (
            conn.execute(
                "SELECT status,attempts,route IS NOT NULL FROM contact_delivery_intents"
            ).fetchall()
            == [("awaiting_completion", 0, 1)] * 2
        )
        assert (
            conn.execute("SELECT count(*) FROM contact_delivery_attempts").fetchone()[0]
            == 0
        )
    assert sent == []


@pytest.mark.parametrize(
    "operation,fail_first",
    [("materialize", False), ("check", False), ("collect", False), ("collect", True)],
)
def test_real_lifecycle_lease_blocks_delivery_until_success_or_restart(
    delivery_environment, monkeypatch, operation, fail_first
):
    sent, workers = delivery_environment
    entered, release = threading.Event(), threading.Event()
    calls, busy = [], []
    with _server(monkeypatch) as (url, runtime):
        body = accepted(url, runtime)
        ref = body["obligation_ref"]
        buyer = _transport(url, BUYER)
        request = finalize_body(body, buyer.review(body=body))
        client = runtime.settlement_clients[MECHANISM]
        original = getattr(client, operation)
        repository = runtime.settlement_repository
        reserve = repository.reserve_settlement_operation

        async def held_client(*args, **kwargs):
            calls.append(True)
            entered.set()
            assert await asyncio.to_thread(release.wait, 5)
            if fail_first:
                raise RuntimeError("synthetic in-flight collection interruption")
            return await original(*args, **kwargs)

        async def observe_reservation(**kwargs):
            result = await reserve(**kwargs)
            if result is None:
                busy.append(kwargs["operation"])
            return result

        # Pause the mechanism only after the real runtime owns its journal lease.
        monkeypatch.setattr(client, operation, held_client)
        monkeypatch.setattr(
            repository, "reserve_settlement_operation", observe_reservation
        )
        with ThreadPoolExecutor(1) as pool:
            first = pool.submit(buyer.finalize, body=request)
            try:
                assert entered.wait(5)
                held = asyncio.run(repository.load_settlement_operation(ref, operation))
                assert held["state"] == "in_progress" and held["attempts"] == 1
                assert held["lease_owner"] is not None
                assert_awaiting_completion(runtime, sent)
                second = buyer.finalize(body=request)
                assert second["finalization"]["status"] == "committed"
                assert calls == [True] and busy == []
                asyncio.run(workers[-1].tick())
                assert busy == [operation] and calls == [True]
                assert (
                    asyncio.run(repository.load_settlement_operation(ref, operation))
                    == held
                )
                assert_awaiting_completion(runtime, sent)
                if operation == "collect":
                    row = asyncio.run(repository.load_settlement_obligation(ref))
                    assert row["collection_state"] == "in_progress"
            finally:
                release.set()
            if fail_first:
                with pytest.raises(RuntimeError, match="503"):
                    first.result()
                assert_awaiting_completion(runtime, sent)
                failed = asyncio.run(
                    repository.load_settlement_operation(ref, operation)
                )
                assert failed["state"] == "pending"
                assert failed["uncertain_acknowledgement"]
            else:
                assert first.result() == second
                row = asyncio.run(repository.load_settlement_obligation(ref))
                assert row["collection_state"] == "succeeded"
                with sqlite3.connect(runtime.db.db_path) as conn:
                    assert (
                        conn.execute(
                            "SELECT status FROM contact_delivery_intents"
                        ).fetchall()
                        == [("pending",)] * 2
                    )
        with pytest.raises(RuntimeError, match="409"):
            buyer.finalize(body={**request, "contact_payload": {"name": "changed"}})
        with pytest.raises(RuntimeError, match="409"):
            buyer.finalize(body={**request, "finalization_id": str(uuid.uuid4())})
        object.__setattr__(runtime, "contact_delivery_config", None)
        assert buyer.finalize(body=request) == second
        assert counts(runtime) == (1, 2) and sent == []
    with _server(monkeypatch) as (url, runtime):

        async def drain():
            await workers[-1].tick()
            await asyncio.gather(*workers[-1]._sends)

        asyncio.run(drain())
        row = asyncio.run(runtime.settlement_repository.load_settlement_obligation(ref))
        assert row["collection_state"] == "succeeded"
        assert len(sent) == 2 and counts(runtime) == (1, 2)
        assert (
            _transport(url, BUYER).delivery_read(obligation_ref=ref)["status"]
            == "accepted"
        )
        asyncio.run(drain())
        assert len(sent) == 2


@pytest.mark.parametrize(
    "operation,outcome",
    [
        ("materialize", "pending"),
        ("materialize", "manual_required"),
        ("check", "pending"),
        ("check", "manual_required"),
        ("check", "failed"),
        ("collect", "manual_required"),
    ],
)
def test_real_non_success_outcomes_retain_awaiting_completion(
    delivery_environment, monkeypatch, operation, outcome
):
    sent, workers = delivery_environment
    with _server(monkeypatch) as (url, runtime):
        body = accepted(url, runtime)
        buyer = _transport(url, BUYER)
        request = finalize_body(body, buyer.review(body=body))

        async def non_success(*args, **kwargs):
            if operation == "materialize":
                return MaterializationOutcome(
                    mechanism_ref=f"introduction:{kwargs['operation_ref']}", status=outcome
                )
            if operation == "check":
                return ConditionOutcome(decision=outcome)
            raise SettlementManualRequired("synthetic operator evidence required")

        monkeypatch.setattr(
            runtime.settlement_clients[MECHANISM], operation, non_success
        )
        with pytest.raises(RuntimeError, match="503"):
            buyer.finalize(body=request)
        journal = asyncio.run(
            runtime.settlement_repository.load_settlement_operation(
                body["obligation_ref"], operation
            )
        )
        assert journal["state"] == ("succeeded" if outcome == "failed" else outcome)
        assert_awaiting_completion(runtime, sent)
        assert buyer.finalize(body=request)["finalization"]["status"] == "committed"
        asyncio.run(workers[-1].tick())
        assert_awaiting_completion(runtime, sent)
        assert (
            buyer.read(obligation_ref=body["obligation_ref"])["counterparty_contact"]
            == SELLER_CONTACT
        )
    with _server(monkeypatch) as (url, runtime):

        async def drain():
            await workers[-1].tick()
            await asyncio.gather(*workers[-1]._sends)

        asyncio.run(drain())
        if outcome in {"manual_required", "failed"}:
            # Restart is not permission to clear a durable manual/failed condition.
            assert_awaiting_completion(runtime, sent)
        else:
            assert len(sent) == 2
