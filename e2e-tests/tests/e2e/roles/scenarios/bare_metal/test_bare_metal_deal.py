"""Whole-host deal through the installed bare-metal buyer contribution.

The scenario uses only the core ``market`` executable and authenticated public
seller APIs exposed through that contribution. It never imports a storefront,
site, provisioning, executor, or settlement implementation.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

import pytest
from market_identity import Identity, IdentityScheme

from src.settings import settings
from tests.e2e.roles.buyer_cli import BuyerCli, create_profiled_buyer_cli
from tests.e2e.roles.helpers.domain_deal import (
    DealStage,
    DomainDealState,
    assert_market_run_succeeded,
    ordered_event_groups,
)

pytestmark = pytest.mark.e2e_bare_metal_deal

_FORBIDDEN_BUY_FLAGS = (
    "--access-ref",
    "--executor",
    "--host",
    "--password",
    "--private-key",
    "--provider",
    "--provisioning",
    "--resource",
    "--site",
)


def _setting(name: str, default: Any = "") -> Any:
    return settings.get(f"BARE_METAL.{name}", default)


def _require_bare_metal_plugin() -> None:
    installed = {item.name for item in entry_points().select(group="market.buyer_domains")}
    if "bare-metal" not in installed:
        pytest.skip(
            "arkhai-bare-metal-buyer entry point market.buyer_domains/bare-metal is not installed"
        )


def _json_result(run: Any, *, command: str) -> dict[str, Any]:
    assert_market_run_succeeded(run, command=command)
    try:
        value = json.loads(run.stdout())
    except json.JSONDecodeError as exc:
        raise AssertionError(f"{command} did not return its declared JSON view") from exc
    if not isinstance(value, dict):
        raise AssertionError(f"{command} returned a non-object JSON view")
    return value


def _ssh(
    access: dict[str, Any],
    *,
    private_key_file: Path,
    known_hosts_file: Path,
) -> subprocess.CompletedProcess[str]:
    host = str(access.get("host") or "")
    username = str(access.get("username") or "")
    port = int(access.get("port") or 22)
    if not host or not username:
        raise AssertionError("authenticated access view omitted host or username")
    return subprocess.run(
        [
            "ssh",
            "-i",
            str(private_key_file),
            "-p",
            str(port),
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            f"UserKnownHostsFile={known_hosts_file}",
            f"{username}@{host}",
            "printf arkhai-bare-metal-access-ok",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.fixture(scope="module")
def bare_metal_buyer_cli(buyer_cli_binary, tmp_path_factory) -> BuyerCli:
    _require_bare_metal_plugin()
    registry_url = str(_setting("REGISTRY_URL") or "")
    if not registry_url:
        pytest.skip("BARE_METAL.REGISTRY_URL is not configured")
    registry_authority = str(_setting("REGISTRY_AUTHORITY") or "")
    raw_registry_principals = _setting("REGISTRY_PRINCIPALS", [])
    try:
        registry_principals = tuple(
            Identity.model_validate(dict(value)) for value in raw_registry_principals
        )
    except (TypeError, ValueError) as exc:
        pytest.skip(f"BARE_METAL.REGISTRY_PRINCIPALS is invalid: {exc}")
    if not registry_authority or not registry_principals:
        pytest.skip("BARE_METAL.REGISTRY_AUTHORITY and REGISTRY_PRINCIPALS are not configured")
    credential_variable = str(
        _setting(
            "BUYER_CREDENTIAL_ENVIRONMENT",
            "ARKHAI_E2E_BARE_METAL_MARKETPLACE_CREDENTIAL",
        )
    )
    credential = os.environ.get(credential_variable, "")
    if not credential:
        pytest.skip(f"{credential_variable} is not injected")

    yield create_profiled_buyer_cli(
        binary=buyer_cli_binary,
        base=tmp_path_factory.mktemp("bare_metal_buyer_cli"),
        domain_identity="bare_metal.v1",
        marketplace_scheme=IdentityScheme.ED25519,
        marketplace_credential=credential,
        registries=(registry_url,),
        credential_variable=credential_variable,
        toml_sections=(
            "[bare_metal]",
            f"registry_url = {json.dumps(registry_url)}",
            f"registry_authority = {json.dumps(registry_authority)}",
            "registry_principals = ["
            + ", ".join(
                "{ scheme = "
                + json.dumps(principal.scheme.value)
                + ", identifier = "
                + json.dumps(principal.identifier)
                + " }"
                for principal in registry_principals
            )
            + "]",
        ),
    )


@pytest.fixture(scope="module")
def bare_metal_ssh_private_key() -> Path:
    """Preflight the role-scoped access credential before any market effect."""
    file_name = os.environ.get(
        "ARKHAI_E2E_BARE_METAL_SSH_PRIVATE_KEY_FILE",
        "",
    )
    path = Path(file_name)
    if not file_name or not path.is_file():
        pytest.skip(
            "ARKHAI_E2E_BARE_METAL_SSH_PRIVATE_KEY_FILE is not an available role-scoped credential"
        )
    return path


def test_bare_metal_complete_deal(
    bare_metal_buyer_cli: BuyerCli,
    bare_metal_ssh_private_key: Path,
    tmp_path: Path,
) -> None:
    raw_buy_args = str(_setting("BUY_ARGS") or "")
    if not raw_buy_args:
        pytest.skip(
            "BARE_METAL.BUY_ARGS must name the exact public duration, SSH public "
            "key, settlement selection, and non-interactive output flags"
        )
    buy_args = shlex.split(raw_buy_args)
    lowered = tuple(argument.lower() for argument in buy_args)
    forbidden = [
        flag
        for flag in _FORBIDDEN_BUY_FLAGS
        if any(argument == flag or argument.startswith(flag + "=") for argument in lowered)
    ]
    if forbidden:
        raise AssertionError(
            f"bare-metal buy input attempts seller-owned or secret fields: {forbidden}"
        )

    buy = bare_metal_buyer_cli.run(
        ["bare-metal", "buy", *buy_args],
        timeout=float(_setting("DEAL_TIMEOUT_SECONDS", 900)),
    )
    assert_market_run_succeeded(buy, command="market bare-metal buy")
    ordered_event_groups(
        buy.read_events(),
        ("discover",),
        ("negotiation_completed",),
        ("settlement_submitted", "settlement_started"),
        ("run_ended",),
    )

    state = DomainDealState(domain_identity="bare_metal.v1")
    state.complete(DealStage.DISCOVERY)
    state.complete(DealStage.NEGOTIATION)
    state.complete(DealStage.SETTLEMENT)

    result = _json_result(
        bare_metal_buyer_cli.run(["bare-metal", "result", "--from", buy.run_id, "--json"]),
        command="market bare-metal result",
    )
    state.complete(DealStage.DELIVERY, delivery=result)

    access = _json_result(
        bare_metal_buyer_cli.run(["bare-metal", "access", "--from", buy.run_id, "--json"]),
        command="market bare-metal access",
    )
    known_hosts_file = tmp_path / "known_hosts"
    first_access = _ssh(
        access,
        private_key_file=bare_metal_ssh_private_key,
        known_hosts_file=known_hosts_file,
    )
    assert first_access.returncode == 0
    assert first_access.stdout == "arkhai-bare-metal-access-ok"

    _json_result(
        bare_metal_buyer_cli.run(
            ["bare-metal", "teardown", "request", "--from", buy.run_id, "--json"]
        ),
        command="market bare-metal teardown request",
    )
    terminal_status = str(_setting("TERMINAL_TEARDOWN_STATUS", "released"))
    deadline = time.monotonic() + float(_setting("TEARDOWN_TIMEOUT_SECONDS", 300))
    teardown: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        teardown = _json_result(
            bare_metal_buyer_cli.run(
                [
                    "bare-metal",
                    "teardown",
                    "status",
                    "--from",
                    buy.run_id,
                    "--json",
                ]
            ),
            command="market bare-metal teardown status",
        )
        if teardown.get("status") == terminal_status:
            break
        time.sleep(float(_setting("POLL_INTERVAL_SECONDS", 2)))
    else:
        raise AssertionError(
            f"bare-metal teardown did not reach {terminal_status!r} before timeout"
        )

    revoked_access = _ssh(
        access,
        private_key_file=bare_metal_ssh_private_key,
        known_hosts_file=known_hosts_file,
    )
    assert revoked_access.returncode != 0, "SSH access survived authoritative teardown"
    state.complete(DealStage.TEARDOWN, teardown=teardown)
    state.assert_complete()
