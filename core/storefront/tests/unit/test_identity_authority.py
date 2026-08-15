from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest
from market_identity import Ed25519Signer, RotationIntent, sign_rotation

from core_storefront.identity_authority import (
    IdentityAuthorityError,
    StorefrontIdentityAuthority,
    coordinate_rotation,
)
from core_storefront.sqlite_client import SQLiteClient


def test_two_proof_rotation_bounds_overlap_and_retires_old_identity(tmp_path) -> None:
    db_path = str(tmp_path / "authority.db")
    SQLiteClient(db_path)
    authority = StorefrontIdentityAuthority(db_path, max_overlap_seconds=60)
    current = Ed25519Signer(bytes(range(32)))
    replacement = Ed25519Signer(bytes(range(1, 33)))
    authority.register_subject(
        authority="storefront.publisher",
        subject="seller-1",
        role="seller",
        principal=current.identity,
        now=1_000,
    )

    excessive = RotationIntent(
        authority="storefront.publisher",
        subject="seller-1",
        nonce="rotate-too-long",
        current=current.identity,
        replacement=replacement.identity,
        overlap_seconds=61,
        expires_at=2_000,
    )
    with pytest.raises(IdentityAuthorityError, match="overlap"):
        authority.apply_rotation(
            sign_rotation(
                current_signer=current,
                replacement_signer=replacement,
                intent=excessive,
            ),
            operator=current.identity,
            now=1_000,
        )

    intent = excessive.model_copy(
        update={"nonce": "rotate-1", "overlap_seconds": 30}
    )
    status = authority.apply_rotation(
        sign_rotation(
            current_signer=current,
            replacement_signer=replacement,
            intent=intent,
        ),
        operator=current.identity,
        now=1_000,
    )
    assert status.primary == replacement.identity
    assert status.active_principals(1_001) == {
        current.identity,
        replacement.identity,
    }
    assert status.active_principals(1_031) == {replacement.identity}
    restarted = authority.register_subject(
        authority="storefront.publisher",
        subject="seller-1",
        role="seller",
        principal=replacement.identity,
        now=1_001,
    )
    assert restarted.active_principals(1_001) == {
        current.identity,
        replacement.identity,
    }

    retired = authority.retire(
        authority="storefront.publisher",
        subject="seller-1",
        principal=current.identity,
        actor=replacement.identity,
        operation_id="retire-1",
        now=1_031,
    )
    assert retired.primary == replacement.identity
    assert retired.active_principals(1_031) == {replacement.identity}
    with pytest.raises(IdentityAuthorityError, match="primary or last"):
        authority.retire(
            authority="storefront.publisher",
            subject="seller-1",
            principal=replacement.identity,
            actor=replacement.identity,
            operation_id="retire-last",
            now=1_032,
        )



def test_service_peer_registration_remains_idempotent_during_rotation_overlap(
    tmp_path,
) -> None:
    db_path = str(tmp_path / "service-peer.db")
    SQLiteClient(db_path)
    authority = StorefrontIdentityAuthority(db_path, max_overlap_seconds=60)
    current = Ed25519Signer(b"\x21" * 32)
    replacement = Ed25519Signer(b"\x22" * 32)
    authority.register_service_peer(
        peer_id="provisioning-home",
        role="service",
        site_id="home",
        principal=current.identity,
        now=1_000,
    )
    intent = RotationIntent(
        authority="storefront.service-peer",
        subject="provisioning-home",
        nonce="service-rotate-1",
        current=current.identity,
        replacement=replacement.identity,
        overlap_seconds=30,
        expires_at=2_000,
    )
    authority.apply_rotation(
        sign_rotation(
            current_signer=current,
            replacement_signer=replacement,
            intent=intent,
        ),
        operator=current.identity,
        now=1_000,
    )

    status = authority.register_service_peer(
        peer_id="provisioning-home",
        role="service",
        site_id="home",
        principal=current.identity,
        now=1_001,
    )

    assert status.primary == replacement.identity
    assert status.active_principals(1_001) == {
        current.identity,
        replacement.identity,
    }
    after_disable = authority.disable(
        authority="storefront.service-peer",
        subject="provisioning-home",
        principal=current.identity,
        operator=replacement.identity,
        operation_id="disable-old-service-key",
        now=1_002,
    )
    assert after_disable.active_principals(1_002) == {replacement.identity}
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute(
            "SELECT status FROM service_peers WHERE peer_id=?",
            ("provisioning-home",),
        ).fetchone() == ("active",)
    finally:
        conn.close()


