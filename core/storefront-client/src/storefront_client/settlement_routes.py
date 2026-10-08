"""The route contract for the storefront settlement routes.

Each route's method, path, signed operation, the resource a request binds, and
the caller role it admits are declared once here. The typed client builds its
requests from these declarations and every storefront's authentication binds
incoming requests through `bind_settlement_route`, so the two cannot disagree.

The resource is the identifier the path carries: an escrow UID for an EVM
settlement, a negotiation ID for a mechanism that settles from the Agreement.
It is one path segment, so it may not be empty or contain ``/``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

Role = Literal["buyer", "seller"]


class SettlementRouteError(ValueError):
    """An identifier that cannot be one path segment."""


@dataclass(frozen=True)
class SettlementRoute:
    method: str
    prefix: str
    suffix: str
    operation: str
    role: Role

    @property
    def template(self) -> str:
        """The path with its identifier as a FastAPI path parameter."""
        return f"{self.prefix}{{identifier}}{self.suffix}"

    def path(self, identifier: str) -> str:
        """The request path for one settlement identifier."""
        return f"{self.prefix}{_segment(identifier)}{self.suffix}"

    def resource(self, method: str, path: str) -> str | None:
        """The resource a request to this route binds, or None for another route."""
        path = path.rstrip("/")
        if method.upper() != self.method or not path.startswith(self.prefix):
            return None
        if not path.endswith(self.suffix):
            return None
        identifier = path[len(self.prefix) : len(path) - len(self.suffix)]
        if not identifier or "/" in identifier:
            return None
        return identifier


def _segment(identifier: str) -> str:
    if not isinstance(identifier, str) or not identifier or "/" in identifier:
        raise SettlementRouteError("a settlement identifier must be one non-empty path segment")
    return identifier


#: Settle a deal: an escrow UID for an EVM mechanism, else the negotiation ID.
SETTLE = SettlementRoute("POST", "/api/v1/settle/", "", "settle_escrow", "buyer")
#: Read a settlement's status.
SETTLE_STATUS = SettlementRoute("GET", "/api/v1/settle/", "/status", "settle_status", "buyer")
#: The seller reverses a deal's still-held payment.
REFUND = SettlementRoute("POST", "/api/v1/settlements/", "/refund", "refund_settlement", "seller")

SETTLEMENT_ROUTES: tuple[SettlementRoute, ...] = (SETTLE, SETTLE_STATUS, REFUND)


@dataclass(frozen=True)
class SettlementRouteBinding:
    route: SettlementRoute
    resource: str


def bind_settlement_route(method: str, path: str) -> SettlementRouteBinding | None:
    """Bind a request to exactly one settlement route, or None if it is not one."""
    matches = [
        SettlementRouteBinding(route, resource)
        for route in SETTLEMENT_ROUTES
        if (resource := route.resource(method, path)) is not None
    ]
    if len(matches) > 1:
        raise SettlementRouteError(f"{method} {path} matches more than one settlement route")
    return matches[0] if matches else None



def unmounted_settlement_routes(mounted: Iterable[tuple[str, str]]) -> list[SettlementRoute]:
    """The settlement routes a storefront does not mount.

    ``mounted`` is the storefront's ``(method, path template)`` pairs. A route
    counts as mounted only at its own method and at a path it binds.
    """
    found = set()
    for method, template in mounted:
        path = re.sub(r"\{[^}/]+\}", "identifier", template)
        binding = bind_settlement_route(method, path)
        if binding is not None:
            found.add(binding.route)
    return [route for route in SETTLEMENT_ROUTES if route not in found]

__all__ = [
    "REFUND",
    "SETTLE",
    "SETTLEMENT_ROUTES",
    "SETTLE_STATUS",
    "SettlementRoute",
    "SettlementRouteBinding",
    "SettlementRouteError",
    "bind_settlement_route",
    "unmounted_settlement_routes",
]
