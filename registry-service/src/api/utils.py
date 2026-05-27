"""Utility functions for API routes."""

import logging
from typing import Optional
from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from src.db.models import Agent, Listing, OrderStatusEnum

# Import for signature verification
try:
    from eth_account import Account
    from eth_account.messages import encode_defunct
    HAS_ETH_ACCOUNT = True
except ImportError:
    HAS_ETH_ACCOUNT = False

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Identity-scheme dispatch (Phase 2 of pluggable-identity refactor)
# ---------------------------------------------------------------------------
# The registry currently runs entirely on EIP-191 identities (Agent.owner is
# a wallet address recovered from a signature). Verifier calls go through
# this tiny inline dispatcher so the call-boundary already accepts a
# scheme-tagged Identity. Phase 4 consolidates onto service.identity once
# the build pipeline ships market-service into the registry image.


class Identity:
    """Scheme-tagged identity, mirroring ``service.schemas.Identity``.

    Phase 2 keeps this self-contained inside the registry to avoid taking
    a build-time dependency on the shared ``service`` package. Phase 4
    swaps this out for the imported model when the registry image
    consolidates with the rest of the workspace.
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


def _verify_eip191_signature(message: str, signature: str, expected_owner: str) -> bool:
    """Back-compat shim for callers that still pass raw owner addresses.

    New code should construct an :class:`Identity` and call
    :func:`_verify_identity_signature` directly.
    """
    return _verify_identity_signature(
        Identity(scheme="eip191", identifier=expected_owner), message, signature
    )


def verify_heartbeat_signature(
    agent_id: str,
    timestamp: int,
    signature: str,
    expected: "Identity | str",
) -> bool:
    """Verify heartbeat signature. Message format: 'heartbeat:{agent_id}:{timestamp}'

    ``expected`` may be an :class:`Identity` (preferred) or a raw owner
    address string (back-compat — coerced to ``eip191``).
    """
    if not HAS_ETH_ACCOUNT:
        logger.warning("[Heartbeat] eth_account not available, signature verification disabled")
        return False
    identity = expected if isinstance(expected, Identity) else Identity(
        scheme="eip191", identifier=expected
    )
    message = f"heartbeat:{agent_id}:{timestamp}"
    logger.info(
        f"[Heartbeat] Verifying for agent={agent_id} "
        f"scheme={identity.scheme} identifier={identity.identifier}"
    )
    is_valid = _verify_identity_signature(identity, message, signature)
    logger.info(f"[Heartbeat] Signature valid: {is_valid}")
    return is_valid


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
    resource_id: agent_id for create_listing, listing_id for update/delete

    ``expected`` may be an :class:`Identity` (preferred) or a raw owner
    address string (back-compat — coerced to ``eip191``).
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


def find_agent_by_identity(db: Session, identity: Identity) -> Optional[Agent]:
    """Look up an Agent row by scheme-tagged identity (Phase 3).

    The canonical lookup post-migration. Returns ``None`` when no row
    matches; callers handle 404 / lazy-create / JIT-index themselves.
    """
    return db.query(Agent).filter(
        Agent.scheme == identity.scheme,
        Agent.identifier == identity.identifier,
    ).first()


def ensure_agent_for_eip191(
    db: Session,
    identifier: str,
) -> Agent:
    """Find or create an Agent row for an EIP-191 identity.

    Used by the publication path for sellers identifying via ``eip191``:
    the signed request is the trust anchor — successful signature
    recovery proves the publisher controls the wallet at ``identifier``,
    so we create the row on first sighting. No on-chain lookup needed.

    Pre-condition: signature verification has already passed. Calling
    this without verifying first creates rows for arbitrary callers.

    Returns the row (existing or newly created).
    """
    identity = Identity(scheme="eip191", identifier=identifier)
    agent = find_agent_by_identity(db, identity)
    if agent is not None:
        return agent

    # The legacy `chain_id` + `registry_address` columns are NOT NULL but
    # meaningless for an eip191 agent. Pre-Phase-4 we fill them with
    # placeholders; Phase 4 drops these columns entirely.
    agent = Agent(
        scheme=identity.scheme,
        identifier=identity.identifier,
        owner=identity.identifier,
        chain_id=0,
        registry_address="",
        identity_registry=None,
        onchain_agent_id=None,
    )
    db.add(agent)
    try:
        db.commit()
        db.refresh(agent)
    except IntegrityError:
        # Concurrent insert raced us — re-query.
        db.rollback()
        return find_agent_by_identity(db, identity)  # type: ignore[return-value]

    logger.info(
        f"[Phase3] Created eip191 agent row identifier={identity.identifier}"
    )
    return agent


def find_agent_by_id(db: Session, agent_id: str) -> Optional[Agent]:
    """Find an Agent row by URL-form agent_id.

    Post-pluggable-identity (Phase 4) the registry accepts two shapes:

    * EIP-191 wallet address (``0x…``) — looked up via ``(scheme=eip191,
      identifier=address.lower())``.
    * Legacy ERC-8004 canonical (``eip155:<chain>:<registry>:<n>``) —
      looked up against the deprecated ``agents.agent_id`` column for
      back-compat with rows still tagged by migration 012.

    Returns ``None`` on miss.
    """
    if agent_id.startswith("0x") and len(agent_id) == 42:
        ident = Identity(scheme="eip191", identifier=agent_id)
        return find_agent_by_identity(db, ident)

    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    return agent


def order_to_dict(listing: Listing) -> dict:
    """Convert a Listing ORM row to its wire-shape dict."""
    return {
        "listing_id": listing.listing_id,
        "agent_id": listing.agent_id,
        "seller": listing.seller,
        "buyer": listing.buyer,
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


