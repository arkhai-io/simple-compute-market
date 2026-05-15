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
    accepted_escrows: list[dict[str, Any]]
    max_duration_seconds: int | None = None
    listing_id: str = field(default_factory=lambda: __import__("uuid").uuid4().hex)

    def to_dict(self) -> dict:
        return {
            "listing_id": self.listing_id,
            "offer_resource": self.offer,
            "accepted_escrows": self.accepted_escrows,
            "max_duration_seconds": self.max_duration_seconds,
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
    accepted_escrows: list[dict[str, Any]] = field(default_factory=list)
    max_duration_seconds: int | None = None
    created_at: str | int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "ListingSummary":
        known = {
            "listing_id", "agent_id", "seller", "buyer",
            "offer_resource", "accepted_escrows", "max_duration_seconds",
            "created_at", "updated_at", "status",
            # camelCase alternatives
            "id", "makerAgentId", "offer", "maxDurationSeconds", "createdAt",
            "maker_agent_id",
        }
        # Registry uses "listing_id" as the primary key; fall back to "id"
        listing_id = d.get("listing_id") or d.get("id")
        maker = (
            d.get("agent_id")
            or d.get("makerAgentId")
            or d.get("maker_agent_id")
            or d.get("seller")
        )
        offer = d.get("offer") or d.get("offer_resource") or {}
        accepted_escrows = d.get("accepted_escrows") or []
        return cls(
            id=listing_id,
            status=d.get("status"),
            maker_agent_id=maker,
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


# ---------------------------------------------------------------------------
# System diagnostics  (GET /api/v1/system/config|sync|stats)
# ---------------------------------------------------------------------------


@dataclass
class AgentIndexedResponse:
    """Response from GET /api/v1/system/sync/wait-for-agent."""

    indexed: bool
    agent_id: str
    elapsed_ms: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "AgentIndexedResponse":
        known = {"indexed", "agent_id", "elapsed_ms"}
        return cls(
            indexed=bool(d.get("indexed", False)),
            agent_id=str(d.get("agent_id", "")),
            elapsed_ms=int(d.get("elapsed_ms", 0)),
            extra={k: v for k, v in d.items() if k not in known},
        )


@dataclass
class SystemConfigResponse:
    """Response from GET /api/v1/system/config."""

    chain_id: int = 0
    rpc_url: str = ""
    identity_registry_address: str = ""
    reputation_registry_address: str = ""
    validation_registry_address: str = ""
    enable_health_checks: bool = False
    heartbeat_ttl_secs: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "SystemConfigResponse":
        known = {
            "chain_id", "rpc_url", "identity_registry_address",
            "reputation_registry_address", "validation_registry_address",
            "enable_health_checks", "heartbeat_ttl_secs",
        }
        return cls(
            chain_id=int(d.get("chain_id", 0)),
            rpc_url=d.get("rpc_url", ""),
            identity_registry_address=d.get("identity_registry_address", ""),
            reputation_registry_address=d.get("reputation_registry_address", ""),
            validation_registry_address=d.get("validation_registry_address", ""),
            enable_health_checks=bool(d.get("enable_health_checks", False)),
            heartbeat_ttl_secs=int(d.get("heartbeat_ttl_secs", 0)),
            extra={k: v for k, v in d.items() if k not in known},
        )


@dataclass
class SystemSyncResponse:
    """Response from GET /api/v1/system/sync."""

    event_sync_running: bool = False
    event_sync_last_block: int = 0
    health_check_running: bool = False
    health_check_enabled: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "SystemSyncResponse":
        es = d.get("event_sync", {})
        hc = d.get("health_check", {})
        return cls(
            event_sync_running=bool(es.get("running", False)),
            event_sync_last_block=int(es.get("last_synced_block", 0)),
            health_check_running=bool(hc.get("running", False)),
            health_check_enabled=bool(hc.get("enabled", False)),
            extra={k: v for k, v in d.items() if k not in ("event_sync", "health_check")},
        )


@dataclass
class SystemStatsResponse:
    """Response from GET /api/v1/system/stats."""

    agent_count: int = 0
    order_count: int = 0
    orders_by_status: dict[str, int] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "SystemStatsResponse":
        obs_raw = d.get("orders_by_status", {})
        obs = {k: int(v) for k, v in obs_raw.items()} if isinstance(obs_raw, dict) else {}
        known = {"agent_count", "order_count", "orders_by_status"}
        return cls(
            agent_count=int(d.get("agent_count", 0)),
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

    def to_dict(self) -> dict:
        d: dict = {
            "listing_id": self.listing_id,
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
