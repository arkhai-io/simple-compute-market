"""Response and registration models for the Arkhai storefront REST API.

These dataclasses represent the response shapes returned by the
storefront's HTTP endpoints. They live in ``storefront-client``
because they are part of the API contract — the same contract
documented in the versioning policy in ``storefront-client/README.md``.

Request builders (``StorefrontOrderCreateRequest``, etc.) remain in
the consuming test project until the full client migration is
complete.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# ERC-8004 registration file  (GET /.well-known/erc-8004-registration.json)
# ---------------------------------------------------------------------------


@dataclass
class RegistrationRecord:
    """Single on-chain registration entry inside the ERC-8004 file."""

    agent_id: int | None = None       # 0 means not yet registered
    agent_registry: str | None = None  # "eip155:<chainId>:<address>"

    @classmethod
    def from_dict(cls, d: dict) -> "RegistrationRecord":
        return cls(
            agent_id=d.get("agentId"),
            agent_registry=d.get("agentRegistry"),
        )

    @property
    def registry_address(self) -> str | None:
        """Extract the bare 0x address from 'eip155:<chainId>:<address>'."""
        raw = self.agent_registry or ""
        parts = raw.split(":")
        return parts[-1] if len(parts) == 3 else None


@dataclass
class StorefrontEndpoint:
    name: str
    endpoint: str
    version: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "StorefrontEndpoint":
        known = {"name", "endpoint", "version"}
        return cls(
            name=d["name"],
            endpoint=d["endpoint"],
            version=d.get("version"),
            extra={k: v for k, v in d.items() if k not in known},
        )


@dataclass
class ERC8004RegistrationFile:
    """Response from GET /.well-known/erc-8004-registration.json"""

    type: str | None = None
    name: str | None = None
    description: str | None = None
    endpoints: list[StorefrontEndpoint] = field(default_factory=list)
    registrations: list[RegistrationRecord] = field(default_factory=list)
    updated_at: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "ERC8004RegistrationFile":
        known = {"type", "name", "description", "endpoints", "registrations", "updatedAt"}
        return cls(
            type=d.get("type"),
            name=d.get("name"),
            description=d.get("description"),
            endpoints=[StorefrontEndpoint.from_dict(e) for e in d.get("endpoints", [])],
            registrations=[RegistrationRecord.from_dict(r) for r in d.get("registrations", [])],
            updated_at=d.get("updatedAt"),
            extra={k: v for k, v in d.items() if k not in known},
        )

    @property
    def is_registered(self) -> bool:
        """True iff at least one registration record has a non-zero agentId."""
        return any(r.agent_id is not None for r in self.registrations)


# ---------------------------------------------------------------------------
# Order create response  (POST /orders/create)
# ---------------------------------------------------------------------------


@dataclass
class StorefrontOrderCreateResponse:
    """Response from POST /orders/create.

    status values:
        ``"created"``   — storefront processed synchronously; order_id set.
        ``"no_action"`` — storefront ran but did not create an order.
        ``"queued"``    — enable_event_queue is True; processed async.
    """

    status: str | None = None
    event_id: str | None = None
    order_id: str | None = None
    root_agent_response: str | None = None
    order_request: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "StorefrontOrderCreateResponse":
        known = {"status", "event_id", "order_id", "root_agent_response", "order_request"}
        return cls(
            status=d.get("status"),
            event_id=d.get("event_id"),
            order_id=d.get("order_id"),
            root_agent_response=d.get("root_agent_response"),
            order_request=d.get("order_request", {}),
            extra={k: v for k, v in d.items() if k not in known},
        )


# ---------------------------------------------------------------------------
# Order close response  (POST /orders/close)
# ---------------------------------------------------------------------------


@dataclass
class StorefrontOrderCloseResponse:
    """Response from POST /orders/close.

    status values: ``"closed"`` | ``"queued"``
    """

    status: str | None = None
    event_id: str | None = None
    root_agent_response: str | None = None
    order_request: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "StorefrontOrderCloseResponse":
        known = {"status", "event_id", "root_agent_response", "order_request"}
        return cls(
            status=d.get("status"),
            event_id=d.get("event_id"),
            root_agent_response=d.get("root_agent_response"),
            order_request=d.get("order_request", {}),
            extra={k: v for k, v in d.items() if k not in known},
        )


# ---------------------------------------------------------------------------
# Order refund response  (POST /orders/refund)
# ---------------------------------------------------------------------------


@dataclass
class StorefrontOrderRefundResponse:
    """Response from POST /orders/refund."""

    status: str | None = None
    order_id: str | None = None
    refund_tx: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "StorefrontOrderRefundResponse":
        known = {"status", "order_id", "refund_tx"}
        return cls(
            status=d.get("status"),
            order_id=d.get("order_id"),
            refund_tx=d.get("refund_tx"),
            extra={k: v for k, v in d.items() if k not in known},
        )


# ---------------------------------------------------------------------------
# Order claim response  (POST /orders/claim)
# ---------------------------------------------------------------------------


@dataclass
class StorefrontOrderClaimResponse:
    """Response from POST /orders/claim."""

    status: str | None = None
    order_id: str | None = None
    fulfillment_uid: str | None = None
    claim_tx: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "StorefrontOrderClaimResponse":
        known = {"status", "order_id", "fulfillment_uid", "claim_tx"}
        return cls(
            status=d.get("status"),
            order_id=d.get("order_id"),
            fulfillment_uid=d.get("fulfillment_uid"),
            claim_tx=d.get("claim_tx"),
            extra={k: v for k, v in d.items() if k not in known},
        )


# ---------------------------------------------------------------------------
# Order discover response  (POST /orders/discover)
# ---------------------------------------------------------------------------


@dataclass
class DiscoverMatch:
    """A single match returned by /orders/discover."""

    their_order_id: str | None = None
    their_agent_url: str | None = None
    their_price: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "DiscoverMatch":
        known = {"their_order_id", "their_agent_url", "their_price"}
        return cls(
            their_order_id=d.get("their_order_id"),
            their_agent_url=d.get("their_agent_url"),
            their_price=d.get("their_price"),
            extra={k: v for k, v in d.items() if k not in known},
        )


@dataclass
class StorefrontOrderDiscoverResponse:
    """Response from POST /orders/discover."""

    order_id: str | None = None
    match_count: int | None = None
    matches: list[DiscoverMatch] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "StorefrontOrderDiscoverResponse":
        known = {"order_id", "match_count", "matches"}
        return cls(
            order_id=d.get("order_id"),
            match_count=d.get("match_count"),
            matches=[DiscoverMatch.from_dict(m) for m in d.get("matches", [])],
            extra={k: v for k, v in d.items() if k not in known},
        )
