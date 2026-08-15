"""Utility functions for registry API routes."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Optional

from fastapi import HTTPException
from market_identity import Identity, TrustedIdentitySet
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.db.models import Listing, OrderStatusEnum, Publisher, PublisherIdentity

logger = logging.getLogger(__name__)


def find_identity_binding(
    db: Session,
    identity: Identity,
) -> Optional[PublisherIdentity]:
    """Resolve an exact canonical principal to its retained binding row."""

    return (
        db.query(PublisherIdentity)
        .filter(
            PublisherIdentity.scheme == identity.scheme.value,
            PublisherIdentity.identifier == identity.identifier,
        )
        .first()
    )


def effective_identity_status(
    binding: PublisherIdentity,
    *,
    now: datetime | None = None,
) -> str:
    """Return lifecycle status after applying the bounded-overlap deadline."""

    if binding.disabled_at is not None or binding.status == "disabled":
        return "disabled"
    if binding.retired_at is not None or binding.status == "retired":
        return "retired"
    deadline = binding.active_until
    instant = now or (
        datetime.now(deadline.tzinfo)
        if deadline is not None and deadline.tzinfo is not None
        else datetime.utcnow()
    )
    if binding.status == "overlap" and deadline is not None and deadline <= instant:
        return "retired"
    return binding.status


def identity_is_active(
    binding: PublisherIdentity,
    *,
    now: datetime | None = None,
) -> bool:
    return effective_identity_status(binding, now=now) in {"primary", "overlap"}


def find_publisher_by_identity(
    db: Session,
    identity: Identity,
    *,
    active_only: bool = False,
) -> Optional[Publisher]:
    """Resolve an exact principal, optionally requiring an active binding."""

    binding = find_identity_binding(db, identity)
    if binding is None or (active_only and not identity_is_active(binding)):
        return None
    return binding.publisher


def find_publisher_by_id(db: Session, publisher_id: int) -> Optional[Publisher]:
    return (
        db.query(Publisher)
        .filter(Publisher.publisher_id == publisher_id)
        .first()
    )


def publisher_accepts_identity(
    publisher: Publisher,
    identity: Identity,
    *,
    primary_only: bool = False,
) -> bool:
    """Authorize one complete principal against a publisher's active bindings."""

    for binding in publisher.identities:
        if (
            binding.scheme == identity.scheme.value
            and binding.identifier == identity.identifier
            and identity_is_active(binding)
        ):
            return not primary_only or binding.status == "primary"
    return False


def primary_identity(publisher: Publisher) -> Identity | None:
    """Return the publisher's single active primary principal."""

    for binding in publisher.identities:
        if binding.status == "primary" and identity_is_active(binding):
            return Identity(
                scheme=binding.scheme,
                identifier=binding.identifier,
            )
    return None

def active_identities(publisher: Publisher) -> TrustedIdentitySet:
    bindings = sorted(
        (
            binding
            for binding in publisher.identities
            if identity_is_active(binding)
        ),
        key=lambda binding: (binding.status != "primary", binding.created_at),
    )
    return TrustedIdentitySet(
        identities=tuple(
            Identity(scheme=binding.scheme, identifier=binding.identifier)
            for binding in bindings
        )
    )


def ensure_publisher_for_identity(
    db: Session,
    identity: Identity,
    storefront_url: Optional[str] = None,
) -> Publisher:
    """Lazily bind a newly verified principal to one stable publisher."""

    binding = find_identity_binding(db, identity)
    if binding is not None:
        if not identity_is_active(binding):
            raise HTTPException(
                status_code=403,
                detail="Publisher principal is retired or disabled",
            )
        publisher = binding.publisher
        if storefront_url and publisher.storefront_url != storefront_url:
            publisher.storefront_url = storefront_url
        return publisher

    publisher = Publisher(storefront_url=storefront_url)
    publisher.identities.append(
        PublisherIdentity(
            scheme=identity.scheme.value,
            identifier=identity.identifier,
            status="primary",
        )
    )
    db.add(publisher)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        binding = find_identity_binding(db, identity)
        if binding is None or not identity_is_active(binding):
            raise HTTPException(
                status_code=409,
                detail="Publisher principal binding conflict",
            )
        return binding.publisher

    logger.info(
        "[Publisher] Created publisher id=%s principal=%s:%s",
        publisher.publisher_id,
        identity.scheme.value,
        identity.identifier,
    )
    return publisher


def publisher_to_dict(publisher: Publisher) -> dict[str, Any]:
    """Return a stable publisher with explicit principal lifecycle bindings."""

    identities = []
    for binding in publisher.identities:
        status = effective_identity_status(binding)
        identities.append(
            {
                "principal": {
                    "scheme": binding.scheme,
                    "identifier": binding.identifier,
                },
                "status": status,
                "active_until": (
                    binding.active_until.isoformat()
                    if binding.active_until is not None
                    else None
                ),
                "retired_at": (
                    binding.retired_at.isoformat()
                    if binding.retired_at is not None
                    else None
                ),
                "disabled_at": (
                    binding.disabled_at.isoformat()
                    if binding.disabled_at is not None
                    else None
                ),
            }
        )
    return {
        "publisher_id": publisher.publisher_id,
        "storefront_url": publisher.storefront_url,
        "identities": identities,
        "created_at": publisher.created_at.isoformat(),
    }


def _as_json_obj(value: Any, default: Any) -> Any:
    """Decode a JSON column that may contain one already-encoded value."""

    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return default
    return default if value is None else value


def order_to_dict(listing: Listing) -> dict[str, Any]:
    """Convert a listing row to its principal-aware discovery wire shape."""

    publisher = listing.publisher
    owners = active_identities(publisher) if publisher is not None else None
    return {
        "listing_id": listing.listing_id,
        "publisher_id": listing.publisher_id,
        "publisher_principals": (
            owners.model_dump(mode="json") if owners is not None else None
        ),
        "storefront_url": publisher.storefront_url if publisher else None,
        "offer_resource": _as_json_obj(listing.offer_resource, {}),
        "accepted_escrows": _as_json_obj(listing.accepted_escrows, []),
        "settlement_options": _as_json_obj(listing.settlement_options, []),
        "demands": _as_json_obj(listing.demands, []),
        "max_duration_seconds": listing.max_duration_seconds,
        "oracle_address": listing.oracle_address,
        "status": listing.status.value,
        "created_at": listing.created_at.isoformat(),
        "updated_at": listing.updated_at.isoformat(),
    }


def validate_order_status(status: str) -> OrderStatusEnum:
    """Validate and convert a listing lifecycle status."""

    try:
        return OrderStatusEnum(status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid status: {status}") from exc
