"""Typed dataclasses for Registry API requests and responses.

These are intentionally permissive — fields that the API may omit are
Optional so that responses from different environments (local, staging,
production) don't cause parse failures when non-critical fields are absent.

All models use dataclasses + a lightweight ``from_dict`` factory rather than
a heavy validation library, keeping the package dependency-light.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Shared / primitive models
# ---------------------------------------------------------------------------


@dataclass
class ValidationErrorDetail:
    loc: list[str | int]
    msg: str
    type: str

    @classmethod
    def from_dict(cls, d: dict) -> "ValidationErrorDetail":
        return cls(loc=d["loc"], msg=d["msg"], type=d["type"])


@dataclass
class HTTPValidationError:
    detail: list[ValidationErrorDetail]

    @classmethod
    def from_dict(cls, d: dict) -> "HTTPValidationError":
        return cls(detail=[ValidationErrorDetail.from_dict(e) for e in d.get("detail", [])])


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@dataclass
class HealthResponse:
    """Response body from GET /health."""

    status: str | None = None
    health_checks_enabled: bool | None = None
    # Preserve any extra fields the service may return
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "HealthResponse":
        known = {"status", "health_checks_enabled"}
        return cls(
            status=d.get("status"),
            health_checks_enabled=d.get("health_checks_enabled"),
            extra={k: v for k, v in d.items() if k not in known},
        )


# ---------------------------------------------------------------------------
# Publishers
# ---------------------------------------------------------------------------


@dataclass
class PublisherIdentity:
    """A publisher's signing identity — a ``(scheme, identifier)`` pair."""

    scheme: str
    identifier: str

    @classmethod
    def from_dict(cls, d: dict) -> "PublisherIdentity":
        return cls(scheme=d.get("scheme", ""), identifier=d.get("identifier", ""))


@dataclass
class Publisher:
    """A listing-owning principal, returned by GET /publishers/{id}."""

    publisher_id: int | None = None
    storefront_url: str | None = None
    identities: list[PublisherIdentity] = field(default_factory=list)
    created_at: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "Publisher":
        known = {"publisher_id", "storefront_url", "identities", "created_at"}
        return cls(
            publisher_id=d.get("publisher_id"),
            storefront_url=d.get("storefront_url"),
            identities=[PublisherIdentity.from_dict(i) for i in d.get("identities", [])],
            created_at=d.get("created_at"),
            extra={k: v for k, v in d.items() if k not in known},
        )


@dataclass
class PublisherListResponse:
    """Wrapper around the list returned by GET /publishers."""

    publishers: list[Publisher]
    count: int | None = None

    @classmethod
    def from_raw(cls, raw: list | dict) -> "PublisherListResponse":
        if isinstance(raw, list):
            return cls(publishers=[Publisher.from_dict(p) for p in raw])
        items = raw.get("items") or raw.get("publishers") or raw.get("data") or []
        return cls(
            publishers=[Publisher.from_dict(p) for p in items],
            count=raw.get("count"),
        )


# ---------------------------------------------------------------------------
# Listings
# ---------------------------------------------------------------------------


