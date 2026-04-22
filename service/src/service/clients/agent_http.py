"""HTTP transport for agent-to-agent messages.

Replaces A2A for the /negotiation/* and /settlement/* message paths. Each
send is a plain `POST {peer_url}/{path}` with a JSON envelope body.
Non-2xx responses and connect failures raise; the caller decides whether
to retry or swallow.

The sync-vs-async dispatch split matters when an outbound send is
triggered from inside an inbound request handler: awaiting a synchronous
send there deadlocks if the peer tries to await a response from us in
the same handler. `send_and_forget` schedules the send on the event loop
and returns immediately — same pattern as the old `_background_send`.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)


# Tight default: agent-to-agent messages should respond in seconds, not
# minutes. Long-running work (provisioning, on-chain waits) is kicked off
# as a local background task and responded to via a follow-up message.
_DEFAULT_TIMEOUT_SECONDS = 30.0


class AgentDispatchError(RuntimeError):
    """Raised when an outbound agent-to-agent send fails."""


async def send_message(
    *,
    peer_url: str,
    path: str,
    envelope: dict[str, Any],
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """POST `envelope` to `peer_url + path`; return the peer's JSON response.

    Raises AgentDispatchError on network failure, non-2xx, or non-JSON body.
    """
    if not peer_url:
        raise AgentDispatchError("peer_url is required")
    if not path.startswith("/"):
        path = "/" + path
    url = peer_url.rstrip("/") + path

    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=envelope) as resp:
                # Read the body regardless of status so 4xx responses are
                # still surfaced with their detail rather than a bare status.
                text = await resp.text()
                if resp.status >= 400:
                    raise AgentDispatchError(
                        f"POST {url} -> HTTP {resp.status}: {text[:500]}"
                    )
                if not text:
                    return {}
                try:
                    import json
                    return json.loads(text)
                except ValueError as exc:
                    raise AgentDispatchError(
                        f"POST {url} returned non-JSON body: {text[:200]!r}"
                    ) from exc
    except aiohttp.ClientError as exc:
        raise AgentDispatchError(f"POST {url} failed: {exc}") from exc


def send_and_forget(
    *,
    peer_url: str,
    path: str,
    envelope: dict[str, Any],
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
) -> None:
    """Fire-and-forget: schedule `send_message` on the current loop.

    Use from inside an inbound request handler when you just want to
    push a notification (fulfillment_failed, arbitration_complete, etc.)
    and don't block the handler on the peer's round trip. Errors are
    logged, not raised — the caller is already halfway through another
    request by the time the send resolves.
    """
    async def _send() -> None:
        try:
            await send_message(
                peer_url=peer_url,
                path=path,
                envelope=envelope,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:  # AgentDispatchError or cancellation
            logger.warning("[AGENT_HTTP] fire-and-forget %s%s failed: %s",
                           peer_url, path, exc)

    asyncio.create_task(_send())


__all__ = ["AgentDispatchError", "send_message", "send_and_forget"]
