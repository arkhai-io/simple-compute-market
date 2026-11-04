"""The HTTP endpoint frps calls, and the configuration it decides under.

frps posts each `NewProxy` to the plugin and refuses the proxy unless the plugin
answers HTTP 200 with an admission, so any failure here — a crash, a timeout, a body
frps cannot read — fails closed. The server answers `POST /` only, on the loopback
address it was given; on a reachable port every decision could be probed, and a slow
body could hold a thread, since the socket timeout bounds each wait for its next
bytes rather than the whole body.

The plugin holds no state across requests beyond its configuration, which a reload
replaces in one reference assignment. A request reads the reference once, so it
finishes under the configuration it started with, and nothing else is shared.
"""

from __future__ import annotations

import json
import signal
import socket
import socketserver
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from frp_grant_admission.config import Config, ConfigError, load_config
from frp_grant_admission.decision_log import DecisionLog
from frp_grant_admission.reasons import Reason
from frp_grant_admission.request import MAX_BODY_BYTES, Decision, decide_body

SOCKET_TIMEOUT_SECONDS = 5


class Plugin:
    """The configuration in force, how to reload it, and the clock decisions use."""

    def __init__(
        self,
        config: Config,
        config_path: str | Path,
        log: DecisionLog,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._config = config
        self._config_path = Path(config_path)
        self._bound = config.listen
        self.log = log
        self._clock = clock

    @property
    def config(self) -> Config:
        return self._config

    def now(self) -> int:
        """The clock in whole Unix seconds; a grant is expired from the second of `exp`."""
        return int(self._clock())

    def decide(self, body: bytes) -> Decision:
        config = self._config
        now = self.now()
        decision = decide_body(body, config, now)
        self.log.decision(decision, now)
        return decision

    def refuse(self, reason: Reason) -> Decision:
        """A refusal decided before the body could be read."""
        decision = Decision(reason)
        self.log.decision(decision, self.now())
        return decision

    def reload(self) -> bool:
        """Re-read the file; replace the configuration only if it loads."""
        try:
            config = load_config(self._config_path)
        except ConfigError as error:
            self.log.config_refused(error.problems, "reload", self.now())
            return False
        except Exception as error:
            # Whatever the file does to the loader, the running configuration stays.
            self.log.config_refused((f"cannot load: {error!r}",), "reload", self.now())
            return False
        self._config = config
        self.log.config_loaded(config, "reload", self.now(), bound=self._bound)
        return True


class _Handler(BaseHTTPRequestHandler):
    server: PluginServer

    def setup(self) -> None:
        self.timeout = self.server.socket_timeout
        super().setup()

    def do_POST(self) -> None:
        if urlsplit(self.path).path != "/":
            self.send_error(404)
            return
        plugin = self.server.plugin
        body = self._read_body()
        decision = plugin.refuse(Reason.MALFORMED_REQUEST) if body is None else plugin.decide(body)
        self._answer(decision)

    def _read_body(self) -> bytes | None:
        """The body, or None when it is missing, over the cap, or not sent in time."""
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return None
        if length < 0:
            return None
        try:
            # Reading at most one byte past the cap bounds memory whatever the
            # declared length; a body that long is refused.
            body = self.rfile.read(min(length, MAX_BODY_BYTES + 1))
        except OSError:
            # The socket timeout included: a body whose next bytes do not arrive
            # within it is refused. It bounds each wait, not the whole body.
            return None
        if len(body) != length or len(body) > MAX_BODY_BYTES:
            return None
        return body

    def _answer(self, decision: Decision) -> None:
        payload = json.dumps(decision.answer()).encode("utf-8")
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except OSError:
            # frps has gone; it refuses a proxy it heard no admission for.
            pass

    def log_message(self, format: str, *args: object) -> None:
        # The plugin's stderr carries its JSON lines, not an access log.
        pass


class PluginServer(ThreadingHTTPServer):
    """A threading HTTP server answering frps for one `Plugin`.

    `address` is an IPv4 address or `::1` and a port; the socket's family follows it.
    """

    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        plugin: Plugin,
        socket_timeout: float = SOCKET_TIMEOUT_SECONDS,
    ) -> None:
        self.plugin = plugin
        self.socket_timeout = socket_timeout
        self.address_family = socket.AF_INET6 if ":" in address[0] else socket.AF_INET
        super().__init__(address, _Handler)

    def server_bind(self) -> None:
        # HTTPServer.server_bind would look the host's name up for CGI variables
        # nothing here reads; the plugin makes no lookup and no outbound call.
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = host
        self.server_port = port


def install_reload_on_sighup(plugin: Plugin) -> Callable[..., object] | int | None:
    """Reload `plugin` on SIGHUP; returns the handler it replaced.

    Python runs the handler in the main thread, which otherwise only serves the
    listening socket, so the one write it can interrupt there is another reload's,
    when a second SIGHUP arrives during a reload. The log's lock is reentrant, so
    that never deadlocks; whatever the nested write raises is caught below.
    """

    def reload(_signum: int, _frame: object) -> None:
        try:
            plugin.reload()
        except Exception:
            # An exception leaving a signal handler would end serve_forever, and a
            # failed reload must leave the plugin serving what it served before.
            traceback.print_exc()

    return signal.signal(signal.SIGHUP, reload)