@dataclass
class ComputeResource:
    gpu_model: str
    quantity: int
    sla: float
    region: str

    def to_dict(self) -> dict:
        return {
            "gpu_model": self.gpu_model,
            "quantity": self.quantity,
            "sla": self.sla,
            "region": self.region,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ComputeResource":
        return cls(
            gpu_model=d["gpu_model"],
            quantity=d["quantity"],
            sla=d["sla"],
            region=d["region"],
        )


@dataclass
class TokenResource:
    token: str
    amount: float

    def to_dict(self) -> dict:
        return {"token": self.token, "amount": self.amount}

    @classmethod
    def from_dict(cls, d: dict) -> "TokenResource":
        return cls(token=d["token"], amount=d["amount"])


@dataclass
class ListingRequest:
    """Listing fields for POST /listings.

    ``storefront_url`` is the publisher's storefront URL (recorded on the
    publisher). The signing identity and signature are added by the client
    at publish time, not here.
    """

    offer: dict[str, Any]
    accepted_escrows: list[dict[str, Any]]
    max_duration_seconds: int | None = None
    listing_id: str = field(default_factory=lambda: __import__("uuid").uuid4().hex)
    storefront_url: str = ""

    def to_dict(self) -> dict:
        return {
            "listing_id": self.listing_id,
            "offer_resource": self.offer,
            "accepted_escrows": self.accepted_escrows,
            "max_duration_seconds": self.max_duration_seconds,
            "storefront_url": self.storefront_url,
        }


@dataclass
class ListingSummary:
    """Single listing record as returned by GET /listings or
    GET /listings/{id}. Captures common fields defensively.

    ``storefront_url`` is the publisher's storefront URL — where a buyer
    negotiates.
    """

    id: str | int | None = None
    status: str | None = None
    publisher_id: int | None = None
    storefront_url: str | None = None
    offer: dict[str, Any] = field(default_factory=dict)
    accepted_escrows: list[dict[str, Any]] = field(default_factory=list)
    max_duration_seconds: int | None = None
    created_at: str | int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "ListingSummary":
        known = {
            "listing_id", "publisher_id", "storefront_url",
            "offer_resource", "accepted_escrows", "max_duration_seconds",
            "created_at", "updated_at", "status",
            "id", "offer", "maxDurationSeconds", "createdAt",
        }
        listing_id = d.get("listing_id") or d.get("id")
        offer = d.get("offer") or d.get("offer_resource") or {}
        accepted_escrows = d.get("accepted_escrows") or []
        return cls(
            id=listing_id,
            status=d.get("status"),
            publisher_id=d.get("publisher_id"),
            storefront_url=d.get("storefront_url"),
            offer=offer,
            accepted_escrows=accepted_escrows,
            max_duration_seconds=d.get("max_duration_seconds") or d.get("maxDurationSeconds"),
            created_at=d.get("created_at") or d.get("createdAt"),
            extra={k: v for k, v in d.items() if k not in known},
        )


@dataclass
class ListingListResponse:
    """Wrapper around GET /listings response (list or paginated envelope)."""

    listings: list[ListingSummary]
    total: int | None = None
    limit: int | None = None
    offset: int | None = None

    @classmethod
    def from_raw(cls, raw: list | dict) -> "ListingListResponse":
        if isinstance(raw, list):
            return cls(listings=[ListingSummary.from_dict(o) for o in raw])
        # Registry returns {"items": [...]} — also handle "listings" / "data"
        items = raw.get("items") or raw.get("listings") or raw.get("data") or []
        return cls(
            listings=[ListingSummary.from_dict(o) for o in items],
            total=raw.get("total"),
            limit=raw.get("limit"),
            offset=raw.get("offset"),
        )


# ---------------------------------------------------------------------------
# Listing update (request)
# ---------------------------------------------------------------------------


@dataclass
class UpdateListingRequest:
    """Request body for PUT /listings/{listing_id}.

    Constructs the signed body that the registry route expects. Auth fields
    (signature, timestamp) are embedded when ``private_key`` is supplied. The
    signature covers the ``listing_id`` (passed to :meth:`to_dict`), matching
    the registry's owner-scoped verification against the listing's publisher
    identity.
    """

    updates: dict[str, Any]
    private_key: str | None = None

    def to_dict(self, listing_id: str) -> dict:
        from registry_client.auth import build_auth_headers
        body = dict(self.updates)
        if self.private_key:
            auth = build_auth_headers(self.private_key, "update_listing", listing_id)
            body["signature"] = auth["X-Signature"]
            body["timestamp"] = int(auth["X-Timestamp"])
        return body


# ---------------------------------------------------------------------------
# System diagnostics  (GET /api/v1/system/stats)
# ---------------------------------------------------------------------------


@dataclass
class SystemStatsResponse:
    """Response from GET /api/v1/system/stats."""

    publisher_count: int = 0
    order_count: int = 0
    orders_by_status: dict[str, int] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "SystemStatsResponse":
        obs_raw = d.get("orders_by_status", {})
        obs = {k: int(v) for k, v in obs_raw.items()} if isinstance(obs_raw, dict) else {}
        known = {"publisher_count", "order_count", "orders_by_status"}
        return cls(
            publisher_count=int(d.get("publisher_count", 0)),
            order_count=int(d.get("order_count", 0)),
            orders_by_status=obs,
            extra={k: v for k, v in d.items() if k not in known},
        )


@dataclass
class ValidatePublishRequest:
    """Request body for POST /api/v1/listings/validate-publish."""

    listing_id: str
    offer_resource: dict
    accepted_escrows: list[dict]
    max_duration_seconds: int | None = None
    storefront_url: str = ""

    def to_dict(self) -> dict:
        d: dict = {
            "listing_id": self.listing_id,
            "storefront_url": self.storefront_url,
            "offer_resource": self.offer_resource,
            "accepted_escrows": self.accepted_escrows,
        }
        if self.max_duration_seconds is not None:
            d["max_duration_seconds"] = self.max_duration_seconds
        return d


@dataclass
class FilterSpecResponse:
    """Response from GET /filter-spec — what the registry advertises.

    ``etag`` is a stable hash over ``{version, listing_shape, filters}``.
    Buyers should cache by URL+etag and send ``If-Match: <etag>`` on
    every ``list_listings`` call so a spec rotation surfaces as a 412
    instead of a silent shape change.
    """

    version: int
    etag: str
    listing_shape: dict
    filters: list[dict]

    @classmethod
    def from_dict(cls, d: dict) -> "FilterSpecResponse":
        return cls(
            version=int(d.get("version", 0)),
            etag=str(d.get("etag", "")),
            listing_shape=dict(d.get("listing_shape") or {}),
            filters=list(d.get("filters") or []),
        )


@dataclass
class ValidatePublishResponse:
    """Response from POST /api/v1/listings/validate-publish."""

    valid: bool
    listing_id: str
    offer_resource_type: str | None = None
    accepted_escrows_count: int = 0
    errors: list = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "ValidatePublishResponse":
        known = {"valid", "listing_id", "offer_resource_type",
                 "accepted_escrows_count", "errors"}
        return cls(
            valid=bool(d.get("valid", False)),
            listing_id=d.get("listing_id", ""),
            offer_resource_type=d.get("offer_resource_type"),
            accepted_escrows_count=int(d.get("accepted_escrows_count", 0)),
            errors=list(d.get("errors", [])),
            extra={k: v for k, v in d.items() if k not in known},
        )
