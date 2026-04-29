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


# ---------------------------------------------------------------------------
# Health / system  (GET /health, GET /api/v1/system/status)
# ---------------------------------------------------------------------------


@dataclass
class HealthResponse:
    """Response from GET /health or GET /api/v1/system/health."""

    status: str = "ok"          # "ok" | "degraded"
    checks: dict[str, str] = field(default_factory=dict)
    paused: bool | None = None  # present on /api/v1/system/status only
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "HealthResponse":
        known = {"status", "checks", "paused"}
        return cls(
            status=d.get("status", "ok"),
            checks=d.get("checks", {}),
            paused=d.get("paused"),
            extra={k: v for k, v in d.items() if k not in known},
        )


# ---------------------------------------------------------------------------
# Orders API  (GET /api/v1/orders, GET /api/v1/orders/{id})
# ---------------------------------------------------------------------------


@dataclass
class OrderSummary:
    """A single row from GET /api/v1/orders or GET /api/v1/orders/{id}."""

    order_id: str = ""
    status: str = ""
    paused: bool = False
    duration_hours: int = 1
    order_maker: str = ""
    order_taker: str | None = None
    escrow_uid: str | None = None
    created_at: str = ""
    updated_at: str = ""
    offer_resource: dict[str, Any] = field(default_factory=dict)
    demand_resource: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "OrderSummary":
        import json as _json

        def _parse_resource(v: Any) -> dict[str, Any]:
            if isinstance(v, dict):
                return v
            if isinstance(v, str):
                try:
                    return _json.loads(v)
                except Exception:
                    return {}
            return {}

        known = {
            "order_id", "status", "paused", "duration_hours", "order_maker",
            "order_taker", "escrow_uid", "created_at", "updated_at",
            "offer_resource", "demand_resource",
        }
        return cls(
            order_id=d.get("order_id", ""),
            status=d.get("status", ""),
            paused=bool(d.get("paused", False)),
            duration_hours=int(d.get("duration_hours", 1)),
            order_maker=d.get("order_maker", ""),
            order_taker=d.get("order_taker"),
            escrow_uid=d.get("escrow_uid"),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
            offer_resource=_parse_resource(d.get("offer_resource")),
            demand_resource=_parse_resource(d.get("demand_resource")),
            extra={k: v for k, v in d.items() if k not in known},
        )


@dataclass
class OrderListResponse:
    """Response from GET /api/v1/orders."""

    orders: list[OrderSummary] = field(default_factory=list)
    count: int = 0
    limit: int = 50
    offset: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "OrderListResponse":
        known = {"orders", "count", "limit", "offset"}
        return cls(
            orders=[OrderSummary.from_dict(o) for o in d.get("orders", [])],
            count=d.get("count", 0),
            limit=d.get("limit", 50),
            offset=d.get("offset", 0),
            extra={k: v for k, v in d.items() if k not in known},
        )


@dataclass
class OrderPauseResponse:
    """Response from POST /api/v1/orders/{id}/pause or /resume."""

    order_id: str = ""
    paused: bool = False
    message: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "OrderPauseResponse":
        known = {"order_id", "paused", "message"}
        return cls(
            order_id=d.get("order_id", ""),
            paused=bool(d.get("paused", False)),
            message=d.get("message", ""),
            extra={k: v for k, v in d.items() if k not in known},
        )


# ---------------------------------------------------------------------------
# Negotiations API
# ---------------------------------------------------------------------------


@dataclass
class NegotiationMessage:
    """A single round message in a negotiation thread."""

    round: int = 0
    sender: str = ""
    action_taken: str = ""
    proposed_price: int | None = None
    our_price: int | None = None
    their_price: int | None = None
    message_type: str = ""
    timestamp: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "NegotiationMessage":
        known = {
            "round", "sender", "action_taken", "proposed_price",
            "our_price", "their_price", "message_type", "timestamp",
        }
        return cls(
            round=int(d.get("round", 0)),
            sender=d.get("sender", ""),
            action_taken=d.get("action_taken", ""),
            proposed_price=d.get("proposed_price"),
            our_price=d.get("our_price"),
            their_price=d.get("their_price"),
            message_type=d.get("message_type", ""),
            timestamp=d.get("timestamp", ""),
            extra={k: v for k, v in d.items() if k not in known},
        )


