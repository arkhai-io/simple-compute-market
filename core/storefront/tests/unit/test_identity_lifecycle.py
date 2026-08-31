from __future__ import annotations

import pytest
from market_identity import Ed25519Signer, RotationIntent, sign_rotation

from core_storefront.identity_authority import (
    ADMINISTRATOR_AUTHORITY,
    SERVICE_PEER_AUTHORITY,
    IdentityAuthorityError,
    StorefrontIdentityAuthority,
)
from core_storefront.identity_lifecycle import (
    inspect_identity,
    retire_rotated_identity,
    rotate_identity,
)
from core_storefront.models.system_models import IdentityRetirementRequest
from core_storefront.sqlite_client import SQLiteClient


def test_administrator_can_rotate_and_retire_service_peer_identity(tmp_path) -> None:
    db_path = str(tmp_path / "lifecycle.db")
    SQLiteClient(db_path)
    authority = StorefrontIdentityAuthority(db_path, max_overlap_seconds=60)
    administrator = Ed25519Signer(bytes(range(32)))
    current = Ed25519Signer(bytes(range(1, 33)))
    replacement = Ed25519Signer(bytes(range(2, 34)))
    authority.register_subject(
        authority=ADMINISTRATOR_AUTHORITY,
        subject="operator",
        role="admin",
        principal=administrator.identity,
        now=1_000,
    )
    authority.register_service_peer(
        peer_id="provisioning/home",
        role="service",
        site_id="home",
        principal=current.identity,
        now=1_000,
    )
    intent = RotationIntent(
        authority=SERVICE_PEER_AUTHORITY,
        subject="provisioning/home",
        nonce="rotate-service-1",
        current=current.identity,
        replacement=replacement.identity,
        overlap_seconds=30,
        expires_at=2_000,
    )

    overlap = rotate_identity(
        authority,
        request=sign_rotation(
            current_signer=current,
            replacement_signer=replacement,
            intent=intent,
        ),
        operator=administrator.identity,
        now=1_001,
    )

    assert overlap.primary == replacement.identity
    assert {binding.principal for binding in overlap.bindings if binding.active} == {
        replacement.identity,
        current.identity,
    }
    retired = retire_rotated_identity(
        authority,
        request=IdentityRetirementRequest(
            authority=SERVICE_PEER_AUTHORITY,
            subject="provisioning/home",
            rotation_nonce="rotate-service-1",
            principal=current.identity,
        ),
        operator=administrator.identity,
        now=1_002,
    )
    assert retired.primary == replacement.identity
    assert {
        binding.principal for binding in retired.bindings if binding.active
    } == {replacement.identity}
    assert any(
        binding.principal == current.identity
        and binding.status == "retired"
        and not binding.active
        for binding in retired.bindings
    )


def test_retirement_requires_the_matching_rotation_nonce(tmp_path) -> None:
    db_path = str(tmp_path / "retirement-nonce.db")
    SQLiteClient(db_path)
    authority = StorefrontIdentityAuthority(db_path)
    current = Ed25519Signer(b"\x31" * 32)
    replacement = Ed25519Signer(b"\x32" * 32)
    operator = Ed25519Signer(b"\x33" * 32)
    authority.register_service_peer(
        peer_id="service-1",
        role="service",
        site_id="site-1",
        principal=current.identity,
        now=1_000,
    )
    intent = RotationIntent(
        authority=SERVICE_PEER_AUTHORITY,
        subject="service-1",
        nonce="right-nonce",
        current=current.identity,
        replacement=replacement.identity,
        overlap_seconds=10,
        expires_at=2_000,
    )
    rotate_identity(
        authority,
        request=sign_rotation(
            current_signer=current,
            replacement_signer=replacement,
            intent=intent,
        ),
        operator=operator.identity,
        now=1_001,
    )

    with pytest.raises(IdentityAuthorityError, match="nonce"):
        retire_rotated_identity(
            authority,
            request=IdentityRetirementRequest(
                authority=SERVICE_PEER_AUTHORITY,
                subject="service-1",
                rotation_nonce="wrong-nonce",
                principal=current.identity,
            ),
            operator=operator.identity,
            now=1_002,
        )

    status = inspect_identity(
        authority,
        authority=SERVICE_PEER_AUTHORITY,
        subject="service-1",
        now=1_002,
    )
    assert {binding.principal for binding in status.bindings if binding.active} == {
        replacement.identity,
        current.identity,
    }
