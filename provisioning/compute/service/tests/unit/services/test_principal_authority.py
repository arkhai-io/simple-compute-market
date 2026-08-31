from datetime import datetime, timedelta, timezone

import pytest
from market_identity import (
    Ed25519Signer,
    RotationIntent,
    RotationRequest,
    sign_rotation,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from compute_provisioning_service.db.models import Base
from compute_provisioning_service.identity import ProvisioningIdentityContext
from compute_provisioning_service.services.principal_authority import (
    PrincipalRotationError,
    SqlAlchemyProvisioningPrincipalAuthority,
)


def _authority():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    service = Ed25519Signer(b"\x11" * 32)
    seller = Ed25519Signer(b"\x12" * 32)
    admin = Ed25519Signer(b"\x13" * 32)
    context = ProvisioningIdentityContext(
        signer=service,
        storefront_principal=seller.identity,
        admin_principal=admin.identity,
        storefront_site_id="default",
    )
    return (
        SqlAlchemyProvisioningPrincipalAuthority(factory, context),
        factory,
        context,
        seller,
        admin,
    )


def _rotation(current, replacement, *, role="seller", nonce="rotation-1", overlap=60):
    intent = RotationIntent(
        current=current.identity,
        replacement=replacement.identity,
        subject=f"provisioning:{'storefront' if role == 'seller' else 'admin'}",
        authority="provisioning",
        nonce=nonce,
        overlap_seconds=overlap,
        expires_at=2_000_000_000,
    )
    return sign_rotation(
        current_signer=current,
        replacement_signer=replacement,
        intent=intent,
    )


def test_rotation_overlap_retirement_audit_and_restart_continuity():
    authority, factory, context, seller, admin = _authority()
    replacement = Ed25519Signer(b"\x14" * 32)
    request = _rotation(seller, replacement)

    authority.rotate("seller", request, actor=admin.identity)

    active = authority.active_principals("seller")
    assert seller.identity in active
    assert replacement.identity in active
    restarted = SqlAlchemyProvisioningPrincipalAuthority(factory, context)
    assert restarted.active_principals("seller") == active
    retired = restarted.active_principals(
        "seller",
        now=datetime.now(timezone.utc) + timedelta(seconds=61),
    )
    assert replacement.identity in retired
    assert seller.identity not in retired
    with pytest.raises(PrincipalRotationError, match="nonce"):
        restarted.rotate("seller", request, actor=admin.identity)


def test_rotation_rejects_one_proof_and_role_collapse():
    authority, _, _, seller, admin = _authority()
    replacement = Ed25519Signer(b"\x14" * 32)
    valid = _rotation(seller, replacement)
    one_proof = RotationRequest(
        intent=valid.intent,
        current_proof=valid.current_proof,
        replacement_proof=valid.current_proof,
    )
    with pytest.raises(PrincipalRotationError, match="both current and replacement"):
        authority.rotate("seller", one_proof, actor=admin.identity)

    wrong_subject = _rotation(
        seller,
        replacement,
        role="admin",
        nonce="rotation-2",
    )
    with pytest.raises(PrincipalRotationError, match="subject"):
        authority.rotate("seller", wrong_subject, actor=admin.identity)
