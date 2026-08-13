from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from src import hosted_restart_control


def _request(server, service: str, credential: str | None = None):
    headers = {} if credential is None else {"Authorization": f"Bearer {credential}"}
    request = urllib.request.Request(
        f"http://127.0.0.1:{server.server_port}/restart/{service}",
        method="POST",
        headers=headers,
    )
    return urllib.request.urlopen(request, timeout=2)


@pytest.fixture
def restart_server(monkeypatch):
    monkeypatch.setenv(
        "HOSTED_SETTLEMENT_E2E_RESTART_CREDENTIAL", "test-restart-credential"
    )
    server = hosted_restart_control.ThreadingHTTPServer(
        ("127.0.0.1", 0), hosted_restart_control._Handler
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def test_restart_control_requires_bearer_credential(restart_server, monkeypatch) -> None:
    called = False

    def restart(service: str) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(hosted_restart_control, "_restart", restart)
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _request(restart_server, "hosted-settlement-api")
    assert exc_info.value.code == 401
    assert called is False


def test_restart_control_dispatches_allowlisted_service(restart_server, monkeypatch) -> None:
    restarted: list[str] = []
    monkeypatch.setattr(hosted_restart_control, "_restart", restarted.append)

    with _request(
        restart_server,
        "hosted-settlement-worker",
        credential="test-restart-credential",
    ) as response:
        payload = json.load(response)

    assert payload == {"restarted": True, "service": "hosted-settlement-worker"}
    assert restarted == ["hosted-settlement-worker"]


def test_restart_control_rejects_non_allowlisted_service(restart_server) -> None:
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _request(restart_server, "registry", credential="test-restart-credential")
    assert exc_info.value.code == 400
