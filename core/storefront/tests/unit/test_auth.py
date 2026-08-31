from __future__ import annotations

import pytest
from market_identity import (
    REQUEST_PROTOCOL,
    Ed25519Signer,
    Identity,
    ReplayReservation,
    RequestEnvelope,
    canonical_body_hash,
    sign_request,
)

from core_storefront.auth import (
    IDENTITY_IDENTIFIER_HEADER,
    IDENTITY_SCHEME_HEADER,
    REQUEST_ID_HEADER,
    ROLE_HEADER,
    SIGNATURE_HEADER,
    SIGNATURE_VERSION_HEADER,
    TIMESTAMP_HEADER,
    AuthError,
    ReplayClaim,
    authenticate_request,
)


class ReplayStore:
    def __init__(self) -> None:
        self.rows: dict[
            tuple[object, str],
            tuple[ReplayReservation, str, int, tuple[int, object] | None],
        ] = {}
        self.next_token = 0

    async def get_replay_reservation(self, principal, request_id):
        row = self.rows.get((principal, request_id))
        return row[0] if row is not None else None

    async def claim_replay(self, reservation, *, now, lease_seconds):
        key = (reservation.identity.principal, reservation.identity.request_id)
        row = self.rows.get(key)
        if row is not None and row[0].request_hash != reservation.request_hash:
            return ReplayClaim(state="changed", reservation=reservation)
        if row is not None and row[3] is not None:
            return ReplayClaim(
                state="completed",
                reservation=reservation,
                recorded_outcome=row[3],
            )
        if row is not None and row[2] > now:
            return ReplayClaim(state="pending", reservation=reservation)
        self.next_token += 1
        token = f"attempt-{self.next_token}"
        self.rows[key] = (reservation, token, now + lease_seconds, None)
        return ReplayClaim(
            state="dispatch",
            reservation=reservation,
            attempt_token=token,
        )

    async def record_replay_outcome(
        self,
        reservation,
        *,
        attempt_token,
        status,
        body,
    ):
        key = (reservation.identity.principal, reservation.identity.request_id)
        row = self.rows[key]
        if row[1] != attempt_token:
            raise RuntimeError("superseded")
        self.rows[key] = (row[0], row[1], row[2], (status, body))


def _signed_headers(
    *,
    signer,
    body,
    role="buyer",
    request_id="request-1",
    timestamp=1_000,
):
    authenticated = sign_request(
        signer=signer,
        envelope=RequestEnvelope(
            role=role,
            principal=signer.identity,
            method="POST",
            operation="negotiate",
            resource="listing-1",
            request_id=request_id,
            timestamp=timestamp,
            body_hash=canonical_body_hash(body),
        ),
    )
    return {
        SIGNATURE_VERSION_HEADER: REQUEST_PROTOCOL,
        IDENTITY_SCHEME_HEADER: authenticated.principal.scheme.value,
        IDENTITY_IDENTIFIER_HEADER: authenticated.principal.identifier,
        ROLE_HEADER: authenticated.role,
        REQUEST_ID_HEADER: authenticated.request_id,
        TIMESTAMP_HEADER: str(authenticated.timestamp),
        SIGNATURE_HEADER: authenticated.proof.value,
    }


@pytest.mark.asyncio
async def test_ed25519_v2_request_reserves_replay_before_dispatch() -> None:
    signer = Ed25519Signer(bytes(range(32)))
    store = ReplayStore()
    body = {"buyer_principal": signer.identity.model_dump(mode="json")}
    headers = _signed_headers(signer=signer, body=body)

    first = await authenticate_request(
        headers=headers,
        method="POST",
        operation="negotiate",
        resource="listing-1",
        body=body,
        expected_role="buyer",
        expected_principal=signer.identity,
        replay_store=store,
        now=1_000,
    )
    retry = await authenticate_request(
        headers=headers,
        method="POST",
        operation="negotiate",
        resource="listing-1",
        body=body,
        expected_role="buyer",
        expected_principal=signer.identity,
        replay_store=store,
        now=1_000,
    )

    assert first.dispatch_allowed is True
    assert retry.exact_retry is True
    assert retry.dispatch_allowed is False


@pytest.mark.asyncio
async def test_v2_rejects_body_mutation_and_cross_role_reuse() -> None:
    signer = Ed25519Signer(bytes(range(32)))
    store = ReplayStore()
    body = {"buyer_principal": signer.identity.model_dump(mode="json")}
    headers = _signed_headers(signer=signer, body=body)

    with pytest.raises(AuthError):
        await authenticate_request(
            headers=headers,
            method="POST",
            operation="negotiate",
            resource="listing-1",
            body={**body, "amount": 2},
            expected_role="buyer",
            expected_principal=signer.identity,
            replay_store=store,
            now=1_000,
        )
    with pytest.raises(AuthError):
        await authenticate_request(
            headers=headers,
            method="POST",
            operation="negotiate",
            resource="listing-1",
            body=body,
            expected_role="seller",
            expected_principal=signer.identity,
            replay_store=store,
            now=1_000,
        )


