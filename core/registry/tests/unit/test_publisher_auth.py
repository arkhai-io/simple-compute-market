"""Unit coverage for exact-principal publisher authorization."""

from datetime import datetime, timedelta

from market_identity import Ed25519Signer, Eip191Signer, Identity

from src.api.utils import effective_identity_status, publisher_accepts_identity
from src.db.models import Publisher, PublisherIdentity


def _publisher(principal: Identity, **binding_fields) -> Publisher:
    publisher = Publisher()
    publisher.identities.append(
        PublisherIdentity(
            scheme=principal.scheme.value,
            identifier=principal.identifier,
            status=binding_fields.pop("status", "primary"),
            **binding_fields,
        )
    )
    return publisher


def test_primary_eip191_principal_is_authorized() -> None:
    signer = Eip191Signer(bytes.fromhex("11" * 32))
    assert publisher_accepts_identity(_publisher(signer.identity), signer.identity)


def test_primary_ed25519_principal_is_authorized() -> None:
    signer = Ed25519Signer(bytes.fromhex("22" * 32))
    assert publisher_accepts_identity(_publisher(signer.identity), signer.identity)


def test_identifier_under_another_scheme_never_authorizes() -> None:
    signer = Eip191Signer(bytes.fromhex("33" * 32))
    publisher = _publisher(signer.identity)
    binding = publisher.identities[0]
    binding.scheme = "ed25519"
    binding.identifier = "MzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzM"
    assert not publisher_accepts_identity(publisher, signer.identity)


def test_overlap_expires_at_bound() -> None:
    signer = Ed25519Signer(bytes.fromhex("44" * 32))
    binding = PublisherIdentity(
        scheme=signer.identity.scheme.value,
        identifier=signer.identity.identifier,
        status="overlap",
        active_until=datetime.utcnow() - timedelta(seconds=1),
    )
    assert effective_identity_status(binding) == "retired"
    publisher = Publisher(identities=[binding])
    assert not publisher_accepts_identity(publisher, signer.identity)


def test_disabled_principal_never_authorizes() -> None:
    signer = Ed25519Signer(bytes.fromhex("55" * 32))
    publisher = _publisher(
        signer.identity,
        status="disabled",
        disabled_at=datetime.utcnow(),
    )
    assert not publisher_accepts_identity(publisher, signer.identity)
