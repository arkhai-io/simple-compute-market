"""Contact-owned transitions; callers hold a single SQLite write transaction."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import uuid
from typing import Any

from market_identity import canonical_json

from .delivery_contract import (
    DeliveryPolicy,
    EmailRoute,
    IntroductionFinalize,
    IntroductionReview,
)
from .introduction_routes import (
    IntroductionAgreement,
    IntroductionRecord,
    IntroductionRouteError,
)
from .migrations import insert_introduction, load_introduction


def fail(code: str, status: int = 409) -> IntroductionRouteError:
    return IntroductionRouteError(status, {"code": code})


def policy(agreement: IntroductionAgreement) -> dict[str, Any]:
    try:
        return DeliveryPolicy.model_validate(
            agreement.introduction_package.get("delivery_policy")
        ).model_dump(mode="json")
    except ValueError as exc:
        raise fail("delivery_policy_required") from exc


def fingerprint(salt: bytes, value: Any) -> str:
    return hmac.new(salt, canonical_json(value), hashlib.sha256).hexdigest()


def _buyer_binding(
    request: IntroductionReview, agreement: IntroductionAgreement, expires: int
) -> dict[str, Any]:
    return {
        "kind": "buyer-review.v1",
        "negotiation_id": request.negotiation_id,
        "obligation_ref": request.obligation_ref,
        "finalization_id": request.finalization_id,
        "buyer_principal": agreement.buyer_principal.model_dump(mode="json"),
        "seller_principal": agreement.seller_principal.model_dump(mode="json"),
        "delivery_policy": policy(agreement),
        "introduction": dict(agreement.introduction_package),
        "contact_payload": request.contact_payload,
        "delivery_route": request.delivery_route.model_dump(mode="json"),
        "expires_at": expires,
    }


def _seller_binding(contact: dict[str, str], route: EmailRoute) -> dict[str, Any]:
    return {
        "kind": "seller-review.v1",
        "contact_payload": contact,
        "delivery_route": route.model_dump(mode="json"),
    }


def _row(conn: sqlite3.Connection, ref: str, fid: str) -> dict[str, Any] | None:
    cursor = conn.execute(
        "SELECT * FROM contact_finalizations WHERE obligation_ref=? AND finalization_id=?",
        (ref, fid),
    )
    row = cursor.fetchone()
    return dict(zip((c[0] for c in cursor.description), row)) if row else None


def _captured(conn: sqlite3.Connection, ref: str, fid: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM contact_finalizations WHERE obligation_ref=? AND finalization_id!=? AND status='committed'",
            (ref, fid),
        ).fetchone()
        is not None
    )


def _terminal(
    conn: sqlite3.Connection, ref: str, fid: str, status: str, code: str | None = None
) -> None:
    conn.execute(
        "UPDATE contact_finalizations SET status=?, code=?, salt=NULL, buyer_fingerprint=NULL, seller_fingerprint=NULL, token_digest=NULL WHERE obligation_ref=? AND finalization_id=? AND status='reviewed'",
        (status, code, ref, fid),
    )


def outcome(conn: sqlite3.Connection, ref: str, fid: str) -> dict[str, Any]:
    row = _row(conn, ref, fid)
    result = {
        "schema_version": 2,
        "obligation_ref": ref,
        "finalization_id": fid,
        "status": row["status"] if row else "unknown",
    }
    if row and row["status"] == "rejected":
        result["code"] = row["code"]
    return result


def review(
    conn: sqlite3.Connection,
    request: IntroductionReview,
    agreement: IntroductionAgreement,
    seller_contact: dict[str, str],
    seller_route: EmailRoute,
    now: int,
) -> dict[str, Any]:
    public_policy = policy(agreement)
    if _captured(
        conn, request.obligation_ref, request.finalization_id
    ) or load_introduction(conn, request.obligation_ref):
        raise fail("finalization_conflict")
    if _row(conn, request.obligation_ref, request.finalization_id):
        raise fail("review_invalid")
    expires = min(now + 300, agreement.expiration_unix)
    if expires <= now:
        raise fail("review_expired")
    salt, token = secrets.token_bytes(32), secrets.token_urlsafe(32)
    buyer_fp = fingerprint(salt, _buyer_binding(request, agreement, expires))
    seller_fp = fingerprint(salt, _seller_binding(seller_contact, seller_route))
    conn.execute(
        "INSERT INTO contact_finalizations (obligation_ref,finalization_id,agreement_ref,status,expires_at,salt,buyer_fingerprint,seller_fingerprint,token_digest) VALUES (?,?,?,'reviewed',?,?,?,?,?)",
        (
            request.obligation_ref,
            request.finalization_id,
            agreement.agreement_ref,
            expires,
            salt,
            buyer_fp,
            seller_fp,
            hashlib.sha256(token.encode()).hexdigest(),
        ),
    )
    return {
        "schema_version": 2,
        "obligation_ref": request.obligation_ref,
        "finalization_id": request.finalization_id,
        "review_token": token,
        "expires_at": expires,
        "seller_snapshot_revision": seller_fp,
        "delivery_policy": public_policy,
        "introduction": dict(agreement.introduction_package),
    }


def finalize(
    conn: sqlite3.Connection,
    request: IntroductionFinalize,
    agreement: IntroductionAgreement,
    seller_contact: dict[str, str],
    seller_route: EmailRoute | None,
    now: int,
) -> IntroductionRecord | IntroductionRouteError:
    policy(agreement)
    ref, fid = request.obligation_ref, request.finalization_id
    row = _row(conn, ref, fid)
    if _captured(conn, ref, fid):
        return fail("finalization_conflict")
    if row is None:
        return fail("review_invalid")
    if row["status"] == "committed":
        if not hmac.compare_digest(
            row["committed_fingerprint"],
            fingerprint(row["salt"], request.model_dump(mode="json")),
        ):
            return fail("finalization_conflict")
        record = load_introduction(conn, ref)
        return (
            record
            if record is not None
            else fail("delivery_configuration_unavailable", 503)
        )
    if row["status"] != "reviewed":
        return fail(
            {"cancelled": "finalization_cancelled", "expired": "review_expired"}.get(
                row["status"], row["code"] or "review_invalid"
            )
        )
    if now >= row["expires_at"]:
        _terminal(conn, ref, fid, "expired")
        return fail("review_expired")
    if not seller_contact or seller_route is None:
        return fail("delivery_configuration_unavailable", 503)
    salt = row["salt"]
    if not hmac.compare_digest(
        row["buyer_fingerprint"],
        fingerprint(salt, _buyer_binding(request, agreement, row["expires_at"])),
    ):
        return fail("finalization_conflict")
    if not hmac.compare_digest(
        row["token_digest"], hashlib.sha256(request.review_token.encode()).hexdigest()
    ):
        _terminal(conn, ref, fid, "rejected", "review_invalid")
        return fail("review_invalid")
    if not hmac.compare_digest(
        row["seller_fingerprint"],
        fingerprint(salt, _seller_binding(seller_contact, seller_route)),
    ):
        _terminal(conn, ref, fid, "rejected", "review_changed")
        return fail("review_changed")
    record = insert_introduction(
        conn,
        IntroductionRecord(
            obligation_ref=ref,
            agreement_ref=agreement.agreement_ref,
            buyer_contact=request.contact_payload,
            seller_contact=seller_contact,
            introduction_package=dict(agreement.introduction_package),
        ),
    )
    conn.execute(
        "UPDATE contact_finalizations SET status='committed', committed_fingerprint=?, buyer_fingerprint=NULL, seller_fingerprint=NULL, token_digest=NULL WHERE obligation_ref=? AND finalization_id=?",
        (fingerprint(salt, request.model_dump(mode="json")), ref, fid),
    )
    for role, route in (("buyer", request.delivery_route), ("seller", seller_route)):
        conn.execute(
            "INSERT INTO contact_delivery_intents (intent_id,obligation_ref,recipient_role,policy_kind,status,route,attempts) VALUES (?,?,?,'contact-delivery.v1','awaiting_completion',?,0)",
            (str(uuid.uuid4()), ref, role, json.dumps(route.model_dump(mode="json"))),
        )
    return record


def cancel(
    conn: sqlite3.Connection, agreement: IntroductionAgreement, fid: str
) -> dict[str, Any]:
    policy(agreement)
    ref = agreement.obligation_ref
    if _captured(conn, ref, fid):
        raise fail("finalization_conflict")
    if _row(conn, ref, fid) is None:
        conn.execute(
            "INSERT INTO contact_finalizations (obligation_ref,finalization_id,agreement_ref,status) VALUES (?,?,?,'cancelled')",
            (ref, fid, agreement.agreement_ref),
        )
    else:
        _terminal(conn, ref, fid, "cancelled")
    return outcome(conn, ref, fid)


def recover(conn: sqlite3.Connection, now: int) -> None:
    # Recovery never discovers work from historical reveal rows.
    conn.execute(
        "UPDATE contact_finalizations SET status='rejected',code='review_invalid',salt=NULL,buyer_fingerprint=NULL,seller_fingerprint=NULL,token_digest=NULL WHERE status='reviewed' AND (salt IS NULL OR length(salt)!=32 OR buyer_fingerprint IS NULL OR seller_fingerprint IS NULL OR token_digest IS NULL OR expires_at IS NULL OR expires_at<0 OR length(buyer_fingerprint)!=64 OR length(seller_fingerprint)!=64 OR length(token_digest)!=64 OR buyer_fingerprint GLOB '*[^0-9a-f]*' OR seller_fingerprint GLOB '*[^0-9a-f]*' OR token_digest GLOB '*[^0-9a-f]*')"
    )
    conn.execute(
        "UPDATE contact_finalizations SET status='expired',salt=NULL,buyer_fingerprint=NULL,seller_fingerprint=NULL,token_digest=NULL WHERE status='reviewed' AND expires_at<=?",
        (now,),
    )
    conn.execute(
        "UPDATE contact_delivery_attempts SET status='needs_review',failure_code='attempt_abandoned',finished_at=? WHERE status='sending' AND attempt_id IN (SELECT attempt_id FROM contact_delivery_intents WHERE status='sending' AND claim_expires_at<=?)",
        (now, now),
    )
    conn.execute(
        "UPDATE contact_delivery_intents SET status='needs_review',failure_code='attempt_abandoned',route=NULL,next_attempt_at=NULL WHERE status='sending' AND claim_expires_at<=?",
        (now,),
    )


def delivery_projection(
    conn: sqlite3.Connection, ref: str, role: str
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT status,intent_id,attempts,next_attempt_at,failure_code FROM contact_delivery_intents WHERE obligation_ref=? AND recipient_role=?",
        (ref, role),
    ).fetchone()
    values = row or ("not_requested", None, 0, None, None)
    return {
        "schema_version": 1,
        "obligation_ref": ref,
        "recipient_role": role,
        **dict(
            zip(
                ("status", "intent_id", "attempts", "next_attempt_at", "failure_code"),
                values,
            )
        ),
    }