@pytest.mark.asyncio
async def test_v2_rejects_legacy_headers_and_cross_scheme_authority() -> None:
    signer = Ed25519Signer(bytes(range(32)))
    store = ReplayStore()
    body = {"buyer_principal": signer.identity.model_dump(mode="json")}
    with pytest.raises(AuthError, match="X-Market-Signature-Version"):
        await authenticate_request(
            headers={"X-Signature": "legacy", "X-Timestamp": "1000"},
            method="POST",
            operation="negotiate",
            resource="listing-1",
            body=body,
            expected_role="buyer",
            expected_principal=signer.identity,
            replay_store=store,
            now=1_000,
        )

    headers = _signed_headers(signer=signer, body=body)
    eip191_authority = Identity(
        scheme="eip191",
        identifier="0x1111111111111111111111111111111111111111",
    )
    with pytest.raises(AuthError, match="principal"):
        await authenticate_request(
            headers=headers,
            method="POST",
            operation="negotiate",
            resource="listing-1",
            body=body,
            expected_role="buyer",
            expected_principal=eip191_authority,
            replay_store=store,
            now=1_000,
        )


@pytest.mark.asyncio
async def test_completed_exact_retry_survives_original_timestamp_age() -> None:
    signer = Ed25519Signer(bytes(range(32)))
    store = ReplayStore()
    body = {"buyer_principal": signer.identity.model_dump(mode="json")}
    headers = _signed_headers(signer=signer, body=body)
    first = await authenticate_request(
        headers=headers,
        method="POST",
        operation="negotiate",
        resource="listing-1",
        body=body,
        expected_role="buyer",
        expected_principal=signer.identity,
        replay_store=store,
        now=1_000,
    )
    assert first.attempt_token is not None
    await store.record_replay_outcome(
        first.reservation,
        attempt_token=first.attempt_token,
        status=201,
        body={"ok": True},
    )

    retry = await authenticate_request(
        headers=_signed_headers(signer=signer, body=body, timestamp=10_000),
        method="POST",
        operation="negotiate",
        resource="listing-1",
        body=body,
        expected_role="buyer",
        expected_principal=signer.identity,
        replay_store=store,
        now=10_000,
    )

    assert retry.exact_retry is True
    assert retry.recorded_outcome == (201, {"ok": True})

    with pytest.raises(AuthError, match="timestamp"):
        await authenticate_request(
            headers=headers,
            method="POST",
            operation="negotiate",
            resource="listing-1",
            body=body,
            expected_role="buyer",
            expected_principal=signer.identity,
            replay_store=store,
            now=10_000,
        )


@pytest.mark.asyncio
async def test_stale_unseen_request_is_rejected_without_reservation() -> None:
    signer = Ed25519Signer(bytes(range(32)))
    store = ReplayStore()
    body = {"buyer_principal": signer.identity.model_dump(mode="json")}

    with pytest.raises(AuthError, match="timestamp"):
        await authenticate_request(
            headers=_signed_headers(signer=signer, body=body),
            method="POST",
            operation="negotiate",
            resource="listing-1",
            body=body,
            expected_role="buyer",
            expected_principal=signer.identity,
            replay_store=store,
            now=1_301,
        )

    assert store.rows == {}


@pytest.mark.asyncio
async def test_stale_pending_attempt_is_atomically_reclaimed() -> None:
    signer = Ed25519Signer(bytes(range(32)))
    store = ReplayStore()
    body = {"buyer_principal": signer.identity.model_dump(mode="json")}
    headers = _signed_headers(signer=signer, body=body)
    first = await authenticate_request(
        headers=headers,
        method="POST",
        operation="negotiate",
        resource="listing-1",
        body=body,
        expected_role="buyer",
        expected_principal=signer.identity,
        replay_store=store,
        now=1_000,
        replay_lease_seconds=10,
    )
    reclaimed = await authenticate_request(
        headers=headers,
        method="POST",
        operation="negotiate",
        resource="listing-1",
        body=body,
        expected_role="buyer",
        expected_principal=signer.identity,
        replay_store=store,
        now=1_011,
        replay_lease_seconds=10,
    )

    assert reclaimed.dispatch_allowed is True
    assert reclaimed.attempt_token != first.attempt_token


@pytest.mark.asyncio
async def test_changed_request_id_reuse_is_rejected_after_valid_signature() -> None:
    signer = Ed25519Signer(bytes(range(32)))
    store = ReplayStore()
    body = {"buyer_principal": signer.identity.model_dump(mode="json")}
    await authenticate_request(
        headers=_signed_headers(signer=signer, body=body),
        method="POST",
        operation="negotiate",
        resource="listing-1",
        body=body,
        expected_role="buyer",
        expected_principal=signer.identity,
        replay_store=store,
        now=1_000,
    )
    changed = {**body, "amount": 2}

    with pytest.raises(AuthError, match="changed signed content"):
        await authenticate_request(
            headers=_signed_headers(signer=signer, body=changed),
            method="POST",
            operation="negotiate",
            resource="listing-1",
            body=changed,
            expected_role="buyer",
            expected_principal=signer.identity,
            replay_store=store,
            now=1_000,
        )
