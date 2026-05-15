"""Response and registration models for the Arkhai storefront REST API.

These dataclasses represent the response shapes returned by the
storefront's HTTP endpoints. They live in ``storefront-client``
because they are part of the API contract — the same contract
documented in the versioning policy in ``storefront-client/README.md``.

Request builders (``StorefrontListingCreateRequest``, etc.) remain in
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
# Listing create response  (POST /listings/create)
# ---------------------------------------------------------------------------


@dataclass
class StorefrontListingCreateResponse:
    """Response from POST /listings/create.

    status values:
        ``"created"``   — policy accepted; listing_id is set.
        ``"no_action"`` — policy ran but did not create a listing (no matching policy).
    """

    status: str | None = None
    listing_id: str | None = None
    root_agent_response: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "StorefrontListingCreateResponse":
        known = {"status", "listing_id", "root_agent_response"}
        return cls(
            status=d.get("status"),
            listing_id=d.get("listing_id"),
            root_agent_response=d.get("root_agent_response"),
            extra={k: v for k, v in d.items() if k not in known},
        )


# ---------------------------------------------------------------------------
# Listing close response  (POST /listings/close)
# ---------------------------------------------------------------------------


@dataclass
class StorefrontListingCloseResponse:
    """Response from POST /listings/close.

    status values: ``"closed"``
    """

    listing_id: str | None = None
    root_agent_response: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "StorefrontListingCloseResponse":
        known = {"status", "listing_id", "root_agent_response"}
        return cls(
            status=d.get("status"),
            listing_id=d.get("listing_id"),
            root_agent_response=d.get("root_agent_response"),
            extra={k: v for k, v in d.items() if k not in known},
        )


# ---------------------------------------------------------------------------
# Listing refund response  (POST /listings/refund)
# ---------------------------------------------------------------------------


@dataclass
class StorefrontListingRefundResponse:
    """Response from POST /listings/refund."""

    status: str | None = None
    listing_id: str | None = None
    refund_tx: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "StorefrontListingRefundResponse":
        known = {"status", "listing_id", "refund_tx"}
        return cls(
            status=d.get("status"),
            listing_id=d.get("listing_id"),
            refund_tx=d.get("refund_tx"),
            extra={k: v for k, v in d.items() if k not in known},
        )


# ---------------------------------------------------------------------------
# Listing claim response  (POST /listings/claim)
# ---------------------------------------------------------------------------


@dataclass
class StorefrontListingClaimResponse:
    """Response from POST /listings/claim."""

    status: str | None = None
    listing_id: str | None = None
    fulfillment_uid: str | None = None
    claim_tx: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "StorefrontListingClaimResponse":
        known = {"status", "listing_id", "fulfillment_uid", "claim_tx"}
        return cls(
            status=d.get("status"),
            listing_id=d.get("listing_id"),
            fulfillment_uid=d.get("fulfillment_uid"),
            claim_tx=d.get("claim_tx"),
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
    agent_id: str | None = None  # canonical eip155:… form; present on /api/v1/system/status
    chain_id: int | None = None  # EVM chain ID; present on /api/v1/system/status
    resource_count: int | None = None  # registered compute resources; present on /api/v1/system/status
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "HealthResponse":
        known = {"status", "checks", "paused", "agent_id", "chain_id", "resource_count"}
        raw_chain_id = d.get("chain_id")
        raw_resource_count = d.get("resource_count")
        return cls(
            status=d.get("status", "ok"),
            checks=d.get("checks", {}),
            paused=d.get("paused"),
            agent_id=d.get("agent_id"),
            chain_id=int(raw_chain_id) if raw_chain_id is not None else None,
            resource_count=int(raw_resource_count) if raw_resource_count is not None else None,
            extra={k: v for k, v in d.items() if k not in known},
        )


# ---------------------------------------------------------------------------
# Listings API  (GET /api/v1/listings, GET /api/v1/listings/{id})
# ---------------------------------------------------------------------------


@dataclass
class ListingSummary:
    """A single row from GET /api/v1/listings or GET /api/v1/listings/{id}."""

    listing_id: str = ""
    status: str = ""
    paused: bool = False
    max_duration_seconds: int | None = None
    seller: str = ""
    buyer: str | None = None
    escrow_uid: str | None = None
    created_at: str = ""
    updated_at: str = ""
    offer_resource: dict[str, Any] = field(default_factory=dict)
    demand_resource: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "ListingSummary":
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
            "listing_id", "status", "paused", "max_duration_seconds", "seller",
            "buyer", "escrow_uid", "created_at", "updated_at",
            "offer_resource", "demand_resource",
        }
        max_dur = d.get("max_duration_seconds")
        return cls(
            listing_id=d.get("listing_id", ""),
            status=d.get("status", ""),
            paused=bool(d.get("paused", False)),
            max_duration_seconds=int(max_dur) if max_dur is not None else None,
            seller=d.get("seller", ""),
            buyer=d.get("buyer"),
            escrow_uid=d.get("escrow_uid"),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
            offer_resource=_parse_resource(d.get("offer_resource")),
            demand_resource=_parse_resource(d.get("demand_resource")),
            extra={k: v for k, v in d.items() if k not in known},
        )


@dataclass
class ListingListResponse:
    """Response from GET /api/v1/listings."""

    listings: list[ListingSummary] = field(default_factory=list)
    count: int = 0
    limit: int = 50
    offset: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "ListingListResponse":
        known = {"listings", "count", "limit", "offset"}
        return cls(
            listings=[ListingSummary.from_dict(o) for o in d.get("listings", [])],
            count=d.get("count", 0),
            limit=d.get("limit", 50),
            offset=d.get("offset", 0),
            extra={k: v for k, v in d.items() if k not in known},
        )


@dataclass
class ListingPauseResponse:
    """Response from POST /api/v1/listings/{id}/pause or /resume."""

    listing_id: str = ""
    paused: bool = False
    registry_status: str = ""   # "published" | "disabled" | "error" | "" (absent on pause)
    message: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "ListingPauseResponse":
        known = {"listing_id", "paused", "registry_status", "message"}
        return cls(
            listing_id=d.get("listing_id", ""),
            paused=bool(d.get("paused", False)),
            registry_status=d.get("registry_status", ""),
            message=d.get("message", ""),
            extra={k: v for k, v in d.items() if k not in known},
        )


# ---------------------------------------------------------------------------
# Stage events  (GET /api/v1/system/events)
# ---------------------------------------------------------------------------


@dataclass
class StageEvent:
    """A single row from the stage_events table."""

    id: int = 0
    ts: str = ""
    stage: str = ""
    event: str = ""
    negotiation_id: str | None = None
    listing_id: str | None = None
    escrow_uid: str | None = None
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "StageEvent":
        known = {"id", "ts", "stage", "event", "negotiation_id", "listing_id", "escrow_uid", "data"}
        return cls(
            id=int(d.get("id", 0)),
            ts=d.get("ts", ""),
            stage=d.get("stage", ""),
            event=d.get("event", ""),
            negotiation_id=d.get("negotiation_id"),
            listing_id=d.get("listing_id"),
            escrow_uid=d.get("escrow_uid"),
            data=d.get("data", {}),
        )


@dataclass
class StageEventListResponse:
    """Response from GET /api/v1/system/events (non-streaming)."""

    events: list[StageEvent] = field(default_factory=list)
    count: int = 0

    @classmethod
    def from_dict(cls, d: dict) -> "StageEventListResponse":
        return cls(
            events=[StageEvent.from_dict(e) for e in d.get("events", [])],
            count=d.get("count", 0),
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
    """A single row from GET /api/v1/listings/{id}/negotiations."""

    negotiation_id: str = ""
    our_listing_id: str = ""
    buyer_address: str = ""
    status: str = ""
    terminal_state: str | None = None
    agreed_price: int | None = None
    agreed_duration_seconds: int | None = None
    requested_duration_seconds: int | None = None
    created_at: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "NegotiationSummary":
        known = {
            "negotiation_id", "our_listing_id", "buyer_address", "status",
            "terminal_state", "agreed_price", "agreed_duration_seconds",
            "requested_duration_seconds", "created_at",
        }
        return cls(
            negotiation_id=d.get("negotiation_id", ""),
            our_listing_id=d.get("our_listing_id", ""),
            buyer_address=d.get("buyer_address", ""),
            status=d.get("status", ""),
            terminal_state=d.get("terminal_state"),
            agreed_price=d.get("agreed_price"),
            agreed_duration_seconds=d.get("agreed_duration_seconds"),
            requested_duration_seconds=d.get("requested_duration_seconds"),
            created_at=d.get("created_at", ""),
            extra={k: v for k, v in d.items() if k not in known},
        )


@dataclass
class NegotiationListResponse:
    """Response from GET /api/v1/listings/{id}/negotiations."""

    listing_id: str = ""
    negotiations: list[NegotiationSummary] = field(default_factory=list)
    count: int = 0
    limit: int = 50
    offset: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "NegotiationListResponse":
        known = {"listing_id", "negotiations", "count", "limit", "offset"}
        return cls(
            listing_id=d.get("listing_id", ""),
            negotiations=[NegotiationSummary.from_dict(n) for n in d.get("negotiations", [])],
            count=d.get("count", 0),
            limit=d.get("limit", 50),
            offset=d.get("offset", 0),
            extra={k: v for k, v in d.items() if k not in known},
        )


@dataclass
class NegotiationDetail:
    """Response from GET /api/v1/listings/{id}/negotiations/{neg_id}."""

    negotiation_id: str = ""
    our_listing_id: str = ""
    their_agent_id: str = ""
    status: str = ""
    terminal_state: str | None = None
    agreed_price: int | None = None
    agreed_duration_seconds: int | None = None
    requested_duration_seconds: int | None = None
    round_count: int = 0
    messages: list[NegotiationMessage] = field(default_factory=list)
    stage_events: list[dict[str, Any]] = field(default_factory=list)
    escrows: list[dict[str, Any]] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "NegotiationDetail":
        known = {
            "negotiation_id", "our_listing_id", "their_agent_id", "status",
            "terminal_state", "agreed_price", "agreed_duration_seconds",
            "requested_duration_seconds", "round_count", "messages", "stage_events",
            "escrows",
        }
        return cls(
            negotiation_id=d.get("negotiation_id", ""),
            our_listing_id=d.get("our_listing_id", ""),
            their_agent_id=d.get("their_agent_id", ""),
            status=d.get("status", ""),
            terminal_state=d.get("terminal_state"),
            agreed_price=d.get("agreed_price"),
            agreed_duration_seconds=d.get("agreed_duration_seconds"),
            requested_duration_seconds=d.get("requested_duration_seconds"),
            round_count=d.get("round_count", 0),
            messages=[NegotiationMessage.from_dict(m) for m in d.get("messages", [])],
            stage_events=d.get("stage_events", []),
            escrows=d.get("escrows", []),
            extra={k: v for k, v in d.items() if k not in known},
        )


@dataclass
class NegotiationActionResponse:
    """Response from POST .../advance or .../force-accept."""

    neg_id: str = ""
    listing_id: str = ""
    action: str = ""
    price: int | None = None
    reason: str | None = None
    source: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "NegotiationActionResponse":
        known = {"neg_id", "listing_id", "action", "price", "reason", "source"}
        return cls(
            neg_id=d.get("neg_id", ""),
            listing_id=d.get("listing_id", ""),
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
class ReleaseReservationsResponse:
    """Response from POST /api/v1/admin/portfolio/release-reservations."""

    released_count: int = 0
    resource_ids: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "ReleaseReservationsResponse":
        known = {"released_count", "resource_ids"}
        return cls(
            released_count=int(d.get("released_count", 0)),
            resource_ids=list(d.get("resource_ids", []) or []),
            extra={k: v for k, v in d.items() if k not in known},
        )


@dataclass
class EvaluateNegotiateResponse:
    """Response from POST /api/v1/admin/listings/{listing_id}/evaluate-negotiate."""

    listing_id: str = ""
    our_reference_price: int = 0
    their_proposed_price: int = 0
    direction: str = ""
    strategy: str = ""
    decision: str = ""
    decision_price: int | None = None
    decision_reason: str | None = None
    would_negotiate: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "EvaluateNegotiateResponse":
        known = {
            "listing_id", "our_reference_price", "their_proposed_price",
            "direction", "strategy", "decision", "decision_price",
            "decision_reason", "would_negotiate",
        }
        return cls(
            listing_id=d.get("listing_id", ""),
            our_reference_price=int(d.get("our_reference_price", 0)),
            their_proposed_price=int(d.get("their_proposed_price", 0)),
            direction=d.get("direction", ""),
            strategy=d.get("strategy", ""),
            decision=d.get("decision", ""),
            decision_price=d.get("decision_price"),
            decision_reason=d.get("decision_reason"),
            would_negotiate=bool(d.get("would_negotiate", False)),
            extra={k: v for k, v in d.items() if k not in known},
        )


@dataclass
class SettleResponse:
    """Response from POST /api/v1/settle/{escrow_uid}."""

    status: str = ""
    escrow_uid: str = ""
    negotiation_id: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "SettleResponse":
        known = {"status", "escrow_uid", "negotiation_id"}
        return cls(
            status=d.get("status", ""),
            escrow_uid=d.get("escrow_uid", ""),
            negotiation_id=d.get("negotiation_id", ""),
            extra={k: v for k, v in d.items() if k not in known},
        )


@dataclass
class RegistryAgentReadyResponse:
    """Response from GET /api/v1/system/wait-for-registry-agent."""

    ready: bool = False
    registry_auth: str = ""
    elapsed_ms: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "RegistryAgentReadyResponse":
        known = {"ready", "registry_auth", "elapsed_ms"}
        return cls(
            ready=bool(d.get("ready", False)),
            registry_auth=str(d.get("registry_auth", "")),
            elapsed_ms=int(d.get("elapsed_ms", 0)),
            extra={k: v for k, v in d.items() if k not in known},
        )


@dataclass
class SettleStatusResponse:
    """Response from GET /api/v1/settle/{escrow_uid}/status."""

    status: str = ""
    escrow_uid: str = ""
    fulfillment_uid: str | None = None
    provisioning_job_id: str | None = None
    tenant_credentials: dict[str, Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "SettleStatusResponse":
        known = {
            "status", "escrow_uid", "fulfillment_uid",
            "provisioning_job_id", "tenant_credentials",
        }
        creds = d.get("tenant_credentials")
        return cls(
            status=d.get("status", ""),
            escrow_uid=d.get("escrow_uid", ""),
            fulfillment_uid=d.get("fulfillment_uid"),
            provisioning_job_id=d.get("provisioning_job_id"),
            tenant_credentials=dict(creds) if isinstance(creds, dict) else None,
            extra={k: v for k, v in d.items() if k not in known},
        )


@dataclass
class SettleWaitResponse:
    """Response from GET /api/v1/admin/settle/{escrow_uid}/wait."""

    ready: bool = False
    status: str = ""
    provisioning_job_id: str | None = None
    elapsed_ms: int = 0

    @classmethod
    def from_dict(cls, d: dict) -> "SettleWaitResponse":
        return cls(
            ready=bool(d.get("ready", False)),
            status=str(d.get("status", "")),
            provisioning_job_id=d.get("provisioning_job_id"),
            elapsed_ms=int(d.get("elapsed_ms", 0)),
        )


@dataclass
class ImportResourcesResponse:
    """Response from POST /api/v1/admin/portfolio/resources/import."""

    imported_count: int = 0
    failed_count: int = 0
    total_rows: int = 0

    @classmethod
    def from_dict(cls, d: dict) -> "ImportResourcesResponse":
        return cls(
            imported_count=int(d.get("imported_count", 0)),
            failed_count=int(d.get("failed_count", 0)),
            total_rows=int(d.get("total_rows", 0)),
        )
