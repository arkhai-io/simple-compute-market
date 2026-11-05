"""The lane values the root Makefile prints come from the committed fixtures.

The script, scripts/lane_env.py, is not part of the double's package; it runs with
the host's interpreter, outside this project's environment. The cases load it from
its path. One holds its imports to the standard library, and the cases that read
its output run it as the Makefile does, in a separate isolated interpreter, so they
cross that process boundary.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

from cryptography import x509
from market_deal_lifecycle.configuration import DisputeEntry

from payments_lane_double.accounts import load_accounts
from payments_lane_double.settings import PORT

from conftest import FIXTURES, committed_dispute_authority

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "lane_env.py"
_SPEC = importlib.util.spec_from_file_location("lane_env", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
lane_env = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(lane_env)


def _values(lines: list[str]) -> dict[str, str]:
    return dict(line.split("=", 1) for line in lines)


def _run(mode: str) -> list[str]:
    completed = subprocess.run(
        [sys.executable, "-I", str(_SCRIPT), mode],
        capture_output=True, text=True, check=True,
    )
    return completed.stdout.splitlines()


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


def test_run_isolated_it_prints_what_its_functions_return() -> None:
    accounts = lane_env._load(FIXTURES / "accounts.toml")

    assert _run("compose") == lane_env.compose_lines(accounts, committed_dispute_authority())
    assert _run("runner") == lane_env.runner_lines(accounts)
    assert _run("seller-account") == [accounts["accounts"]["seller"]["account"]]


def test_the_seller_token_mode_prints_the_token_the_double_authenticates_the_seller_by() -> None:
    directory = load_accounts(FIXTURES / "accounts.toml")

    assert _run("seller-token") == [directory.role("seller").token]


def test_the_compose_values_are_the_seller_token_and_the_pinned_authority() -> None:
    directory = load_accounts(FIXTURES / "accounts.toml")
    values = _values(_run("compose"))

    assert values["PAYMENTS_LANE_SELLER_API_KEY"] == directory.role("seller").token
    assert values["PAYMENTS_LANE_CA_FILE"] == str(lane_env.CA_FILE)
    quoted = values["PAYMENTS_LANE_DISPUTE_AUTHORITIES"]
    assert quoted.startswith("'") and quoted.endswith("'")
    (recommended,) = json.loads(quoted[1:-1])
    assert DisputeEntry.model_validate(recommended) == DisputeEntry.model_validate(
        committed_dispute_authority()
    )


def test_the_runner_values_name_the_double_its_identity_and_the_buyer() -> None:
    directory = load_accounts(FIXTURES / "accounts.toml")
    values = _values(_run("runner"))

    assert values["ARKHAI_PAYMENTS__SERVICE_URL"] == "@str https://payments-double:8443"
    assert values["ARKHAI_PAYMENTS__SERVICE_IDENTITY"] == (
        f"@str {directory.receipt_identity.identifier}"
    )
    assert values["ARKHAI_PAYMENTS__FEE_BPS"] == str(directory.fee_bps)
    assert values["ARKHAI_PAYMENTS__LIVEMODE"] == "false"
    assert values["ARKHAI_PAYMENTS__LANE_OWNED"] == "true"
    assert values["ARKHAI_PAYMENTS__BUYER_ACCOUNT"] == f"@str {directory.role('buyer').account}"
    assert values["ARKHAI_PAYMENTS__SELLER_ACCOUNT"] == f"@str {directory.role('seller').account}"
    # The token reaches the runner under the variable API_KEY_ENV names, and only there.
    assert values["ARKHAI_PAYMENTS__API_KEY_ENV"] == f"@str {lane_env.BUYER_API_KEY_ENV}"
    assert values[lane_env.BUYER_API_KEY_ENV] == directory.role("buyer").token
    assert [key for key, value in values.items()
            if value == directory.role("buyer").token] == [lane_env.BUYER_API_KEY_ENV]
    assert values["SSL_CERT_FILE"] == lane_env.CA_MOUNT


def test_the_service_url_is_a_name_the_certificate_covers_at_the_port_the_double_serves() -> None:
    leaf = x509.load_pem_x509_certificate((lane_env.PROJECT / "tls" / "double.pem").read_bytes())
    names = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    url = urlsplit(lane_env.SERVICE_URL)

    assert url.scheme == "https"
    assert url.hostname in names.get_values_for_type(x509.DNSName)
    assert url.port == PORT