def test_rotation_blocks_stale_and_competing_keys_until_retirement(tmp_path) -> None:
    db_path = str(tmp_path / "serialized-rotation.db")
    SQLiteClient(db_path)
    authority = StorefrontIdentityAuthority(db_path, max_overlap_seconds=60)
    current = Ed25519Signer(b"\x31" * 32)
    replacement = Ed25519Signer(b"\x32" * 32)
    next_signer = Ed25519Signer(b"\x33" * 32)
    authority.register_subject(
        authority="storefront.administrator",
        subject="operator-a",
        role="admin",
        principal=current.identity,
        now=1_000,
    )
    first_intent = RotationIntent(
        authority="storefront.administrator",
        subject="operator-a",
        nonce="rotate-1",
        current=current.identity,
        replacement=replacement.identity,
        overlap_seconds=30,
        expires_at=2_000,
    )
    authority.apply_rotation(
        sign_rotation(
            current_signer=current,
            replacement_signer=replacement,
            intent=first_intent,
        ),
        operator=current.identity,
        now=1_000,
    )

    stale_intent = first_intent.model_copy(
        update={
            "nonce": "stale-key",
            "current": current.identity,
            "replacement": next_signer.identity,
        }
    )
    with pytest.raises(IdentityAuthorityError, match="active primary"):
        authority.apply_rotation(
            sign_rotation(
                current_signer=current,
                replacement_signer=next_signer,
                intent=stale_intent,
            ),
            operator=current.identity,
            now=1_001,
        )

    competing_intent = first_intent.model_copy(
        update={
            "nonce": "competing-primary",
            "current": replacement.identity,
            "replacement": next_signer.identity,
        }
    )
    with pytest.raises(IdentityAuthorityError, match="overlap"):
        authority.apply_rotation(
            sign_rotation(
                current_signer=replacement,
                replacement_signer=next_signer,
                intent=competing_intent,
            ),
            operator=replacement.identity,
            now=1_001,
        )

    retired = authority.complete_rotation(
        authority=first_intent.authority,
        subject=first_intent.subject,
        rotation_nonce=first_intent.nonce,
        principal=current.identity,
        operator=replacement.identity,
        now=1_002,
    )
    assert retired.active_principals(1_002) == {replacement.identity}

    rotated_again = authority.apply_rotation(
        sign_rotation(
            current_signer=replacement,
            replacement_signer=next_signer,
            intent=competing_intent,
        ),
        operator=replacement.identity,
        now=1_003,
    )
    assert rotated_again.primary == next_signer.identity
    assert len(rotated_again.active_principals(1_003)) == 2


@pytest.mark.asyncio
async def test_rotation_coordinator_carries_nonce_into_retirement() -> None:
    current = Ed25519Signer(b"\x41" * 32)
    replacement = Ed25519Signer(b"\x42" * 32)
    intent = RotationIntent(
        authority="storefront.service-peer",
        subject="service-1",
        nonce="rotation-nonce-1",
        current=current.identity,
        replacement=replacement.identity,
        overlap_seconds=30,
        expires_at=2_000,
    )
    request = sign_rotation(
        current_signer=current,
        replacement_signer=replacement,
        intent=intent,
    )

    class Client:
        def __init__(self) -> None:
            self.retirement: dict[str, object] | None = None

        async def apply_rotation(self, request):
            return SimpleNamespace(primary=request.intent.replacement)

        async def rotation_status(self, authority, subject):
            return SimpleNamespace(primary=replacement.identity)

        async def retire_identity(self, **kwargs):
            self.retirement = kwargs
            return kwargs

    client = Client()
    result = await coordinate_rotation((client,), request)

    assert result == (client.retirement,)
    assert client.retirement == {
        "authority": intent.authority,
        "subject": intent.subject,
        "rotation_nonce": intent.nonce,
        "principal": current.identity,
    }