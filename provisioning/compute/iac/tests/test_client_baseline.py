"""Library integration of the shipped baseline editor against real files.

All tokens and addresses are deterministic public fixtures, never for a public network.
"""

import importlib.util
from pathlib import Path
import stat
import tomllib

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "ansible/roles/relay-client/files/client_config.py"
spec = importlib.util.spec_from_file_location("client_config", MODULE)
client_config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client_config)


def values():
    return {"serverAddr": "relay.example.invalid", "serverPort": 7000,
            "auth.token": "public-fixture-token", "webServer.port": 740}


def test_baseline_is_private_stable_and_preserves_proxy_blocks(tmp_path):
    config = tmp_path / "frpc-buyers.toml"
    assert client_config.prepare(config, values())
    first = tomllib.loads(config.read_text())
    assert stat.S_IMODE(config.stat().st_mode) == 0o600
    assert len(first["webServer"]["password"]) == 64
    assert first["webServer"]["addr"] == "127.0.0.1"
    assert first["webServer"]["port"] == 740
    assert not client_config.prepare(config, values())
    proxy = '# BEGIN ANSIBLE MANAGED RELAY PROXY tenant-example\n[[proxies]]\nname = "tenant-example"\nmetadatas.grant = "synthetic-grant"\n# END ANSIBLE MANAGED RELAY PROXY tenant-example\n'
    config.write_text(config.read_text() + proxy)
    changed = {**values(), "serverAddr": "relay-2.example.invalid", "auth.token": "rotated-fixture"}
    assert client_config.prepare(config, changed)
    assert config.read_text().endswith(proxy)
    data = tomllib.loads(config.read_text())
    assert data["serverAddr"] == changed["serverAddr"]
    assert data["auth"]["token"] == changed["auth.token"]
    assert data["webServer"]["password"] == first["webServer"]["password"]
    assert data["proxies"][0]["metadatas"]["grant"] == "synthetic-grant"
    assert not client_config.prepare(config, changed)
    assert client_config.credentials(config) == {"webServer.password": first["webServer"]["password"], "webServer.port": 740}


def test_each_host_has_its_own_password_and_mode_is_repaired(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    client_config.prepare(a, values())
    client_config.prepare(b, values())
    assert client_config.credentials(a) != client_config.credentials(b)
    a.chmod(0o644)
    assert not client_config.prepare(a, values())
    assert stat.S_IMODE(a.stat().st_mode) == 0o600
