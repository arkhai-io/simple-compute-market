"""Real frps and frpc processes with the plugin, run as `serve` runs it.

Every port — frps's bind port, the plugin's, each frpc's admin port, frps's
`allowPorts`, the issuers' ranges, and the remote ports — is chosen at runtime on
127.0.0.1, distinct from one another and found free just before a process binds it, a
race the tests accept. Grants are signed with RFC 8032's TEST 1 key against the system
clock, which is the plugin's clock here.

A proxy's state is read from frpc's admin `/api/status`, and frps's readiness from its
port, by polling within a bound: an external process offers nothing to wait on. A
decision is awaited in the plugin's log on a condition.
"""

from __future__ import annotations

import json
import random
import signal
import socket
import socketserver
import subprocess
import sys
import threading
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from tests.frp_fetch import Binaries
from tests.rfc8032 import TEST_1, TEST_3, Rfc8032Key
from tests.vector_builder import AUDIENCE, claims, header, sign

WAIT_SECONDS = 15
# frpc 0.61.1 sends a refused proxy's NewProxy again on its own 30 seconds after the
# refusal (measured here at 30.1 to 30.2 seconds), so a wait for that retry is twice
# as long and cannot end first.
RETRY_WAIT_SECONDS = 60
POLL_SECONDS = 0.2
# The stcp proxy's shared secret: a fixed test value, used only on loopback.
STCP_SECRET = "frp-gate-test-secret"


def wait_until(predicate: Callable[[], Any], seconds: float, describe: Callable[[], str]) -> Any:
    """Poll `predicate` until it returns something truthy, failing after `seconds`."""
    deadline = time.monotonic() + seconds
    while True:
        result = predicate()
        if result:
            return result
        if time.monotonic() >= deadline:
            pytest.fail(f"not within {seconds}s: {describe()}")
        time.sleep(POLL_SECONDS)


class PortPicker:
    """Loopback ports free when picked, never the same port twice."""

    def __init__(self) -> None:
        self._taken: set[int] = set()

    def one(self) -> int:
        while True:
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            if port not in self._taken:
                self._taken.add(port)
                return port

    def block(self, size: int) -> int:
        """The first of `size` consecutive ports, all free and none picked before."""
        for _ in range(100):
            start = random.randrange(20000, 60000 - size)
            ports = range(start, start + size)
            if self._taken.intersection(ports) or not _all_free(ports):
                continue
            self._taken.update(ports)
            return start
        raise RuntimeError(f"no {size} consecutive free loopback ports found")


def _all_free(ports: range) -> bool:
    probes: list[socket.socket] = []
    try:
        for port in ports:
            probe = socket.socket()
            probes.append(probe)
            probe.bind(("127.0.0.1", port))
    except OSError:
        return False
    finally:
        for probe in probes:
            probe.close()
    return True


class Output:
    """A process's output lines, read by a thread so a test can wait on them."""

    def __init__(self, stream: Any) -> None:
        self._lines: list[str] = []
        self._changed = threading.Condition()
        threading.Thread(target=self._read, args=(stream,), daemon=True).start()

    def _read(self, stream: Any) -> None:
        for line in stream:
            with self._changed:
                self._lines.append(line.rstrip("\n"))
                self._changed.notify_all()

    @property
    def text(self) -> str:
        with self._changed:
            return "\n".join(self._lines)

    def records(self) -> list[dict[str, Any]]:
        """The lines that are JSON objects; the plugin writes nothing else but a traceback."""
        found = []
        for line in self.text.splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                found.append(record)
        return found

    def wait_for(
        self, predicate: Callable[[dict[str, Any]], bool], seconds: float = WAIT_SECONDS
    ) -> dict[str, Any]:
        found: list[dict[str, Any]] = []

        def matched() -> bool:
            found[:] = [record for record in self.records() if predicate(record)]
            return bool(found)

        with self._changed:
            if not self._changed.wait_for(matched, timeout=seconds):
                pytest.fail(f"no matching line within {seconds}s in:\n{self.text}")
        return found[0]


