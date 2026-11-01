"""The plugin's real HTTP server, in-process on an ephemeral loopback port.

The caller is frps, so there is no typed client: each test posts a body shaped as
frps's server-plugin protocol sends it, and frps's protocol is the contract. The
clock is fixed, so grants replay at the vector's time. Waits observe the log or the
answer within a bound, never a sleep.
"""

from __future__ import annotations

import http.client
import json
import os
import signal
import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pytest

from frp_grant_admission.config import load_config
from frp_grant_admission.decision_log import DecisionLog
from frp_grant_admission.request import MAX_BODY_BYTES
from frp_grant_admission.server import (
    SOCKET_TIMEOUT_SECONDS,
    Plugin,
    PluginServer,
    install_reload_on_sighup,
)
from tests.frps_request import GRANT, PATH, new_proxy
from tests.rfc8032 import TEST_1, TEST_2, TEST_3
from tests.vector_builder import AUDIENCE, NOW, PORT, claims, forged, header, sign

WAIT_SECONDS = 5


def configuration(*, listen: str = "127.0.0.1:7300", site_b: bool = False) -> str:
    """Issuer A always; issuer B, with TEST 3's key, when asked. RFC 8032 test keys only."""
    text = (
        f'listen = "{listen}"\n\n[[issuers]]\nname = "issuer-a"\naudience = "{AUDIENCE}"\n'
        "ports = { start = 6100, end = 6199 }\n"
        f'keys = [ {{ public_key = "{TEST_1.spki_base64}" }}, '
        f'{{ public_key = "{TEST_2.spki_base64}" }} ]\n'
    )
    if site_b:
        text += (
            f'\n[[issuers]]\nname = "issuer-b"\naudience = "{AUDIENCE}"\n'
            "ports = { start = 6200, end = 6249 }\n"
            f'keys = [ {{ public_key = "{TEST_3.spki_base64}" }} ]\n'
        )
    return text


