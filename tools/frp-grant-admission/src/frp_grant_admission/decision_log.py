"""The plugin's log: one JSON line per decision and per configuration load.

A decision line names the proxy, its type and remote port, and what the grant named —
its issuer where known, `kid`, `sub`, `jti`, and `exp` where present — with
`verified` saying whether those values passed the signature and claim checks. On a
forged or malformed grant they are whatever the sender wrote; JSON encoding keeps
them from forging a line. The grant itself is never written: a valid grant is a
bearer credential for its port until it expires. Nor is any of the request's
metadata, which the client chose.

Lines are strict JSON in ASCII, one per write, and written under a lock, so lines
from concurrent requests never interleave. The lock is reentrant because a reload
runs in a SIGHUP handler, and a second SIGHUP arriving while a reload writes its line
must not deadlock the main thread on its own lock. A number JSON cannot carry — a
`NaN` or an overflowing exponent the sender wrote — is logged as Python writes it,
`"nan"` or `"inf"`, and a value nested too deeply to walk as a placeholder, so every
decision still gets its line.
"""

from __future__ import annotations

import json
import math
import sys
import threading
import time
from typing import Any, TextIO

from frp_grant_admission.config import Config, ListenAddress
from frp_grant_admission.request import Decision


def timestamp(now: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))


TOO_DEEP = "<nested too deeply to log>"


def _loggable(line: dict[str, Any]) -> dict[str, Any]:
    """`line` with non-finite floats as text and over-deep values as a placeholder.

    The JSON parser accepts deeper nesting than a Python recursion can walk, so a
    field the walk cannot finish is replaced rather than losing the line.
    """
    loggable = {}
    for name, value in line.items():
        try:
            loggable[name] = _finite(value)
        except RecursionError:
            loggable[name] = TOO_DEEP
    return loggable


def _finite(value: Any) -> Any:
    """`value` with every non-finite float replaced by its text."""
    if isinstance(value, float) and not math.isfinite(value):
        return repr(value)
    if isinstance(value, dict):
        return {name: _finite(member) for name, member in value.items()}
    if isinstance(value, list):
        return [_finite(member) for member in value]
    return value


class DecisionLog:
    """Writes the plugin's JSON lines to a stream, stderr unless one is given."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream
        self._lock = threading.RLock()

    def decision(self, decision: Decision, now: int) -> None:
        grant = decision.grant
        line: dict[str, Any] = {
            "ts": timestamp(now),
            "event": "admit" if decision.admitted else "refuse",
        }
        if decision.reason is not None:
            line["reason"] = decision.reason.code
        line.update(
            {
                "proxy": decision.proxy,
                "type": decision.proxy_type,
                "remote_port": decision.remote_port,
            }
        )
        if grant is not None:
            line.update(
                {
                    "issuer": grant.issuer,
                    "kid": grant.kid,
                    "sub": grant.sub,
                    "jti": grant.jti,
                    "exp": grant.exp,
                }
            )
        line = {name: value for name, value in line.items() if value is not None}
        line["verified"] = grant is not None and grant.verified
        self._write(line)

    def config_loaded(
        self,
        config: Config,
        trigger: str,
        now: int,
        bound: ListenAddress | None = None,
    ) -> None:
        """A configuration now in force; `trigger` is `startup` or `reload`.

        `bound` is the address the plugin listens on, bound at startup. A reloaded
        configuration naming another address is in force but for its listen
        address, which takes effect only when the plugin restarts and binds again.
        """
        line: dict[str, Any] = {
            "ts": timestamp(now),
            "event": "config_loaded",
            "trigger": trigger,
            "listen": str(config.listen),
            "issuers": [
                {
                    "name": issuer.name,
                    "audience": issuer.audience,
                    "ports": {"start": issuer.port_start, "end": issuer.port_end},
                    "keys": list(issuer.kids),
                }
                for issuer in config.issuers
            ],
        }
        if bound is not None and bound != config.listen:
            line["listen"] = str(bound)
            line["listen_at_restart"] = str(config.listen)
        self._write(line)

    def config_refused(self, problems: tuple[str, ...], trigger: str, now: int) -> None:
        """A configuration that did not load; on reload the running one stays."""
        line = {
            "ts": timestamp(now),
            "event": "config_refused",
            "trigger": trigger,
            "problems": list(problems),
        }
        if trigger == "reload":
            line["kept"] = "the running configuration"
        self._write(line)

    def _write(self, line: dict[str, Any]) -> None:
        text = json.dumps(
            _loggable(line), ensure_ascii=True, allow_nan=False, separators=(",", ":")
        ) + "\n"
        stream = self._stream if self._stream is not None else sys.stderr
        with self._lock:
            stream.write(text)
            stream.flush()
