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
# Agents
# ---------------------------------------------------------------------------


@dataclass
class Capability:
    id: str
    name: str
    description: str | None = None
    tags: list[str] = field(default_factory=list)
    input_modes: list[str] = field(default_factory=lambda: ["text/plain"])
    output_modes: list[str] = field(default_factory=lambda: ["text/plain"])
    examples: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "Capability":
        return cls(
            id=d["id"],
            name=d["name"],
            description=d.get("description"),
            tags=d.get("tags", []),
            input_modes=d.get("inputModes", ["text/plain"]),
            output_modes=d.get("outputModes", ["text/plain"]),
            examples=d.get("examples", []),
        )


@dataclass
class Endpoint:
    name: str
    endpoint: str
    version: str | None = None
    mcp_tools: list[str] | None = None
    mcp_prompts: list[str] | None = None
    mcp_resources: list[str] | None = None
    a2a_skills: list[str] | None = None

    @classmethod
    def from_dict(cls, d: dict) -> "Endpoint":
        return cls(
            name=d["name"],
            endpoint=d["endpoint"],
            version=d.get("version"),
            mcp_tools=d.get("mcpTools"),
            mcp_prompts=d.get("mcpPrompts"),
            mcp_resources=d.get("mcpResources"),
            a2a_skills=d.get("a2aSkills"),
        )


@dataclass
class AgentSummary:
    """
    Lightweight agent representation returned by GET /agents.
    The API currently returns ``{}`` schema, so we capture all known fields
    defensively and stash extras.
    """

    id: str | int | None = None
    agent_id: str | None = None           # canonical eip155:… form
    name: str | None = None
    description: str | None = None
    owner: str | None = None
    chain_id: int | None = None
    visibility: str | None = None
    labels: dict[str, str] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "AgentSummary":
        known = {"id", "agentId", "name", "description", "owner", "chainId",
                 "visibility", "labels"}
        return cls(
            id=d.get("id"),
            agent_id=d.get("agentId"),
            name=d.get("name"),
            description=d.get("description"),
            owner=d.get("owner"),
            chain_id=d.get("chainId"),
            visibility=d.get("visibility"),
            labels=d.get("labels", {}),
            extra={k: v for k, v in d.items() if k not in known},
        )


@dataclass
class AgentListResponse:
    """Wrapper around the list returned by GET /agents."""

    agents: list[AgentSummary]
    total: int | None = None
    limit: int | None = None
    offset: int | None = None

    @classmethod
    def from_raw(cls, raw: list | dict) -> "AgentListResponse":
        """
        The API may return a plain list or a paginated envelope dict.
        Handle both shapes.
        """
        if isinstance(raw, list):
            return cls(agents=[AgentSummary.from_dict(a) for a in raw])
        # Paginated envelope — registry uses "items"; also handle "agents" / "data"
        items = raw.get("items") or raw.get("agents") or raw.get("data") or []
        return cls(
            agents=[AgentSummary.from_dict(a) for a in items],
            total=raw.get("total"),
            limit=raw.get("limit"),
            offset=raw.get("offset"),
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
    """Request body for POST /agents/{agent_id}/listings."""

    offer: dict[str, Any]
    demand: dict[str, Any]
    duration_hours: float
    listing_id: str = field(default_factory=lambda: __import__("uuid").uuid4().hex)

    def to_dict(self) -> dict:
        return {
            "listing_id": self.listing_id,
            "offer_resource": self.offer,
            "demand_resource": self.demand,
            "duration_hours": self.duration_hours,
        }


@dataclass
class ListingSummary:
    """
    Single listing record as returned by GET /listings or
    GET /agents/{id}/listings. Schema is ``{}`` in the spec; we capture
    common fields defensively.
    """

    id: str | int | None = None
    status: str | None = None
    maker_agent_id: str | None = None
    offer: dict[str, Any] = field(default_factory=dict)
    demand: dict[str, Any] = field(default_factory=dict)
    duration_hours: float | None = None
    created_at: str | int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "ListingSummary":
        known = {
            # Listings vocabulary (current registry wire)
            "listing_id", "agent_id", "seller", "buyer",
            "offer_resource", "demand_resource", "duration_hours",
            "created_at", "updated_at", "status",
            "seller_attestation", "buyer_attestation",
            # camelCase alternatives
            "id", "makerAgentId", "offer", "demand", "durationHours", "createdAt",
            "maker_agent_id",
        }
        # Registry uses "listing_id" as the primary key; fall back to "id"
        listing_id = d.get("listing_id") or d.get("id")
        # "agent_id" is the canonical agent who owns the listing in registry
        # responses; camelCase APIs use "makerAgentId"; "seller" is the
        # agent's base URL.
        maker = (
            d.get("agent_id")
            or d.get("makerAgentId")
            or d.get("maker_agent_id")
            or d.get("seller")
        )
        # offer/demand may be nested as offer_resource/demand_resource
        offer = d.get("offer") or d.get("offer_resource") or {}
        demand = d.get("demand") or d.get("demand_resource") or {}
        return cls(
            id=listing_id,
            status=d.get("status"),
            maker_agent_id=maker,
            offer=offer,
            demand=demand,
            duration_hours=d.get("duration_hours") or d.get("durationHours"),
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
# Listing update + heartbeat (request)
# ---------------------------------------------------------------------------


@dataclass
class UpdateListingRequest:
    """Request body for PUT /listings/{listing_id}.

    Constructs the signed body that the registry route expects.
    Auth fields (signature, timestamp, signer_agent_id) are embedded
    when ``private_key`` is supplied.
    """

    updates: dict[str, Any]
    private_key: str | None = None
    agent_id: str | None = None

    def to_dict(self) -> dict:
        from registry_client.auth import build_auth_headers
        body = dict(self.updates)
        if self.private_key:
            auth = build_auth_headers(self.private_key, "update_listing",
                                      self.updates.get("listing_id", ""))
            body["signature"] = auth["X-Signature"]
            body["timestamp"] = int(auth["X-Timestamp"])
        if self.agent_id:
            body["signer_agent_id"] = self.agent_id
        return body


@dataclass
class HeartbeatRequest:
    signature: str | None = None
    timestamp: int | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in {"signature": self.signature, "timestamp": self.timestamp}.items()
                if v is not None}


@dataclass
class AttestationStats:
    """Settlement activity counts from GET /api/v1/system/stats/attestations.

    settled_listing_count > 0 means at least one full Alkahest deal cycle
    has completed: buyer locked escrow (seller_attestation) and seller
    attested fulfillment (buyer_attestation).
    """

    settled_listing_count: int = 0
    seller_attestation_count: int = 0
    buyer_attestation_count: int = 0

    @classmethod
    def from_dict(cls, d: dict) -> "AttestationStats":
        return cls(
            settled_listing_count=int(
                d.get("settled_listing_count", d.get("settled_order_count", 0))
            ),
            seller_attestation_count=int(
                d.get("seller_attestation_count", d.get("maker_attestation_count", 0))
            ),
            buyer_attestation_count=int(
                d.get("buyer_attestation_count", d.get("taker_attestation_count", 0))
            ),
        )
