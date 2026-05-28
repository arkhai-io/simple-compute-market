"""Utility functions for API routes."""

import logging
from typing import Optional
from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from src.db.models import Publisher, PublisherIdentity, Listing, OrderStatusEnum

# Import for signature verification
try:
    from eth_account import Account
    from eth_account.messages import encode_defunct
    HAS_ETH_ACCOUNT = True
except ImportError:
    HAS_ETH_ACCOUNT = False

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Identity-scheme dispatch
# ---------------------------------------------------------------------------
# The registry runs on EIP-191 identities: a request is authenticated by
# recovering the signer's wallet address from an EIP-191 signature. Verifier
# calls go through this dispatcher so the call boundary accepts a
# scheme-tagged Identity; adding a scheme is one dict entry.


class Identity:
    """Scheme-tagged identity, mirroring ``service.schemas.Identity``.

    Kept self-contained inside the registry to avoid a build-time dependency
    on the shared ``service`` package.
    """

    __slots__ = ("scheme", "identifier")

    def __init__(self, scheme: str, identifier: str) -> None:
        self.scheme = scheme
        # Normalize EIP-191 identifiers to lowercase for byte-wise comparability.
        self.identifier = identifier.lower() if scheme == "eip191" else identifier


def _verify_eip191(identity: Identity, message: bytes, proof: bytes) -> bool:
    if not HAS_ETH_ACCOUNT:
        return False
    try:
        text = message.decode("utf-8")
    except UnicodeDecodeError:
        return False
    try:
        envelope = encode_defunct(text=text)
        recovered = Account.recover_message(envelope, signature=proof)
        return recovered.lower() == identity.identifier.lower()
    except Exception as exc:  # noqa: BLE001 — eth_account raises many shapes
        logger.error(f"[VERIFY] EIP-191 recovery failed: {exc}")
        return False


# Scheme name → verifier callable. Adding a scheme is a single dict entry.
_VERIFIERS: dict[str, "callable[[Identity, bytes, bytes], bool]"] = {
    "eip191": _verify_eip191,
}


def _verify_identity_signature(identity: Identity, message: str, signature: str) -> bool:
    """Dispatch signature verification by identity scheme."""
    verifier = _VERIFIERS.get(identity.scheme)
    if verifier is None:
        logger.warning(f"[VERIFY] unknown identity scheme {identity.scheme!r}")
        return False
    try:
        proof = bytes.fromhex(signature.removeprefix("0x"))
    except ValueError:
        logger.error("[VERIFY] malformed signature hex")
        return False
    return verifier(identity, message.encode("utf-8"), proof)


def verify_order_signature(
    operation: str,
    resource_id: str,
    timestamp: int,
    signature: str,
    expected: "Identity | str",
) -> bool:
    """Verify a listing mutation signature.

    Message format: '{operation}:{resource_id}:{timestamp}'
    operation: 'create_listing', 'update_listing', or 'delete_listing'
    resource_id: the signing identifier for create_listing, listing_id for
    update/delete.

    ``expected`` may be an :class:`Identity` (preferred) or a raw EIP-191
    address string (coerced to ``eip191``).
    """
    if not HAS_ETH_ACCOUNT:
        logger.warning("[Order] eth_account not available, signature verification disabled")
        return False
    identity = expected if isinstance(expected, Identity) else Identity(
        scheme="eip191", identifier=expected
    )
    message = f"{operation}:{resource_id}:{timestamp}"
    logger.info(
        f"[Order] Verifying {operation} for resource={resource_id} "
        f"scheme={identity.scheme} identifier={identity.identifier}"
    )
    is_valid = _verify_identity_signature(identity, message, signature)
    logger.info(f"[Order] Signature valid: {is_valid}")
    return is_valid


# ---------------------------------------------------------------------------
# Publisher / identity lookup
# ---------------------------------------------------------------------------


def find_publisher_by_identity(db: Session, identity: Identity) -> Optional[Publisher]:
    """Resolve a publisher by one of its signing identities.

    Returns ``None`` when no identity matches; callers handle 404 /
    lazy-create themselves.
    """
    row = (
        db.query(PublisherIdentity)
        .filter(
            PublisherIdentity.scheme == identity.scheme,
            PublisherIdentity.identifier == identity.identifier,
        )
        .first()
    )
    return row.publisher if row is not None else None


def find_publisher_by_id(db: Session, publisher_id: int) -> Optional[Publisher]:
    """Look up a publisher by its surrogate id."""
    return db.query(Publisher).filter(Publisher.publisher_id == publisher_id).first()


def ensure_publisher_for_identity(
    db: Session,
    identity: Identity,
    storefront_url: Optional[str] = None,
) -> Publisher:
    """Find or create the publisher owning ``identity``.

    Used by the publish path: the signed request is the trust anchor —
    successful signature recovery proves control of the identity, so the
    publisher (and its identity row) is created on first sighting. No
    pre-registration. When ``storefront_url`` is supplied it is recorded on
    create and refreshed on later publishes if it changed.

    Pre-condition: signature verification has already passed.
    """
    publisher = find_publisher_by_identity(db, identity)
    if publisher is not None:
        if storefront_url and publisher.storefront_url != storefront_url:
            publisher.storefront_url = storefront_url
            db.commit()
            db.refresh(publisher)
        return publisher

    publisher = Publisher(storefront_url=storefront_url)
    publisher.identities.append(
        PublisherIdentity(scheme=identity.scheme, identifier=identity.identifier)
    )
    db.add(publisher)
    try:
        db.commit()
        db.refresh(publisher)
    except IntegrityError:
        # Concurrent insert raced us on the unique (scheme, identifier) — re-query.
        db.rollback()
        return find_publisher_by_identity(db, identity)  # type: ignore[return-value]

    logger.info(
        f"[Publisher] Created publisher id={publisher.publisher_id} "
        f"identity={identity.scheme}:{identity.identifier}"
    )
    return publisher


def publisher_to_dict(publisher: Publisher) -> dict:
    """Wire shape for a publisher entity."""
    return {
        "publisher_id": publisher.publisher_id,
        "storefront_url": publisher.storefront_url,
        "identities": [
            {"scheme": i.scheme, "identifier": i.identifier}
            for i in publisher.identities
        ],
        "created_at": publisher.created_at.isoformat(),
    }


def order_to_dict(listing: Listing) -> dict:
    """Convert a Listing ORM row to its wire-shape dict.

    ``storefront_url`` (where a buyer negotiates) is joined from the
    owning publisher — the same value and key the publisher entity uses.
    """
    publisher = listing.publisher
    return {
        "listing_id": listing.listing_id,
        "publisher_id": listing.publisher_id,
        "storefront_url": publisher.storefront_url if publisher else None,
        "offer_resource": listing.offer_resource or {},
        "accepted_escrows": listing.accepted_escrows or [],
        "max_duration_seconds": listing.max_duration_seconds,
        "oracle_address": listing.oracle_address,
        "status": listing.status.value,
        "created_at": listing.created_at.isoformat(),
        "updated_at": listing.updated_at.isoformat(),
    }


def validate_order_status(status: str) -> OrderStatusEnum:
    """Validate and convert string status to OrderStatusEnum"""
    try:
        return OrderStatusEnum(status)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
