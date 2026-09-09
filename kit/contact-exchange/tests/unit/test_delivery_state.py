"""SQLite fences and recipient recovery, with explicit deterministic clocks."""

import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from market_contact_exchange import (
    CONTACT_EXCHANGE_MIGRATIONS,
    IntroductionAgreement,
    IntroductionRouteError,
)
from market_contact_exchange import delivery_state as state
from market_contact_exchange.delivery_contract import (
    EmailRoute,
    IntroductionFinalize,
    IntroductionReview,
)
from market_contact_exchange.delivery_runtime import ContactDeliveryWorker
from market_contact_exchange.fixtures.delivery import POLICY, REVIEW
from market_identity import Ed25519Signer

# Deterministic synthetic test-only principals, never deploy live.
AGREEMENT = IntroductionAgreement(
    agreement_ref=REVIEW["negotiation_id"],
    obligation_ref=REVIEW["obligation_ref"],
    buyer_principal=Ed25519Signer(bytes([34]) * 32).identity,
    seller_principal=Ed25519Signer(bytes([17]) * 32).identity,
    introduction_package={
        "delivery_policy": POLICY,
        "profile": "synthetic",
        "channel": "email",
        "terms": "Synthetic only",
        "option_id": "b" * 64,
    },
    expiration_unix=500,
)
SELLER = {"name": "Synthetic Seller"}
ROUTE = EmailRoute(kind="email", address="seller-route@example.invalid")


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "contacts.db")
    with sqlite3.connect(path) as conn:
        for migration in CONTACT_EXCHANGE_MIGRATIONS:
            migration.apply(conn)
    return path


def tx(db, callback):
    with sqlite3.connect(db) as conn:
        conn.execute("BEGIN IMMEDIATE")
        return callback(conn)


def reviewed(db):
    request = IntroductionReview.model_validate(REVIEW)
    result = tx(db, lambda c: state.review(c, request, AGREEMENT, SELLER, ROUTE, 100))
    return IntroductionFinalize.model_validate(
        {
            **REVIEW,
            "review_token": result["review_token"],
            "consent": "exchange-contacts-and-deliver.v1",
        }
    )


def finalize(db, request, now=101, seller=SELLER):
    return tx(db, lambda c: state.finalize(c, request, AGREEMENT, seller, ROUTE, now))


def test_reviews_are_private_keyed_metadata_and_survive_restart(db):
    request = reviewed(db)
    with sqlite3.connect(db) as c:
        raw = str(c.execute("SELECT * FROM contact_finalizations").fetchall())
        for private in (
            request.review_token,
            ROUTE.address,
            SELLER["name"],
            REVIEW["contact_payload"]["name😀"],
        ):
            assert private not in raw
        assert (
            c.execute("SELECT COUNT(*) FROM contact_introductions").fetchone()[0] == 0
        )
        assert (
            c.execute("SELECT COUNT(*) FROM contact_delivery_intents").fetchone()[0]
            == 0
        )
    assert finalize(db, request).seller_contact == SELLER
    assert finalize(db, request).seller_contact == SELLER
    changed = request.model_copy(update={"contact_payload": {"name": "changed"}})
    assert finalize(db, changed).detail == {"code": "finalization_conflict"}
    with sqlite3.connect(db) as c:
        assert (
            c.execute("SELECT COUNT(*) FROM contact_delivery_intents").fetchone()[0]
            == 2
        )
        assert (
            c.execute("SELECT token_digest FROM contact_finalizations").fetchone()[0]
            is None
        )


@pytest.mark.parametrize(
    "transition,expected",
    [("expiry", "expired"), ("drift", "rejected"), ("cancel", "cancelled")],
)
def test_terminal_fences_clear_review_material(db, transition, expected):
    request = reviewed(db)
    if transition == "expiry":
        finalize(db, request, now=400)
    elif transition == "drift":
        finalize(db, request, seller={"name": "new"})
    else:
        tx(db, lambda c: state.cancel(c, AGREEMENT, request.finalization_id))
    assert isinstance(finalize(db, request), IntroductionRouteError)
    with sqlite3.connect(db) as c:
        assert (
            state.outcome(c, request.obligation_ref, request.finalization_id)["status"]
            == expected
        )
        assert c.execute(
            "SELECT salt,buyer_fingerprint,seller_fingerprint,token_digest FROM contact_finalizations"
        ).fetchone() == (None, None, None, None)
        assert (
            c.execute("SELECT COUNT(*) FROM contact_introductions").fetchone()[0] == 0
        )


def test_cancel_before_late_review_and_unknown_is_read_only(db):
    assert (
        tx(
            db,
            lambda c: state.outcome(
                c, AGREEMENT.obligation_ref, REVIEW["finalization_id"]
            ),
        )["status"]
        == "unknown"
    )
    tx(db, lambda c: state.cancel(c, AGREEMENT, REVIEW["finalization_id"]))
    with pytest.raises(IntroductionRouteError):
        reviewed(db)
    assert (
        tx(db, lambda c: state.cancel(c, AGREEMENT, REVIEW["finalization_id"]))[
            "status"
        ]
        == "cancelled"
    )


def test_concurrent_finalize_and_cancel_serialize(db):
    request = reviewed(db)
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(finalize, db, request)
        second = pool.submit(
            tx, db, lambda c: state.cancel(c, AGREEMENT, request.finalization_id)
        )
        first.result()
        second.result()
    result = tx(
        db, lambda c: state.outcome(c, request.obligation_ref, request.finalization_id)
    )
    assert result["status"] in {"committed", "cancelled"}
    again = finalize(db, request)
    assert isinstance(again, IntroductionRouteError) == (
        result["status"] == "cancelled"
    )


