"""`bare-metal-storefront check-payments` reads the storefront's own
configuration, prints one outcome, and exits by it.

The command runs in process over its real configuration read: each case writes
the configuration files the server reads under a temporary ``XDG_CONFIG_HOME``,
and replaces only the command module's ``payments_transport`` factory, the
network under the real payments client, so the HTTP boundary is mocked. One case
runs the command in a fresh interpreter against a loopback port nothing listens
on, to show it loads none of the storefront's database or runtime. Spec
scenarios "The storefront can reach its payments service" and "The storefront
does not trust the payments origin", the latter as the transport error httpx
raises for an untrusted certificate.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
from market_identity import Ed25519Signer
from typer.testing import CliRunner

import arkhai_bare_metal_storefront.cli as cli
from storefront_configuration import publishable_configuration, write_configuration

# Public test-only values that authenticate to nothing; never use them on a
# public network.
SERVICE = Ed25519Signer(b"\x07" * 32)
KEY = "sk_test_bare_metal_storefront_check_canary"
KEY_ENV = "BARE_METAL_SELLER_PAYMENTS_KEY"
ACCOUNT = "00000000-0000-4000-8000-0000000000b2"
# A loopback origin: the client reads no proxy settings for one, so an ambient
# HTTPS_PROXY cannot route around the mocked transport.
URL = "https://127.0.0.1:8443"

runner = CliRunner()


def payments_section() -> dict[str, Any]:
    return {
        "enabled": True, "service_url": URL,
        "service_identity": SERVICE.identity.model_dump(mode="json"),
        "fee_bps": 250, "livemode": False, "api_key_env": KEY_ENV,
    }


def configure(monkeypatch, tmp_path: Path, *, payments: dict[str, Any] | None) -> Path:
    document = publishable_configuration(tmp_path / "never.db")
    if payments is not None:
        document["Settlement"]["arkhai_payments"] = payments
    return write_configuration(monkeypatch, tmp_path, document)


def invoke(monkeypatch, handler=None, *, key: str | None = KEY):
    requests: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if handler is None:
            return httpx.Response(200, json={"available": {"USD/6": "0"}, "held": []})
        return handler(request)

    monkeypatch.setattr(cli, "payments_transport", lambda: httpx.MockTransport(answer))
    monkeypatch.delenv(KEY_ENV, raising=False)
    if key is not None:
        monkeypatch.setenv(KEY_ENV, key)
    return runner.invoke(cli.app, ["check-payments", "--account", ACCOUNT]), requests


def test_the_configured_section_reaches_the_service_and_prints_ok(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path, payments=payments_section())

    result, requests = invoke(monkeypatch)

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "check": "payments", "outcome": "ok", "service_url": URL, "account": ACCOUNT,
        "assets": ["USD/6"], "held": 0,
    }
    assert [(r.url.path, r.headers["Authorization"]) for r in requests] == [
        (f"/balances/{ACCOUNT}", f"Bearer {KEY}")
    ]
    assert not (tmp_path / "never.db").exists()


def untrusted(request: httpx.Request) -> httpx.Response:
    # What httpx raises when the origin's certificate is not trusted; the text
    # carries the key to show it never reaches the output.
    raise httpx.ConnectError(f"[SSL: CERTIFICATE_VERIFY_FAILED] {KEY}", request=request)


@pytest.mark.parametrize(
    "payments, key, handler, step",
    [
        (None, KEY, None, "configuration"),
        (payments_section(), None, None, "credential"),
        (payments_section(), KEY, untrusted, "transport"),
    ],
    ids=["no-section", "unset-key", "untrusted-origin"],
)
def test_each_failure_prints_its_step_and_exits_one(
    monkeypatch, tmp_path, payments, key, handler, step
):
    configure(monkeypatch, tmp_path, payments=payments)

    result, _ = invoke(monkeypatch, handler, key=key)

    assert result.exit_code == 1, result.output
    outcome = json.loads(result.output)
    assert outcome["outcome"] == "failed" and outcome["step"] == step
    assert KEY not in result.output


def test_a_configuration_the_storefront_cannot_read_is_a_configuration_failure(
    monkeypatch, tmp_path
):
    directory = configure(monkeypatch, tmp_path, payments=payments_section())
    (directory / "storefront.toml").write_text("port = 'not a port'\n", encoding="utf-8")

    result, requests = invoke(monkeypatch)

    assert result.exit_code == 1, result.output
    assert json.loads(result.output)["step"] == "configuration"
    assert requests == []


_LOADED_BY_CHECK = """
import json
import sys
from typer.testing import CliRunner
from arkhai_bare_metal_storefront.cli import app

result = CliRunner().invoke(app, ["check-payments", "--account", sys.argv[1]])
assert result.exit_code == 1, result.output
# The client was built and its connection refused: the run reached the network.
assert json.loads(result.output)["step"] == "transport", result.output
print(sorted(name for name in sys.modules if name.startswith("arkhai_bare_metal_storefront")))
"""


def test_the_command_loads_none_of_the_storefronts_database_or_runtime(
    monkeypatch, tmp_path
):
    """In a fresh interpreter, against a payments origin nothing answers, the
    command imports none of the storefront's database layer or runtime and
    creates no database."""
    configure(monkeypatch, tmp_path, payments={**payments_section(),
                                               "service_url": "https://127.0.0.1:9"})
    monkeypatch.setenv(KEY_ENV, KEY)

    completed = subprocess.run(
        [sys.executable, "-c", _LOADED_BY_CHECK, ACCOUNT],
        capture_output=True, text=True, timeout=120, check=True,
    )

    loaded = set(ast.literal_eval(completed.stdout.strip().splitlines()[-1]))
    for module in ("sqlite_client", "runtime", "server", "migrations"):
        assert f"arkhai_bare_metal_storefront.{module}" not in loaded
    assert not (tmp_path / "never.db").exists()
