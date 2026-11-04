"""Deciding one frps `NewProxy` request: the request's own checks, then the grant's.

frps sends a server plugin `{"version": ..., "op": ..., "content": {...}}`, where a
`NewProxy`'s content carries the proxy's name, type, group, remote port, and its own
metadata as `metas`, beside the client's login (`user`, with the client-wide
metadata as `user.metas`). The checks run in a fixed order and the first that fails
decides the refusal:

1. the body is a JSON object whose `op` is `NewProxy`;
2. `proxy_type` is exactly `tcp`;
3. `group` is absent or empty, so frps's one proxy per remote port holds;
4. `remote_port` is an integer from 1 to 65535 — port 0, which asks frps to choose a
   port, is refused, since a grant names one port;
5. the proxy's own `metas.grant` carries a grant, which `grant.check_grant` decides.

The client-wide `user.metas` is never read: a grant there would be sent once at login
and could not change without ending every proxy the client carries.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from frp_grant_admission.config import Config
from frp_grant_admission.grant import GrantResult, check_grant
from frp_grant_admission.reasons import Reason

MAX_BODY_BYTES = 64 * 1024
SUPPORTED_OP = "NewProxy"
ALLOWED_PROXY_TYPE = "tcp"


@dataclass(frozen=True)
class Decision:
    """A request's verdict, with what the request named for the decision log.

    `proxy`, `proxy_type`, and `remote_port` are the request's values as sent, or
    `None` where it sent none; `grant` is the grant check's result once one was read.
    """

    reason: Reason | None
    proxy: object = None
    proxy_type: object = None
    remote_port: object = None
    grant: GrantResult | None = None

    @property
    def admitted(self) -> bool:
        return self.reason is None

    def answer(self) -> dict[str, object]:
        """The body frps expects: an admission never rewrites the proxy."""
        if self.reason is None:
            return {"reject": False, "unchange": True}
        return {"reject": True, "reject_reason": self.reason.reply}


def decide_body(body: bytes, config: Config, now: int) -> Decision:
    """Decide a request from its raw body."""
    if len(body) > MAX_BODY_BYTES:
        return Decision(Reason.MALFORMED_REQUEST)
    try:
        request = json.loads(body)
    except (ValueError, RecursionError):
        return Decision(Reason.MALFORMED_REQUEST)
    return decide_request(request, config, now)


def decide_request(request: object, config: Config, now: int) -> Decision:
    """Decide a parsed request at `now` (Unix seconds) under `config`."""
    if not isinstance(request, dict) or not isinstance(request.get("op"), str):
        return Decision(Reason.MALFORMED_REQUEST)
    if request["op"] != SUPPORTED_OP:
        return Decision(Reason.OPERATION_NOT_SUPPORTED)
    content = request.get("content")
    if not isinstance(content, dict):
        return Decision(Reason.MALFORMED_REQUEST)

    named = {
        "proxy": content.get("proxy_name"),
        "proxy_type": content.get("proxy_type"),
        "remote_port": content.get("remote_port"),
    }
    if content.get("proxy_type") != ALLOWED_PROXY_TYPE:
        return Decision(Reason.PROXY_TYPE_NOT_ALLOWED, **named)
    if content.get("group") not in (None, ""):
        return Decision(Reason.GROUP_NOT_ALLOWED, **named)
    port = content.get("remote_port")
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        return Decision(Reason.PORT_INVALID, **named)

    metas = content.get("metas")
    grant = metas.get("grant") if isinstance(metas, dict) else None
    if grant is None or grant == "":
        return Decision(Reason.GRANT_MISSING, **named)
    if not isinstance(grant, str):
        return Decision(Reason.GRANT_MALFORMED, **named)
    result = check_grant(grant, config, port, now)
    return Decision(result.reason, grant=result, **named)
