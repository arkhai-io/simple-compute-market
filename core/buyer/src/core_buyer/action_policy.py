"""Mechanism-neutral handling for transient buyer settlement actions."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

ACTION_REQUIRED_EXIT_CODE = 8


class BuyerActionPolicy(str, Enum):
    """How a normal buyer command handles one transient public action."""

    OPEN = "open"
    PRINT = "print"
    FAIL = "fail"


@dataclass(frozen=True, slots=True)
class BuyerActionMetadata:
    """Durable allowlist for an action; intentionally excludes its URL."""

    kind: str | None
    expires_at_unix: int | None

    def as_event(self) -> dict[str, str | int | None]:
        return {
            "action_kind": self.kind,
            "action_expires_at_unix": self.expires_at_unix,
        }


class BuyerActionRequired(RuntimeError):
    """Raised when accepted state needs an action forbidden by policy."""

    def __init__(self, metadata: BuyerActionMetadata) -> None:
        self.metadata = metadata
        super().__init__(
            "buyer action required; rerun with --action open or --action print"
        )


def resolve_buyer_action_policy(
    requested: BuyerActionPolicy | str | None,
    *,
    interactive: bool,
) -> BuyerActionPolicy:
    """Resolve the explicit policy or the terminal-sensitive safe default."""

    if requested is None:
        return BuyerActionPolicy.OPEN if interactive else BuyerActionPolicy.PRINT
    return BuyerActionPolicy(requested)


@dataclass(slots=True)
class BuyerActionHandler:
    """Apply one policy while deduplicating repeated transient actions in memory."""

    policy: BuyerActionPolicy
    open_url: Callable[[str], Any] | None = None
    print_url: Callable[[str], Any] | None = None
    on_required: Callable[[BuyerActionMetadata], Any] | None = None
    _seen: set[tuple[str | None, int | None, bytes]] = field(
        default_factory=set,
        init=False,
        repr=False,
    )

    def handle(self, action: Mapping[str, Any]) -> BuyerActionMetadata | None:
        """Handle a URL-bearing action without returning or persisting the URL."""

        url = action.get("url")
        if not isinstance(url, str) or not url:
            return None
        kind_value = action.get("kind")
        kind = kind_value if isinstance(kind_value, str) and kind_value else None
        expiry_value = action.get("expires_at_unix")
        expiry = expiry_value if isinstance(expiry_value, int) else None
        marker = (kind, expiry, hashlib.sha256(url.encode("utf-8")).digest())
        if marker in self._seen:
            return BuyerActionMetadata(kind=kind, expires_at_unix=expiry)
        self._seen.add(marker)

        metadata = BuyerActionMetadata(kind=kind, expires_at_unix=expiry)
        if self.on_required is not None:
            self.on_required(metadata)

        if self.policy is BuyerActionPolicy.FAIL:
            raise BuyerActionRequired(metadata)
        if self.policy is BuyerActionPolicy.OPEN:
            if self.open_url is None:
                raise RuntimeError("buyer action policy open has no URL opener")
            self.open_url(url)
        else:
            if self.print_url is None:
                raise RuntimeError("buyer action policy print has no URL printer")
            self.print_url(url)
        return metadata