@dataclass
class NegotiationSummary:
    """A single row from GET /api/v1/orders/{id}/negotiations."""

    negotiation_id: str = ""
    our_order_id: str = ""
    buyer_address: str = ""
    status: str = ""
    terminal_state: str | None = None
    agreed_price: int | None = None
    agreed_duration_hours: int | None = None
    created_at: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "NegotiationSummary":
        known = {
            "negotiation_id", "our_order_id", "buyer_address", "status",
            "terminal_state", "agreed_price", "agreed_duration_hours", "created_at",
        }
        return cls(
            negotiation_id=d.get("negotiation_id", ""),
            our_order_id=d.get("our_order_id", ""),
            buyer_address=d.get("buyer_address", ""),
            status=d.get("status", ""),
            terminal_state=d.get("terminal_state"),
            agreed_price=d.get("agreed_price"),
            agreed_duration_hours=d.get("agreed_duration_hours"),
            created_at=d.get("created_at", ""),
            extra={k: v for k, v in d.items() if k not in known},
        )


@dataclass
class NegotiationListResponse:
    """Response from GET /api/v1/orders/{id}/negotiations."""

    order_id: str = ""
    negotiations: list[NegotiationSummary] = field(default_factory=list)
    count: int = 0
    limit: int = 50
    offset: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "NegotiationListResponse":
        known = {"order_id", "negotiations", "count", "limit", "offset"}
        return cls(
            order_id=d.get("order_id", ""),
            negotiations=[NegotiationSummary.from_dict(n) for n in d.get("negotiations", [])],
            count=d.get("count", 0),
            limit=d.get("limit", 50),
            offset=d.get("offset", 0),
            extra={k: v for k, v in d.items() if k not in known},
        )


@dataclass
class NegotiationDetail:
    """Response from GET /api/v1/orders/{id}/negotiations/{neg_id}."""

    negotiation_id: str = ""
    our_order_id: str = ""
    their_agent_id: str = ""
    status: str = ""
    terminal_state: str | None = None
    agreed_price: int | None = None
    agreed_duration_hours: int | None = None
    round_count: int = 0
    messages: list[NegotiationMessage] = field(default_factory=list)
    stage_events: list[dict[str, Any]] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "NegotiationDetail":
        known = {
            "negotiation_id", "our_order_id", "their_agent_id", "status",
            "terminal_state", "agreed_price", "agreed_duration_hours",
            "round_count", "messages", "stage_events",
        }
        return cls(
            negotiation_id=d.get("negotiation_id", ""),
            our_order_id=d.get("our_order_id", ""),
            their_agent_id=d.get("their_agent_id", ""),
            status=d.get("status", ""),
            terminal_state=d.get("terminal_state"),
            agreed_price=d.get("agreed_price"),
            agreed_duration_hours=d.get("agreed_duration_hours"),
            round_count=d.get("round_count", 0),
            messages=[NegotiationMessage.from_dict(m) for m in d.get("messages", [])],
            stage_events=d.get("stage_events", []),
            extra={k: v for k, v in d.items() if k not in known},
        )


@dataclass
class NegotiationActionResponse:
    """Response from POST .../advance or .../force-accept."""

    neg_id: str = ""
    order_id: str = ""
    action: str = ""
    price: int | None = None
    reason: str | None = None
    source: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "NegotiationActionResponse":
        known = {"neg_id", "order_id", "action", "price", "reason", "source"}
        return cls(
            neg_id=d.get("neg_id", ""),
            order_id=d.get("order_id", ""),
            action=d.get("action", ""),
            price=d.get("price"),
            reason=d.get("reason"),
            source=d.get("source"),
            extra={k: v for k, v in d.items() if k not in known},
        )


# ---------------------------------------------------------------------------
# Admin API  (POST /admin/pause, GET /admin/status)
# ---------------------------------------------------------------------------


@dataclass
class AdminPauseResponse:
    """Response from POST /admin/pause or /admin/resume."""

    paused: bool = False
    message: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "AdminPauseResponse":
        known = {"paused", "message"}
        return cls(
            paused=bool(d.get("paused", False)),
            message=d.get("message", ""),
            extra={k: v for k, v in d.items() if k not in known},
        )


@dataclass
class AdminStatusResponse:
    """Response from GET /admin/status."""

    paused: bool = False
    active_negotiations: int = 0
    open_orders: int = 0
    paused_orders: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "AdminStatusResponse":
        known = {"paused", "active_negotiations", "open_orders", "paused_orders"}
        return cls(
            paused=bool(d.get("paused", False)),
            active_negotiations=int(d.get("active_negotiations", 0)),
            open_orders=int(d.get("open_orders", 0)),
            paused_orders=int(d.get("paused_orders", 0)),
            extra={k: v for k, v in d.items() if k not in known},
        )
