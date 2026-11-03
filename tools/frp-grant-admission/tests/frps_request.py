"""Requests shaped as frps's server-plugin protocol sends them.

frps posts `{"version": "0.1.0", "op": ..., "content": {...}}` to the plugin's path
with `?version=0.1.0&op=<op>` appended. A `NewProxy`'s content carries the client's
login as `user` — with the client-wide metadata as `user.metas` — beside the proxy's
name, type, remote port, and its own metadata as `metas`.
"""

from __future__ import annotations

from typing import Any

from tests.vector_builder import PORT, claims, header, sign

PATH = "/?version=0.1.0&op=NewProxy"
GRANT = sign(header(), claims())


def new_proxy(**content: Any) -> dict[str, Any]:
    """A `NewProxy` request for `PORT` carrying `GRANT`; a value of `None` removes a field."""
    fields: dict[str, Any] = {
        "user": {"user": "host-1", "metas": {}, "run_id": "0123456789abcdef"},
        "proxy_name": "host-1.guest-17",
        "proxy_type": "tcp",
        "remote_port": PORT,
        "metas": {"grant": GRANT},
    }
    fields.update(content)
    return {
        "version": "0.1.0",
        "op": "NewProxy",
        "content": {name: value for name, value in fields.items() if value is not None},
    }
