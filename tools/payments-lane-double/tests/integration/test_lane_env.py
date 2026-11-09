"""The double's values lanes and the local release read come from its committed fixtures.

Two kinds of reader. scripts/lane_env.py, not part of the double's package, runs
with the host's interpreter, outside this project's environment, and prints the
seller's account and token; the cases load it from its path, hold its imports to
the standard library, and run it as its callers do, in a separate isolated
interpreter. The lanes' committed runner profiles, under e2e-tests/config, restate
the double's values and each lane storefront's signing key; the cases hold every
restated value to the file it restates.
"""

from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from cryptography import x509

from payments_lane_double.accounts import load_accounts
from payments_lane_double.settings import PORT

from conftest import FIXTURES

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "lane_env.py"
_SPEC = importlib.util.spec_from_file_location("lane_env", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
lane_env = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(lane_env)

_REPO = Path(__file__).resolve().parents[4]
# The double's leaf certificate, which the lane CA's generator in the controls
# project writes and the image serves.
_LEAF = _REPO / "tools" / "lane-double-controls" / "tls" / "payments-double.pem"
_RUNNER_PROFILES = _REPO / "e2e-tests" / "config"
_IDENTITIES = _REPO / "dev-env" / "identities"
# Each lane's runner profile and the identity file its payment storefront signs
# with, whose key the lane's scenarios use as the seller's credential.
_LANE_SELLERS = {
    "config-vms-lane.yml": "bob.identity.env",
    "config-apicredits-lane.yml": "api-credits.identity.env",
    "config-bare-metal-lane.yml": "bob.identity.env",
}


def _run(mode: str) -> list[str]:
    completed = subprocess.run(
        [sys.executable, "-I", str(_SCRIPT), mode],
        capture_output=True, text=True, check=True,
    )
    return completed.stdout.splitlines()


def _payments(profile: str) -> dict:
    return yaml.safe_load((_RUNNER_PROFILES / profile).read_text(encoding="utf-8"))["payments"]


def _identity_credential(name: str) -> str:
    for line in (_IDENTITIES / name).read_text(encoding="utf-8").splitlines():
        if line.startswith("ARKHAI_IDENTITY_CREDENTIAL="):
            return line.split("=", 1)[1]
    raise AssertionError(f"{name} states no ARKHAI_IDENTITY_CREDENTIAL")


def test_the_script_imports_only_the_standard_library() -> None:
    tree = ast.parse(_SCRIPT.read_text(encoding="utf-8"))
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    }

    assert imported - {"__future__"} <= set(sys.stdlib_module_names)


def test_run_isolated_it_prints_the_seller_account_and_token() -> None:
    directory = load_accounts(FIXTURES / "accounts.toml")

    assert _run("seller-account") == [directory.role("seller").account]
    assert _run("seller-token") == [directory.role("seller").token]


def test_the_service_url_is_a_name_the_certificate_covers_at_the_port_the_double_serves() -> None:
    leaf = x509.load_pem_x509_certificate(_LEAF.read_bytes())
    names = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    url = urlsplit(lane_env.SERVICE_URL)

    assert url.scheme == "https"
    assert url.hostname in names.get_values_for_type(x509.DNSName)
    assert url.port == PORT


def test_the_shared_runner_profile_restates_the_double_fixtures() -> None:
    directory = load_accounts(FIXTURES / "accounts.toml")
    payments = _payments("config-payments-lane.yml")

    assert payments["service_url"] == lane_env.SERVICE_URL
    assert payments["service_identity"] == directory.receipt_identity.identifier
    assert payments["fee_bps"] == directory.fee_bps
    assert payments["livemode"] is False
    assert payments["lane_owned"] is True
    assert payments["buyer_account"] == directory.role("buyer").account
    assert payments["seller_account"] == directory.role("seller").account
    assert payments["buyer_api_key"] == directory.role("buyer").token
    # The variable the harness hands the key over under, never one the runner's
    # own settings loader reads.
    assert not payments["api_key_env"].startswith("ARKHAI_")
    assert payments["ca_bundle_path"] == "/run/lane-doubles/lane-ca.pem"
    # The harness reads the double's status with it.
    assert payments["control_token"] == directory.control_token


def test_each_lane_profile_states_its_storefront_signing_key_alone() -> None:
    shared = set(_payments("config-payments-lane.yml"))
    for profile, identity in _LANE_SELLERS.items():
        payments = _payments(profile)
        assert payments["seller_marketplace_credential"] == _identity_credential(identity), profile
        # Only what differs by lane; the shared profile holds the rest.
        assert not set(payments) & shared, profile
