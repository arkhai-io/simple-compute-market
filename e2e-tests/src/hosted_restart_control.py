"""Authenticated, allowlisted restart control for hermetic Compose recovery tests."""

from __future__ import annotations

import argparse
import hmac
import http.client
import json
import os
import socket
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from typing import Any

_ALLOWED_SERVICES = frozenset(
    {"hosted-settlement-api", "hosted-settlement-worker", "bob-storefront"}
)
_MECHANISM_LOCK = Lock()
_MECHANISM_STATE: dict[str, Any] = {
    "priority": [],
    "readiness": {},
    "selected": None,
    "accepted": None,
}


def _select_mechanism(priority: list[str], readiness: dict[str, bool]) -> str | None:
    return next((mechanism for mechanism in priority if readiness.get(mechanism) is True), None)


def _configure_mechanisms(payload: dict[str, Any]) -> dict[str, Any]:
    priority = payload.get("priority")
    readiness = payload.get("readiness")
    if (
        not isinstance(priority, list)
        or not all(isinstance(item, str) and item for item in priority)
        or len(set(priority)) != len(priority)
        or not isinstance(readiness, dict)
        or not all(isinstance(key, str) and isinstance(value, bool) for key, value in readiness.items())
    ):
        raise ValueError("priority and readiness must be valid mechanism controls")
    selected = _select_mechanism(priority, readiness)
    with _MECHANISM_LOCK:
        _MECHANISM_STATE.update(
            priority=list(priority),
            readiness=dict(readiness),
            selected=selected,
            accepted=selected,
        )
        return dict(_MECHANISM_STATE)


def _recover_mechanisms() -> dict[str, Any]:
    with _MECHANISM_LOCK:
        _MECHANISM_STATE["selected"] = _select_mechanism(
            _MECHANISM_STATE["priority"], _MECHANISM_STATE["readiness"]
        )
        return dict(_MECHANISM_STATE)


def _mutate_mechanisms() -> dict[str, Any]:
    with _MECHANISM_LOCK:
        priority = list(reversed(_MECHANISM_STATE["priority"]))
        _MECHANISM_STATE["priority"] = priority
        _MECHANISM_STATE["selected"] = _select_mechanism(
            priority, _MECHANISM_STATE["readiness"]
        )
        return dict(_MECHANISM_STATE)


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"missing required environment variable: {name}")
    return value


class _UnixConnection(http.client.HTTPConnection):
    def __init__(self, path: str) -> None:
        super().__init__("localhost", timeout=10)
        self._path = path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self._path)


def _engine_request(method: str, path: str) -> tuple[int, bytes]:
    connection = _UnixConnection(
        os.environ.get("HOSTED_SETTLEMENT_E2E_ENGINE_SOCKET", "/var/run/docker.sock")
    )
    try:
        connection.request(method, path)
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def _container(service: str) -> dict[str, Any]:
    status, body = _engine_request("GET", "/v1.41/containers/json?all=1")
    if status != 200:
        raise RuntimeError(f"container engine list failed with status {status}")
    rows = json.loads(body)
    matches = [
        row
        for row in rows
        if row.get("Labels", {}).get("com.docker.compose.service") == service
    ]
    if len(matches) != 1:
        raise RuntimeError(f"expected one Compose container for {service}, found {len(matches)}")
    return matches[0]


def _restart(service: str) -> None:
    if service not in _ALLOWED_SERVICES:
        raise ValueError("service is not restart-allowlisted")
    container_id = str(_container(service)["Id"])
    status, _ = _engine_request("POST", f"/v1.41/containers/{container_id}/restart?t=10")
    if status not in {204, 200}:
        raise RuntimeError(f"container restart failed with status {status}")
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        status, body = _engine_request("GET", f"/v1.41/containers/{container_id}/json")
        if status == 200:
            state = json.loads(body).get("State", {})
            health = state.get("Health", {}).get("Status")
            if state.get("Running") and health in {None, "healthy"}:
                return
        time.sleep(0.25)
    raise RuntimeError(f"restarted container {service} did not become ready")


class _Handler(BaseHTTPRequestHandler):
    server_version = "arkhai-hosted-restart-control/1"

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health/ready":
            self._json(200, {"ready": True})
            return
        if self.path == "/mechanisms/accepted":
            with _MECHANISM_LOCK:
                accepted = _MECHANISM_STATE["accepted"]
            self._json(200, {"mechanism": accepted})
            return
        self.send_error(404)
    def do_POST(self) -> None:  # noqa: N802
        if self.path.startswith("/restart/"):
            self._restart()
            return
        try:
            if self.path == "/mechanisms":
                payload = self._read_json()
                result = _configure_mechanisms(payload)
            elif self.path == "/mechanisms/recover":
                result = _recover_mechanisms()
            elif self.path == "/mechanisms/mutate":
                result = _mutate_mechanisms()
            else:
                self.send_error(404)
                return
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
            return
        self._json(
            200,
            {"selected": result["selected"], "accepted": result["accepted"]},
        )

    def _restart(self) -> None:
        expected = "Bearer " + _required("HOSTED_SETTLEMENT_E2E_RESTART_CREDENTIAL")
        supplied = self.headers.get("Authorization", "")
        if not hmac.compare_digest(supplied, expected):
            self._json(401, {"error": "unauthorized"})
            return
        service = self.path.removeprefix("/restart/")
        try:
            _restart(service)
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
            return
        except Exception as exc:
            self._json(502, {"error": str(exc)})
            return
        self._json(200, {"service": service, "restarted": True})

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            value = json.loads(self.rfile.read(length))
        except (ValueError, json.JSONDecodeError) as exc:
            raise ValueError("request body must be valid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError("request body must be a JSON object")
        return value
    def log_message(self, format: str, *args: object) -> None:
        return

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _serve() -> None:
    _required("HOSTED_SETTLEMENT_E2E_RESTART_CREDENTIAL")
    ThreadingHTTPServer(("0.0.0.0", 8084), _Handler).serve_forever()


def _request_restart(service: str) -> None:
    if service not in _ALLOWED_SERVICES:
        raise RuntimeError("service is not restart-allowlisted")
    base_url = os.environ.get(
        "HOSTED_SETTLEMENT_E2E_RESTART_URL", "http://hosted-compose-control:8084"
    ).rstrip("/")
    request = urllib.request.Request(
        f"{base_url}/restart/{service}",
        method="POST",
        headers={
            "Authorization": "Bearer "
            + _required("HOSTED_SETTLEMENT_E2E_RESTART_CREDENTIAL")
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=70) as response:
            if response.status != 200:
                raise RuntimeError(f"restart control returned status {response.status}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"restart control failed: {exc.code} {detail}") from exc


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("serve", "restart"))
    parser.add_argument("service", nargs="?")
    args = parser.parse_args()
    if args.action == "serve":
        if args.service is not None:
            parser.error("serve does not accept a service")
        _serve()
        return
    if args.service is None:
        parser.error("restart requires a service")
    _request_restart(args.service)


if __name__ == "__main__":
    main()
