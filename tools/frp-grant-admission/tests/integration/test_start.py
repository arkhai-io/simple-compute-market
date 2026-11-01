"""Starting the plugin as `serve` does: the configured address, the startup line, SIGHUP.

The configured port is found free just before the test binds it, since a
configuration names a real port and cannot ask for an ephemeral one.
"""

from __future__ import annotations

import http.client
import io
import json
import os
import signal
import socket
import threading
from pathlib import Path

from frp_grant_admission.cli import start
from frp_grant_admission.decision_log import DecisionLog
from tests.frps_request import PATH, new_proxy
from tests.integration.test_server import WAIT_SECONDS, LogLines, configuration


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def lines(stream: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_start_binds_the_configured_address_logs_and_reloads_on_sighup(tmp_path: Path) -> None:
    port = free_port()
    path = tmp_path / "config.toml"
    path.write_text(configuration(listen=f"127.0.0.1:{port}"))
    log = LogLines()
    previous = signal.getsignal(signal.SIGHUP)

    server = start(str(path), DecisionLog(log))

    assert server is not None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert server.server_address[:2] == ("127.0.0.1", port)
        (line,) = log.lines()
        assert (line["event"], line["trigger"], line["listen"]) == (
            "config_loaded",
            "startup",
            f"127.0.0.1:{port}",
        )

        path.write_text(configuration(listen=f"127.0.0.1:{port}", site_b=True))
        os.kill(os.getpid(), signal.SIGHUP)

        reloaded = log.wait_for(lambda line: line.get("trigger") == "reload")
        assert [issuer["name"] for issuer in reloaded["issuers"]] == ["issuer-a", "issuer-b"]
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=WAIT_SECONDS)
        try:
            # The system clock decides here, against which the vector's grant,
            # issued for 2027, is not yet valid; only the answer's shape is asserted.
            connection.request("POST", PATH, body=json.dumps(new_proxy()).encode())
            response = connection.getresponse()
            assert response.status == 200
            assert "reject" in json.loads(response.read())
        finally:
            connection.close()
    finally:
        signal.signal(signal.SIGHUP, previous)
        server.shutdown()
        server.server_close()
        thread.join(WAIT_SECONDS)


def test_start_refuses_an_address_it_cannot_bind(tmp_path: Path) -> None:
    with socket.socket() as occupier:
        occupier.bind(("127.0.0.1", 0))
        occupier.listen()
        port = occupier.getsockname()[1]
        path = tmp_path / "config.toml"
        path.write_text(configuration(listen=f"127.0.0.1:{port}"))
        stream = io.StringIO()
        previous = signal.getsignal(signal.SIGHUP)

        assert start(str(path), DecisionLog(stream)) is None

    (line,) = lines(stream)
    assert line["event"] == "config_refused"
    assert line["problems"][0].startswith(f"cannot listen on 127.0.0.1:{port}")
    assert signal.getsignal(signal.SIGHUP) is previous