def stop(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(WAIT_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(WAIT_SECONDS)


def start_process(arguments: list[str], cwd: Path) -> tuple[subprocess.Popen[str], Output]:
    process = subprocess.Popen(
        arguments,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return process, Output(process.stdout)


@dataclass(frozen=True)
class Ports:
    """frps's and the plugin's ports, and a block of eight for the issuers and frps."""

    frps: int
    plugin: int
    block: int

    @property
    def issuer_a(self) -> tuple[int, int]:
        return self.block, self.block + 2

    @property
    def issuer_b(self) -> tuple[int, int]:
        return self.block + 3, self.block + 5

    @property
    def outside_every_range(self) -> int:
        return self.block + 6

    @property
    def allow_ports(self) -> tuple[int, int]:
        return self.block, self.block + 7


def plugin_configuration(ports: Ports, issuer_a_keys: tuple[Rfc8032Key, ...]) -> str:
    """Issuer A with the keys given, issuer B with TEST 3; RFC 8032 test keys only."""

    def keys(chosen: tuple[Rfc8032Key, ...]) -> str:
        return ", ".join(f'{{ public_key = "{key.spki_base64}" }}' for key in chosen)

    (a_start, a_end), (b_start, b_end) = ports.issuer_a, ports.issuer_b
    return (
        f'listen = "127.0.0.1:{ports.plugin}"\n\n'
        f'[[issuers]]\nname = "issuer-a"\naudience = "{AUDIENCE}"\n'
        f"ports = {{ start = {a_start}, end = {a_end} }}\nkeys = [ {keys(issuer_a_keys)} ]\n\n"
        f'[[issuers]]\nname = "issuer-b"\naudience = "{AUDIENCE}"\n'
        f"ports = {{ start = {b_start}, end = {b_end} }}\nkeys = [ {keys((TEST_3,))} ]\n"
    )


def frps_configuration(ports: Ports) -> str:
    start, end = ports.allow_ports
    return (
        f'bindAddr = "127.0.0.1"\nbindPort = {ports.frps}\n'
        f"allowPorts = [ {{ start = {start}, end = {end} }} ]\n\n"
        f'[[httpPlugins]]\nname = "grant-admission"\naddr = "127.0.0.1:{ports.plugin}"\n'
        'path = "/"\nops = ["NewProxy"]\n'
    )


def grant(
    port: int,
    *,
    key: Rfc8032Key = TEST_1,
    signer: Rfc8032Key | None = None,
    lifetime: int = 3600,
    **changes: Any,
) -> str:
    """A grant for `port` named by `key`'s id and signed by `signer`, on the system clock."""
    now = int(time.time())
    members = claims(port=port, iat=now - 60, exp=now + lifetime, **changes)
    return sign(header(key), members, key=signer or key)


@dataclass(frozen=True)
class Proxy:
    """One `[[proxies]]` entry of frpc's configuration."""

    name: str
    remote_port: int | None = None
    grant: str | None = None
    type: str = "tcp"

    def toml(self, local_port: int) -> str:
        lines = [
            "[[proxies]]",
            f'name = "{self.name}"',
            f'type = "{self.type}"',
            'localIP = "127.0.0.1"',
            f"localPort = {local_port}",
        ]
        if self.type == "stcp":
            lines.append(f'secretKey = "{STCP_SECRET}"')
        if self.remote_port is not None:
            lines.append(f"remotePort = {self.remote_port}")
        if self.grant is not None:
            lines.append(f'metadatas.grant = "{self.grant}"')
        return "\n".join(lines) + "\n"


class Echo:
    """A loopback TCP service a proxy forwards to, echoing what it receives."""

    def __init__(self) -> None:
        class Handler(socketserver.BaseRequestHandler):
            def handle(self) -> None:
                while data := self.request.recv(4096):
                    self.request.sendall(data)

        self._server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self.port = self._server.server_address[1]
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


def connect(port: int) -> socket.socket:
    """A connection to a remote port on frps."""
    return socket.create_connection(("127.0.0.1", port), timeout=WAIT_SECONDS)


def round_trip(connection: socket.socket, payload: bytes) -> bytes:
    """Send `payload` and read back as many bytes, or fewer if the connection ends."""
    connection.sendall(payload)
    received = b""
    while len(received) < len(payload):
        chunk = connection.recv(4096)
        if not chunk:
            break
        received += chunk
    return received


def exchange(port: int, payload: bytes) -> bytes:
    """Send `payload` to a remote port on frps over a new connection and read it back."""
    with connect(port) as connection:
        return round_trip(connection, payload)


@dataclass
class Frpc:
    """One frpc process and the configuration file it was started from."""

    binary: Path
    path: Path
    admin_port: int
    process: subprocess.Popen[str]
    output: Output

    def status(self, name: str) -> dict[str, Any] | None:
        """The proxy's entry in frpc's `/api/status`, or None while it lists none."""
        url = f"http://127.0.0.1:{self.admin_port}/api/status"
        try:
            with urllib.request.urlopen(url, timeout=WAIT_SECONDS) as response:
                document = json.load(response)
        except OSError:
            return None
        for entries in document.values():
            for entry in entries or ():
                if entry.get("name") == name:
                    return entry
        return None

    def wait_for_status(
        self, name: str, status: str, seconds: float = WAIT_SECONDS
    ) -> dict[str, Any]:
        def reached() -> dict[str, Any] | None:
            entry = self.status(name)
            return entry if entry and entry.get("status") == status else None

        return wait_until(
            reached,
            seconds,
            lambda: f"{name} is {self.status(name)}, not {status}; frpc:\n{self.output.text}",
        )

    def reload(self) -> None:
        """`frpc reload`: frpc re-reads its file and registers only the proxies it changed."""
        result = subprocess.run(
            [str(self.binary), "reload", "-c", str(self.path)],
            capture_output=True,
            text=True,
            timeout=WAIT_SECONDS,
        )
        assert result.returncode == 0, result.stdout + result.stderr


@dataclass
class FrpStack:
    """frps with the plugin as its `NewProxy` server plugin, and the frpc clients started."""

    binaries: Binaries
    directory: Path
    picker: PortPicker
    ports: Ports
    echo: Echo
    plugin_path: Path
    plugin: subprocess.Popen[str] | None = None
    plugin_output: Output | None = None
    frps: subprocess.Popen[str] | None = None
    frps_output: Output | None = None
    clients: list[Frpc] = field(default_factory=list)

    @classmethod
    def create(cls, binaries: Binaries, directory: Path) -> FrpStack:
        picker = PortPicker()
        block = picker.block(8)
        ports = Ports(frps=picker.one(), plugin=picker.one(), block=block)
        return cls(binaries, directory, picker, ports, Echo(), directory / "plugin.toml")

    def write_plugin_configuration(self, issuer_a_keys: tuple[Rfc8032Key, ...]) -> None:
        self.plugin_path.write_text(plugin_configuration(self.ports, issuer_a_keys))

    def start_plugin(self) -> Output:
        """Run `frp-grant-admission serve` and wait for its startup line."""
        command = [sys.executable, "-m", "frp_grant_admission.cli", "serve", "--config"]
        self.plugin, self.plugin_output = start_process(
            [*command, str(self.plugin_path)], self.directory
        )
        self.plugin_output.wait_for(
            lambda line: line.get("event") == "config_loaded" and line.get("trigger") == "startup"
        )
        return self.plugin_output

    def stop_plugin(self) -> None:
        if self.plugin is not None:
            stop(self.plugin)

    def reload_plugin(self) -> dict[str, Any]:
        """SIGHUP the plugin and wait for its reload line."""
        assert self.plugin is not None and self.plugin_output is not None
        before = len(self.reloads())
        self.plugin.send_signal(signal.SIGHUP)
        return wait_until(
            lambda: self.reloads()[before:] and self.reloads()[before],
            WAIT_SECONDS,
            lambda: f"no reload line; plugin:\n{self.plugin_output.text}",
        )

    def reloads(self) -> list[dict[str, Any]]:
        assert self.plugin_output is not None
        return [line for line in self.plugin_output.records() if line.get("trigger") == "reload"]

    def decisions(self) -> list[dict[str, Any]]:
        assert self.plugin_output is not None
        return [
            line
            for line in self.plugin_output.records()
            if line.get("event") in ("admit", "refuse")
        ]

    def start_frps(self) -> None:
        path = self.directory / "frps.toml"
        path.write_text(frps_configuration(self.ports))
        self.frps, self.frps_output = start_process(
            [str(self.binaries.frps), "-c", str(path)], self.directory
        )

        def listening() -> bool:
            try:
                socket.create_connection(("127.0.0.1", self.ports.frps), timeout=1).close()
            except OSError:
                return False
            return True

        wait_until(listening, WAIT_SECONDS, lambda: f"frps not listening:\n{self.frps_output.text}")

    def start_frpc(self, proxies: list[Proxy], client_grant: str | None = None) -> Frpc:
        """Start an frpc carrying `proxies`; `client_grant` goes in its client-wide metadata."""
        path = self.directory / f"frpc-{len(self.clients)}.toml"
        admin_port = self.picker.one()
        path.write_text(self._frpc_text(proxies, client_grant, admin_port))
        return self._run_frpc(path, admin_port)

    def restart_frpc(self, client: Frpc) -> Frpc:
        """Stop `client` and start a new frpc from the same file, which registers anew."""
        stop(client.process)
        return self._run_frpc(client.path, client.admin_port)

    def rewrite_frpc(self, client: Frpc, proxies: list[Proxy]) -> None:
        client.path.write_text(self._frpc_text(proxies, None, client.admin_port))

    def _frpc_text(self, proxies: list[Proxy], client_grant: str | None, admin_port: int) -> str:
        lines = [
            'serverAddr = "127.0.0.1"',
            f"serverPort = {self.ports.frps}",
            "loginFailExit = false",
            'webServer.addr = "127.0.0.1"',
            f"webServer.port = {admin_port}",
        ]
        if client_grant is not None:
            lines.append(f'metadatas.grant = "{client_grant}"')
        entries = "\n".join(proxy.toml(self.echo.port) for proxy in proxies)
        return "\n".join(lines) + "\n\n" + entries

    def _run_frpc(self, path: Path, admin_port: int) -> Frpc:
        process, output = start_process([str(self.binaries.frpc), "-c", str(path)], self.directory)
        client = Frpc(self.binaries.frpc, path, admin_port, process, output)
        self.clients.append(client)
        return client

    def close(self) -> None:
        for client in self.clients:
            stop(client.process)
        if self.frps is not None:
            stop(self.frps)
        self.stop_plugin()
        self.echo.close()


def binary_version(binary: Path) -> str:
    """What `<binary> --version` prints: frps and frpc print their release, `0.61.1`."""
    result = subprocess.run(
        [str(binary), "--version"], capture_output=True, text=True, timeout=WAIT_SECONDS
    )
    return result.stdout.strip()
