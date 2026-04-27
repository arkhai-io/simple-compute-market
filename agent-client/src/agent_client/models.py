"""Response and registration models for the Arkhai agent REST API.

These dataclasses represent the response shapes returned by the agent's
HTTP endpoints.  They live in ``agent-client`` because they are part of
the API contract — the same contract documented in the versioning policy
in ``agent-client/README.md``.

Request builders (``AgentOrderCreateRequest``, etc.) remain in the
consuming test project until the full client migration is complete.
See TODO(agent-client-migration) in ARCHITECTURE.md.
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
class AgentEndpoint:
    name: str
    endpoint: str
    version: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "AgentEndpoint":
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
    endpoints: list[AgentEndpoint] = field(default_factory=list)
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
            endpoints=[AgentEndpoint.from_dict(e) for e in d.get("endpoints", [])],
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
class AgentOrderCreateResponse:
    """Response from POST /orders/create.

    status values:
        ``"created"``   — agent processed synchronously, order_id is set.
        ``"no_action"`` — agent ran but did not create an order.
        ``"queued"``    — enable_event_queue is True; processed async.
    """

    status: str | None = None
    event_id: str | None = None
    order_id: str | None = None
    root_agent_response: str | None = None
    order_request: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "AgentOrderCreateResponse":
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
class AgentOrderCloseResponse:
    """Response from POST /orders/close.

    status values: ``"closed"`` | ``"queued"``
    """

    status: str | None = None
    event_id: str | None = None
    root_agent_response: str | None = None
    order_request: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "AgentOrderCloseResponse":
        known = {"status", "event_id", "root_agent_response", "order_request"}
        return cls(
            status=d.get("status"),
            event_id=d.get("event_id"),
            root_agent_response=d.get("root_agent_response"),
            order_request=d.get("order_request", {}),
            extra={k: v for k, v in d.items() if k not in known},
        )
