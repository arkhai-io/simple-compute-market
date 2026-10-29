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
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

import pytest
from market_identity import Identity, IdentityScheme

from e2e_harness.settings import settings
from tests.e2e.roles.buyer_cli import BuyerCli, create_profiled_buyer_cli
from tests.e2e.roles.helpers.bare_metal_access import (
    SshOutcome,
    assert_purchase_recorded,
    classify_ssh,
    forbidden_flags,
    recovery_command,
    ssh_command,
    wait_for_release,
)
from tests.e2e.roles.helpers.domain_deal import (
    DealStage,
    DomainDealState,
    assert_market_run_succeeded,
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
) -> SshOutcome:
    attempt = subprocess.run(
        ssh_command(
            access,
            private_key_file=private_key_file,
            known_hosts_file=known_hosts_file,
        ),
        capture_output=True,
        text=True,
        timeout=30,
    )
    return classify_ssh(attempt.returncode, attempt.stdout, attempt.stderr)


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


@pytest.fixture(scope="module")
def bare_metal_known_hosts() -> Path:
    """The operator's pinned host key for the delivered host, before any market effect.

    Revocation is proven only by that host refusing the key, so the scenario never
    learns a host key on first contact.
    """
    file_name = os.environ.get("ARKHAI_E2E_BARE_METAL_KNOWN_HOSTS_FILE", "")
    path = Path(file_name)
    if not file_name or not path.is_file():
        pytest.skip(
            "ARKHAI_E2E_BARE_METAL_KNOWN_HOSTS_FILE does not name the delivered "
            "host's pinned known-hosts file"
        )
    return path


def test_bare_metal_complete_deal(
    bare_metal_buyer_cli: BuyerCli,
    bare_metal_ssh_private_key: Path,
    bare_metal_known_hosts: Path,
) -> None:
    raw_buy_args = str(_setting("BUY_ARGS") or "")
    if not raw_buy_args:
        pytest.skip(
            "BARE_METAL.BUY_ARGS must name the listing, its Arkhai payments "
            "--option-id, the --ssh-public-key, and the --duration-seconds"
        )
    buy_args = shlex.split(raw_buy_args)
    forbidden = forbidden_flags(buy_args, _FORBIDDEN_BUY_FLAGS)
    if forbidden:
        raise AssertionError(
            f"bare-metal buy input attempts seller-owned or secret fields: {forbidden}"
        )

    buy = bare_metal_buyer_cli.run(
        ["bare-metal", "buy", *buy_args],
        timeout=float(_setting("DEAL_TIMEOUT_SECONDS", 900)),
    )
    bought = _json_result(buy, command="market bare-metal buy")
    # buy prints the id of the run log it wrote; every recovery reads that log.
    run_id = buy.run_id
    assert bought.get("run_id") == run_id, "buy printed another run than it recorded"
    assert_purchase_recorded(buy.read_events())

    state = DomainDealState(domain_identity="bare_metal.v1")
    state.complete(DealStage.DISCOVERY)
    state.complete(DealStage.NEGOTIATION)
    state.complete(DealStage.SETTLEMENT)

    def recover(command: str) -> dict[str, Any]:
        return _json_result(
            bare_metal_buyer_cli.run(recovery_command(command, run_id)),
            command=f"market bare-metal {command}",
        )

    state.complete(DealStage.DELIVERY, delivery=recover("result"))

    access = recover("access")
    first_access = _ssh(
        access,
        private_key_file=bare_metal_ssh_private_key,
        known_hosts_file=bare_metal_known_hosts,
    )
    assert first_access is SshOutcome.ACCEPTED

    teardown = wait_for_release(
        lambda: recover("teardown"),
        timeout_seconds=float(_setting("TEARDOWN_TIMEOUT_SECONDS", 300)),
        poll_interval_seconds=float(_setting("POLL_INTERVAL_SECONDS", 2)),
    )

    revoked_access = _ssh(
        access,
        private_key_file=bare_metal_ssh_private_key,
        known_hosts_file=bare_metal_known_hosts,
    )
    assert revoked_access is SshOutcome.REFUSED, "SSH access survived authoritative teardown"
    state.complete(DealStage.TEARDOWN, teardown=teardown)
    state.assert_complete()
