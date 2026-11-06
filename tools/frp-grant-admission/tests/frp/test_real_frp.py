"""The plugin behind real frps, registering proxies from real frpc.

What these tests prove is frps's behaviour with the plugin, which an answer from the
plugin alone cannot show: that a refusal reaches frpc with its reason, that frps
fails closed whenever the plugin does not admit, that frpc's own retry admits a
refused proxy once the plugin admits, that frps does not recheck a registered proxy,
and that an frpc reload registers only what it changed. An admission is proven by
traffic through the remote port as well as by registration. Every verdict and reason
is proven exhaustively by the vector at unit level; here each is one case.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest

from tests.frp.stack import (
    RETRY_WAIT_SECONDS,
    FrpStack,
    Proxy,
    connect,
    exchange,
    grant,
    round_trip,
)
from tests.rfc8032 import TEST_1, TEST_2

PAYLOAD = b"through the relay\n"


def assert_refused(stack: FrpStack, name: str, reason: str, client_status: dict[str, Any]) -> None:
    """frpc shows the plugin's reason, and the plugin logged the same refusal."""
    assert reason in client_status.get("err", ""), client_status
    assert stack.plugin_output is not None
    line = stack.plugin_output.wait_for(lambda line: line.get("proxy") == name)
    assert (line["event"], line["reason"]) == ("refuse", reason)


def test_a_valid_grant_is_admitted_and_carries_traffic(frp_stack: FrpStack) -> None:
    log = frp_stack.start_plugin()
    port = frp_stack.ports.issuer_a[0]

    client = frp_stack.start_frpc([Proxy("valid", port, grant(port))])

    client.wait_for_status("valid", "running")
    assert exchange(port, PAYLOAD) == PAYLOAD
    line = log.wait_for(lambda line: line.get("proxy") == "valid")
    assert (line["event"], line["issuer"], line["verified"]) == ("admit", "issuer-a", True)


REFUSALS = {
    "no-grant": "grant_missing",
    "forged": "signature_invalid",
    "wrong-port": "port_mismatch",
    "wrong-audience": "audience_mismatch",
    "expired": "grant_expired",
    "outside-every-range": "port_outside_range",
    "other-issuers-range": "port_outside_range",
    "stcp": "proxy_type_not_allowed",
}


def refused_proxy(stack: FrpStack, name: str) -> Proxy:
    a, b = stack.ports.issuer_a[0], stack.ports.issuer_b[0]
    outside = stack.ports.outside_every_range
    return {
        "no-grant": Proxy(name, a),
        "forged": Proxy(name, a, grant(a, key=TEST_1, signer=TEST_2)),
        "wrong-port": Proxy(name, a, grant(a + 1)),
        "wrong-audience": Proxy(name, a, grant(a, aud="relay-2")),
        "expired": Proxy(name, a, grant(a, lifetime=-60)),
        "outside-every-range": Proxy(name, outside, grant(outside)),
        "other-issuers-range": Proxy(name, b, grant(b)),
        "stcp": Proxy(name, None, grant(a), type="stcp"),
    }[name]


@pytest.mark.parametrize("name", sorted(REFUSALS))
def test_a_proxy_is_refused_and_frpc_reports_why(frp_stack: FrpStack, name: str) -> None:
    frp_stack.start_plugin()

    client = frp_stack.start_frpc([refused_proxy(frp_stack, name)])

    status = client.wait_for_status(name, "start error")
    assert_refused(frp_stack, name, REFUSALS[name], status)


def test_a_grant_only_in_client_wide_metadata_is_refused(frp_stack: FrpStack) -> None:
    log = frp_stack.start_plugin()
    port = frp_stack.ports.issuer_a[0]

    client = frp_stack.start_frpc([Proxy("client-wide", port)], client_grant=grant(port))

    status = client.wait_for_status("client-wide", "start error")
    assert_refused(frp_stack, "client-wide", "grant_missing", status)
    line = log.wait_for(lambda line: line.get("proxy") == "client-wide")
    assert "kid" not in line and line["verified"] is False


class _StandIn(BaseHTTPRequestHandler):
    """A plugin that answers every request as its server's `answer` says."""

    server: _StandInServer

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.server.received.append(json.loads(body).get("op"))
        if self.server.answer == "500":
            self.send_error(500)
            return
        reply = b"{not json"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(reply)))
        self.end_headers()
        self.wfile.write(reply)

    def log_message(self, format: str, *args: object) -> None:
        pass