def test_repeated_review_never_rotates_token_and_expiry_read_does_not_sweep(db):
    reviewed(db)
    with pytest.raises(IntroductionRouteError):
        reviewed(db)
    assert (
        tx(
            db,
            lambda c: state.outcome(
                c, AGREEMENT.obligation_ref, REVIEW["finalization_id"]
            ),
        )["status"]
        == "reviewed"
    )
    tx(db, lambda c: state.recover(c, 400))
    assert (
        tx(
            db,
            lambda c: state.outcome(
                c, AGREEMENT.obligation_ref, REVIEW["finalization_id"]
            ),
        )["status"]
        == "expired"
    )


async def test_worker_unique_claim_retry_budget_cleanup_and_independent_recipients(db):
    finalize(db, reviewed(db))
    clock = [1000]
    sent = []

    async def transaction(callback):
        return tx(db, callback)

    async def prepare(*args):
        return AGREEMENT

    async def complete(agreement):
        pass

    async def send(record, role, route, intent, attempt, deadline):
        sent.append((role, route, record, intent, attempt))
        return (
            ("retry_wait", "provider_temporary")
            if role == "seller"
            else ("accepted", None)
        )

    def worker():
        return ContactDeliveryWorker(
            transaction=transaction,
            prepare=prepare,
            complete=complete,
            send=send,
            wall_clock=lambda: clock[0],
            monotonic=lambda: 0,
        )

    one, two = worker(), worker()

    async def tick():
        await asyncio.gather(one.tick(), two.tick())
        await asyncio.gather(*one._sends, *two._sends)

    await tick()
    assert len(sent) == 2
    with sqlite3.connect(db) as c:
        buyer = state.delivery_projection(c, AGREEMENT.obligation_ref, "buyer")
        seller = state.delivery_projection(c, AGREEMENT.obligation_ref, "seller")
        assert buyer["status"] == "accepted"
        assert seller["next_attempt_at"] == 1060
        assert (
            c.execute(
                "SELECT route FROM contact_delivery_intents WHERE recipient_role='buyer'"
            ).fetchone()[0]
            is None
        )
    clock[0] = 1060
    await tick()
    clock[0] = 1360
    await tick()
    await tick()
    assert [s[0] for s in sent].count("seller") == 3
    assert [s[0] for s in sent].count("buyer") == 1
    with sqlite3.connect(db) as c:
        assert (
            state.delivery_projection(c, AGREEMENT.obligation_ref, "seller")["status"]
            == "failed"
        )
        assert (
            c.execute(
                "SELECT count(*) FROM contact_delivery_intents WHERE route IS NOT NULL"
            ).fetchone()[0]
            == 0
        )


async def test_abandoned_claim_and_lost_ack_never_resend(db):
    finalize(db, reviewed(db))

    async def transaction(callback):
        return tx(db, callback)

    async def unused(*args):
        raise AssertionError("unexpected effect")

    worker = ContactDeliveryWorker(
        transaction=transaction,
        prepare=unused,
        complete=unused,
        send=unused,
        wall_clock=lambda: 1000,
    )
    tx(db, lambda c: c.execute("UPDATE contact_delivery_intents SET status='pending'"))
    claim = tx(db, worker._claim)
    tx(db, lambda c: state.recover(c, 1149))
    assert (
        tx(
            db,
            lambda c: state.delivery_projection(
                c, AGREEMENT.obligation_ref, claim["recipient_role"]
            ),
        )["status"]
        == "sending"
    )
    tx(db, lambda c: state.recover(c, 1150))
    assert (
        tx(
            db,
            lambda c: state.delivery_projection(
                c, AGREEMENT.obligation_ref, claim["recipient_role"]
            ),
        )["status"]
        == "needs_review"
    )
    assert (
        tx(
            db,
            lambda c: c.execute(
                "SELECT route FROM contact_delivery_intents WHERE intent_id=?",
                (claim["intent_id"],),
            ).fetchone(),
        )[0]
        is None
    )


async def test_lost_data_ack_is_terminal_across_worker_restart(db):
    finalize(db, reviewed(db))
    calls = []

    async def transaction(callback):
        return tx(db, callback)

    async def prepare(*args):
        return AGREEMENT

    async def complete(*args):
        pass

    async def send(*args):
        calls.append(args)
        return "needs_review", "acceptance_unknown"

    def worker():
        return ContactDeliveryWorker(
            transaction=transaction, prepare=prepare, complete=complete, send=send
        )

    one = worker()
    await one.tick()
    await asyncio.gather(*one._sends)
    await worker().tick()
    assert len(calls) == 2
    with sqlite3.connect(db) as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM contact_delivery_intents WHERE status='needs_review' AND attempts=1 AND route IS NULL"
            ).fetchone()[0]
            == 2
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM contact_delivery_attempts WHERE status='needs_review' AND failure_code='acceptance_unknown'"
            ).fetchone()[0]
            == 2
        )


def test_corrupt_review_binding_is_fenced_at_recovery(db):
    request = reviewed(db)
    tx(db, lambda c: c.execute("UPDATE contact_finalizations SET salt=NULL"))
    tx(db, lambda c: state.recover(c, 101))
    assert tx(
        db, lambda c: state.outcome(c, request.obligation_ref, request.finalization_id)
    ) == {
        "schema_version": 2,
        "obligation_ref": request.obligation_ref,
        "finalization_id": request.finalization_id,
        "status": "rejected",
        "code": "review_invalid",
    }
    assert isinstance(finalize(db, request), IntroductionRouteError)
