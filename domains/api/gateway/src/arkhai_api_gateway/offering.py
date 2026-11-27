"""The one value a gateway is configured with, so it learns no domain's listing schema."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from arkhai_api_gate import GateConfig, PurchasePointer


@dataclass(frozen=True, kw_only=True)
class GatewayOffering:
    """What one gateway deployment serves and how it charges.

    ``service`` is the only model admitted and listed. ``default_charge``
    applies only when a key's verification pins no charge of its own.
    """

    service: str
    scope_service: str | None
    scope_resource_id: str | None
    default_charge: int
    purchase: PurchasePointer
    upstream_base_url: str
    upstream_credential_file: Path | None = None
    # A mapping is unhashable, so the terms are left out of the offering's hash.
    current_terms: Mapping[str, Any] | None = field(default=None, hash=False)

    def __post_init__(self) -> None:
        if not self.service:
            raise ValueError("a gateway offering names the service it admits")
        if self.default_charge < 0:
            raise ValueError("a gateway offering's default charge is non-negative")
        # A half-set or empty scope passes here but no scoped authority could
        # ever accept it.
        scope = (self.scope_service, self.scope_resource_id)
        if "" in scope or (scope[0] is None) != (scope[1] is None):
            raise ValueError("a gateway offering scopes both service and resource, or neither")
        _check_upstream_base_url(self.upstream_base_url)

    def gate_config(self, base: GateConfig) -> GateConfig:
        """``base`` with this offering's scope, default charge, and purchase pointer.

        Deriving it from the offering keeps the gate's scope and fallback charge
        from diverging from what the gateway admits.
        """
        return dataclasses.replace(
            base,
            scope_service=self.scope_service,
            scope_resource_id=self.scope_resource_id,
            amount_per_request=self.default_charge,
            purchase=self.purchase,
        )


def _check_upstream_base_url(url: str) -> None:
    """Refuse a base URL every forward would fail on, before any buyer is charged.

    Userinfo is refused because the upstream credential comes from its own file.
    """
    try:
        parts = urlsplit(url)
        parts.port  # noqa: B018 - raises on a malformed port
    except ValueError as exc:
        raise ValueError("the upstream base URL is malformed") from exc
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("the upstream base URL must be an absolute http or https URL")
    if "@" in parts.netloc:
        raise ValueError("the upstream base URL must not carry credentials")
    if "?" in url or "#" in url:
        raise ValueError("the upstream base URL must not carry a query or fragment")


def read_upstream_credential(path: Path) -> str:
    """The credential in a mounted secret file, stripped.

    Its mode is not checked, since mounted secrets are routinely group-readable.
    """
    try:
        if not path.is_file():
            raise ValueError("the upstream credential file must be a regular file")
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ValueError("the upstream credential file cannot be read") from exc
    if not value:
        raise ValueError("the upstream credential file is empty")
    return value