class LogLines:
    """A stream the plugin logs to, whose lines a test can wait for."""

    def __init__(self) -> None:
        self._text = ""
        self._changed = threading.Condition()

    def write(self, text: str) -> int:
        with self._changed:
            self._text += text
            self._changed.notify_all()
        return len(text)

    def flush(self) -> None:
        pass

    @property
    def raw(self) -> str:
        with self._changed:
            return self._text

    def lines(self) -> list[dict[str, Any]]:
        return [json.loads(line) for line in self.raw.splitlines()]

    def wait_for(self, predicate: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
        """The first line matching `predicate`, waiting up to `WAIT_SECONDS` for it."""
        found: list[dict[str, Any]] = []

        def matched() -> bool:
            found[:] = [line for line in self.lines() if predicate(line)]
            return bool(found)

        with self._changed:
            assert self._changed.wait_for(matched, timeout=WAIT_SECONDS), self._text
        return found[0]


@dataclass
class RunningPlugin:
    config_path: Path
    log: LogLines
    port: int
    host: str = "127.0.0.1"

    def post(self, body: bytes, path: str = PATH) -> tuple[int, bytes]:
        connection = http.client.HTTPConnection(self.host, self.port, timeout=WAIT_SECONDS)
        try:
            connection.request(
                "POST", path, body=body, headers={"Content-Type": "application/json"}
            )
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def new_proxy(self, **content: Any) -> dict[str, Any]:
        status, body = self.post(json.dumps(new_proxy(**content)).encode())
        assert status == 200
        return json.loads(body)

    def reload(self, text: str) -> None:
        self.config_path.write_text(text)
        os.kill(os.getpid(), signal.SIGHUP)


@contextmanager
def running_plugin(
    tmp_path: Path, host: str = "127.0.0.1", socket_timeout: float = SOCKET_TIMEOUT_SECONDS
) -> Iterator[RunningPlugin]:
    config_path = tmp_path / "config.toml"
    config_path.write_text(configuration())
    log = LogLines()
    running = Plugin(load_config(config_path), config_path, DecisionLog(log), clock=lambda: NOW)
    server = PluginServer((host, 0), running, socket_timeout=socket_timeout)
    previous = install_reload_on_sighup(running)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield RunningPlugin(config_path, log, server.server_address[1], host)
    finally:
        signal.signal(signal.SIGHUP, previous)
        server.shutdown()
        server.server_close()
        thread.join(WAIT_SECONDS)


@pytest.fixture
def plugin(tmp_path: Path) -> Iterator[RunningPlugin]:
    with running_plugin(tmp_path) as running:
        yield running


def ipv6_loopback_available() -> bool:
    if not socket.has_ipv6:
        return False
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as probe:
            probe.bind(("::1", 0))
    except OSError:
        return False
    return True


def test_a_valid_grant_is_admitted_and_logged_verified(plugin: RunningPlugin) -> None:
    assert plugin.new_proxy() == {"reject": False, "unchange": True}

    line = plugin.log.wait_for(lambda line: line["event"] == "admit")
    assert line["proxy"] == "host-1.guest-17"
    assert line["remote_port"] == PORT
    assert line["issuer"] == "issuer-a"
    assert line["verified"] is True
    assert GRANT not in plugin.log.raw


def test_a_forged_grant_is_refused_and_neither_reply_nor_log_carries_it(
    plugin: RunningPlugin,
) -> None:
    grant = forged(header(), claims())

    answer = plugin.new_proxy(metas={"grant": grant})

    assert answer["reject"] is True
    assert answer["reject_reason"].startswith("signature_invalid: ")
    line = plugin.log.wait_for(lambda line: line["event"] == "refuse")
    assert line["reason"] == "signature_invalid"
    assert line["verified"] is False
    for segment in grant.split("."):
        assert segment not in plugin.log.raw
        assert segment not in json.dumps(answer)


def test_a_body_over_64_kib_is_refused(plugin: RunningPlugin) -> None:
    status, body = plugin.post(b" " * (MAX_BODY_BYTES + 1))

    assert status == 200
    assert json.loads(body)["reject_reason"].startswith("malformed_request: ")


def test_a_body_that_is_not_json_is_refused(plugin: RunningPlugin) -> None:
    status, body = plugin.post(b"{not json")

    assert status == 200
    assert json.loads(body)["reject_reason"].startswith("malformed_request: ")
    assert plugin.log.wait_for(lambda line: line["event"] == "refuse")["reason"] == (
        "malformed_request"
    )


def raw_exchange(port: int, request: bytes) -> bytes:
    """Send `request` as written and read the reply until the server closes."""
    with socket.create_connection(("127.0.0.1", port), timeout=WAIT_SECONDS) as raw:
        raw.sendall(request)
        reply = b""
        while chunk := raw.recv(4096):
            reply += chunk
    return reply


def test_a_body_without_a_length_is_refused(plugin: RunningPlugin) -> None:
    reply = raw_exchange(plugin.port, f"POST {PATH} HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n".encode())

    assert reply.startswith(b"HTTP/1.0 200")
    assert b'"reject_reason": "malformed_request: ' in reply
    assert plugin.log.wait_for(lambda line: line["event"] == "refuse")["reason"] == (
        "malformed_request"
    )


def test_a_body_not_sent_within_the_socket_timeout_is_refused(tmp_path: Path) -> None:
    # A short timeout keeps the test fast; the server's default is five seconds.
    with running_plugin(tmp_path, socket_timeout=0.2) as plugin:
        head = f"POST {PATH} HTTP/1.0\r\nHost: 127.0.0.1\r\nContent-Length: 100\r\n\r\n"

        reply = raw_exchange(plugin.port, head.encode() + b'{"op":')

        assert b'"reject_reason": "malformed_request: ' in reply
        assert plugin.log.wait_for(lambda line: line["event"] == "refuse")["reason"] == (
            "malformed_request"
        )


@pytest.mark.skipif(not ipv6_loopback_available(), reason="no IPv6 loopback here")
def test_the_ipv6_loopback_is_served(tmp_path: Path) -> None:
    with running_plugin(tmp_path, host="::1") as plugin:
        assert plugin.new_proxy() == {"reject": False, "unchange": True}


def test_a_get_is_not_answered_as_an_admission(plugin: RunningPlugin) -> None:
    connection = http.client.HTTPConnection("127.0.0.1", plugin.port, timeout=WAIT_SECONDS)
    try:
        connection.request("GET", PATH)
        response = connection.getresponse()
        body = response.read()
    finally:
        connection.close()

    assert response.status != 200
    assert b'"reject": false' not in body


def test_another_path_is_not_answered(plugin: RunningPlugin) -> None:
    status, _ = plugin.post(json.dumps(new_proxy()).encode(), path="/handler")

    assert status == 404


def test_an_issuer_added_by_reload_is_admitted_without_a_restart(plugin: RunningPlugin) -> None:
    grant = sign(header(TEST_3), claims(port=6201), key=TEST_3)
    assert plugin.new_proxy(remote_port=6201, metas={"grant": grant})["reject"] is True

    plugin.reload(configuration(site_b=True))

    line = plugin.log.wait_for(
        lambda line: line["event"] == "config_loaded" and line["trigger"] == "reload"
    )
    assert [issuer["name"] for issuer in line["issuers"]] == ["issuer-a", "issuer-b"]
    assert plugin.new_proxy(remote_port=6201, metas={"grant": grant}) == {
        "reject": False,
        "unchange": True,
    }


def test_an_invalid_reload_keeps_the_running_configuration(plugin: RunningPlugin) -> None:
    broken = configuration(site_b=True).replace("start = 6200", "start = 6150")

    plugin.reload(broken.replace('listen = "127.0.0.1:7300"', 'listen = "localhost:7300"'))

    line = plugin.log.wait_for(lambda line: line["event"] == "config_refused")
    assert line["trigger"] == "reload"
    assert len(line["problems"]) == 2
    assert any("overlap" in problem for problem in line["problems"])
    assert any("hostnames are refused" in problem for problem in line["problems"])
    assert plugin.new_proxy() == {"reject": False, "unchange": True}


def test_a_reload_changing_listen_keeps_the_bound_address(plugin: RunningPlugin) -> None:
    plugin.reload(configuration(listen="127.0.0.1:7301", site_b=True))

    line = plugin.log.wait_for(
        lambda line: line["event"] == "config_loaded" and line["trigger"] == "reload"
    )
    assert line["listen"] == "127.0.0.1:7300"
    assert line["listen_at_restart"] == "127.0.0.1:7301"
    assert len(line["issuers"]) == 2
    assert plugin.new_proxy() == {"reject": False, "unchange": True}