class _StandInServer(HTTPServer):
    def __init__(self, port: int, answer: str) -> None:
        self.answer = answer
        self.received: list[str] = []
        super().__init__(("127.0.0.1", port), _StandIn)


@contextmanager
def stand_in(port: int, answer: str) -> Iterator[_StandInServer]:
    server = _StandInServer(port, answer)
    # shutdown() returns only at serve_forever's next poll, and the library
    # has no way to wake it, so the poll is short rather than the default 0.5s.
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.parametrize("failure", ["stopped", "500", "malformed"])
def test_frps_fails_closed_and_frpc_retries_once_the_plugin_answers(
    frp_stack: FrpStack, failure: str
) -> None:
    port = frp_stack.ports.issuer_a[0]
    proxy = Proxy("retried", port, grant(port))

    if failure == "stopped":
        client = frp_stack.start_frpc([proxy])
        client.wait_for_status("retried", "start error")
    else:
        with stand_in(frp_stack.ports.plugin, failure) as server:
            client = frp_stack.start_frpc([proxy])
            client.wait_for_status("retried", "start error")
        assert server.received == ["NewProxy"]
    with pytest.raises(OSError):
        exchange(port, PAYLOAD)

    log = frp_stack.start_plugin()

    client.wait_for_status("retried", "running", seconds=RETRY_WAIT_SECONDS)
    assert client.process.poll() is None and frp_stack.clients == [client]
    assert exchange(port, PAYLOAD) == PAYLOAD
    line = log.wait_for(lambda line: line.get("proxy") == "retried")
    assert line["event"] == "admit"


def test_a_registered_proxy_survives_a_reload_removing_its_key_until_frpc_restarts(
    frp_stack: FrpStack,
) -> None:
    frp_stack.start_plugin()
    port = frp_stack.ports.issuer_a[0]
    client = frp_stack.start_frpc([Proxy("drained", port, grant(port, key=TEST_1))])
    client.wait_for_status("drained", "running")

    with connect(port) as held:
        assert round_trip(held, PAYLOAD) == PAYLOAD
        frp_stack.write_plugin_configuration((TEST_2,))
        reloaded = frp_stack.reload_plugin()

        assert reloaded["event"] == "config_loaded"
        assert round_trip(held, PAYLOAD) == PAYLOAD
    assert client.status("drained")["status"] == "running"
    assert exchange(port, PAYLOAD) == PAYLOAD

    restarted = frp_stack.restart_frpc(client)

    status = restarted.wait_for_status("drained", "start error")
    assert "key_unknown" in status["err"]
    refusals = [line for line in frp_stack.decisions() if line["event"] == "refuse"]
    assert [(line["proxy"], line["reason"]) for line in refusals] == [("drained", "key_unknown")]


def test_an_frpc_reload_adding_a_proxy_causes_exactly_one_decision(frp_stack: FrpStack) -> None:
    log = frp_stack.start_plugin()
    first_port, second_port = frp_stack.ports.issuer_a[0], frp_stack.ports.issuer_a[0] + 1
    first = Proxy("first", first_port, grant(first_port))
    client = frp_stack.start_frpc([first])
    client.wait_for_status("first", "running")
    log.wait_for(lambda line: line.get("proxy") == "first")
    before = len(frp_stack.decisions())

    # The first proxy keeps carrying a connection held across the reload. Its decisions
    # are counted once the second's is logged: frpc sends every NewProxy a reload
    # causes when the reload runs, so a second one for the first proxy would be decided
    # by then.
    with connect(first_port) as held:
        assert round_trip(held, PAYLOAD) == PAYLOAD
        frp_stack.rewrite_frpc(client, [first, Proxy("second", second_port, grant(second_port))])
        client.reload()
        client.wait_for_status("second", "running")
        log.wait_for(lambda line: line.get("proxy") == "second")

        assert round_trip(held, PAYLOAD) == PAYLOAD
    after = frp_stack.decisions()[before:]
    assert [(line["event"], line["proxy"]) for line in after] == [("admit", "second")]
    assert exchange(second_port, PAYLOAD) == PAYLOAD
