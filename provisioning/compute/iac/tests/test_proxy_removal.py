"""Library integration of exact proxy removal and retry state with real HTTP.

The loopback peer and deterministic password are public fixtures, never for a public network.
"""

import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import threading

import pytest

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = (ROOT / "ansible/roles/relay-proxy/files/remove_proxy.sh").read_text()
PASSWORD = "a" * 64


def block(name):
    return f'# BEGIN ANSIBLE MANAGED RELAY PROXY {name}\n[[proxies]]\nname = "{name}"\n# END ANSIBLE MANAGED RELAY PROXY {name}\n'


class Peer:
    def __init__(self, statuses):
        self.calls = []
        self.statuses = list(statuses)
        peer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                peer.calls.append((self.path, self.headers.get("Authorization")))
                expected = "Basic " + base64.b64encode(("admin:" + PASSWORD).encode()).decode()
                status = peer.statuses.pop(0) if peer.statuses else 200
                self.send_response(status if self.headers.get("Authorization") == expected else 401)
                self.end_headers()

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        # shutdown() returns only at serve_forever's next poll, and the library
        # has no way to wake it, so the poll is short rather than the default 0.5s.
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.01), daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_port}/api/reload"


def remove(config, url, name="tenant-example"):
    return subprocess.run(["bash", "-c", "set -e\n" + LIBRARY + '\nremove_guest_proxy "$1" "$2" "$3"\nprintf "%s\\n" "$GUEST_PROXY"', "test", str(config), name, url], capture_output=True, text=True, check=False)


def test_removal_authenticates_preserves_neighbours_and_retries_failed_reload(tmp_path):
    config = tmp_path / "frpc-buyers.toml"
    original = f'webServer.port = 600\nwebServer.password = "{PASSWORD}"\n' + block("tenant-example") + block("tenant-example-2")
    config.write_text(original)
    config.chmod(0o600)
    management = tmp_path / "frpc.toml"
    management.write_text(original)
    with Peer([500, 200]) as peer:
        failed = remove(config, peer.url)
        assert failed.returncode != 0
        assert block("tenant-example") not in config.read_text()
        assert block("tenant-example-2") in config.read_text()
        assert Path(str(config) + ".reload-pending.tenant-example").exists()
        succeeded = remove(config, peer.url)
        assert succeeded.returncode == 0, succeeded.stderr
        assert succeeded.stdout.strip() == "removed"
        assert not Path(str(config) + ".reload-pending.tenant-example").exists()
        absent = remove(config, peer.url)
        assert absent.returncode == 0
        assert absent.stdout.strip() == "absent"
        assert len(peer.calls) == 2
        assert all(path == "/api/reload" and auth.startswith("Basic ") for path, auth in peer.calls)
    assert management.read_text() == original
    assert config.stat().st_mode & 0o777 == 0o600


def test_a_missing_end_marker_is_refused_without_removing_a_neighbour(tmp_path):
    config = tmp_path / "frpc-buyers.toml"
    original = f'webServer.port = 600\nwebServer.password = "{PASSWORD}"\n' + block("tenant-example").replace("# END ANSIBLE MANAGED RELAY PROXY tenant-example\n", "") + block("tenant-example-2")
    config.write_text(original)
    with Peer([]) as peer:
        failed = remove(config, peer.url)
        assert failed.returncode != 0
        assert peer.calls == []
    assert config.read_text() == original


def test_a_missing_configuration_fails_without_claiming_absence(tmp_path):
    with Peer([]) as peer:
        result = remove(tmp_path / "absent", peer.url)
        assert result.returncode != 0
        assert result.stdout.strip() != "absent"
        assert peer.calls == []


@pytest.mark.parametrize("failed_command", ["cat", "grep"])
def test_config_read_failure_is_not_treated_as_a_missing_marker(tmp_path, failed_command):
    config = tmp_path / "frpc-buyers.toml"
    config.write_text(f'webServer.port = 600\nwebServer.password = "{PASSWORD}"\n' + block("tenant-example"))
    binary = tmp_path / "bin"
    binary.mkdir()
    (binary / failed_command).write_text("#!/bin/sh\nexit 2\n")
    (binary / failed_command).chmod(0o755)
    run = subprocess.run(["bash", "-c", "set -e\n" + LIBRARY +
                          '\nPATH="$4:$PATH"; remove_guest_proxy "$1" "$2" "$3"',
                          "test", str(config), "tenant-example", "http://127.0.0.1:1/api/reload", str(binary)],
                         capture_output=True, text=True, check=False)
    assert run.returncode != 0
    assert block("tenant-example") in config.read_text()


def test_disappeared_config_keeps_pending_reload_evidence(tmp_path):
    config = tmp_path / "missing.toml"
    pending = Path(str(config) + ".reload-pending.tenant-example")
    pending.touch()
    with Peer([]) as peer:
        result = remove(config, peer.url)
        assert result.returncode != 0
        assert pending.exists()
        assert peer.calls == []
