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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from market_identity import Identity, IdentityScheme

from src.settings import settings
from src.ssh_access import (
    AccessVerdict,
    assert_lease_key_unchanged,
    buyer_ssh_argv,
    freeze_lease_key,
    classify_ssh_probe,
    resolve_host_key_trust,
    run_ssh_probe,
)
from tests.e2e.roles.buyer_cli import BuyerCli, create_profiled_buyer_cli
from tests.e2e.roles.helpers.domain_deal import (
    DealStage,
    DomainDealState,
    assert_market_run_succeeded,
    ordered_event_groups,
)

pytestmark = pytest.mark.e2e_bare_metal_deal

_ACCESS_PROOF_COMMAND = "printf arkhai-bare-metal-access-ok"
_ACCESS_PROOF_OUTPUT = "arkhai-bare-metal-access-ok"

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


def _require_input(message: str) -> None:
    """Absent acceptance inputs skip by default and block when selected.

    An ordinary suite run may reasonably exclude this scenario. An explicitly
    selected acceptance lane may not report success having exercised nothing,
    so `BARE_METAL.REQUIRE_ACCEPTANCE_LANE` turns every missing input into a
    failure.
    """
    if _setting("REQUIRE_ACCEPTANCE_LANE", False):
        raise AssertionError(f"acceptance lane is blocked: {message}")
    pytest.skip(message)


def _require_bare_metal_plugin() -> None:
    installed = {item.name for item in entry_points().select(group="market.buyer_domains")}
    if "bare-metal" not in installed:
        _require_input(
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


def _access_endpoint(access: dict[str, Any]) -> tuple[str, int, str]:
    host = str(access.get("host") or "")
    username = str(access.get("username") or "")
    port = int(access.get("port") or 22)
    if not host or not username:
        raise AssertionError("authenticated access view omitted host or username")
    return host, port, username


def _buyer_ssh(
    access: dict[str, Any],
    *,
    private_key_file: Path,
    known_hosts_file: Path,
    strict_host_key_checking: str,
    command: str = _ACCESS_PROOF_COMMAND,
):
    """Run one buyer SSH attempt using only the lease's own key."""
    host, port, username = _access_endpoint(access)
    return run_ssh_probe(
        buyer_ssh_argv(
            host=host,
            port=port,
            username=username,
            private_key_file=str(private_key_file),
            known_hosts_file=str(known_hosts_file),
            strict_host_key_checking=strict_host_key_checking,
            command=command,
        )
    )


@pytest.fixture(scope="module")
def bare_metal_buyer_cli(buyer_cli_binary, tmp_path_factory) -> BuyerCli:
    _require_bare_metal_plugin()
    registry_url = str(_setting("REGISTRY_URL") or "")
    if not registry_url:
        _require_input("BARE_METAL.REGISTRY_URL is not configured")
    registry_authority = str(_setting("REGISTRY_AUTHORITY") or "")
    raw_registry_principals = _setting("REGISTRY_PRINCIPALS", [])
    try:
        registry_principals = tuple(
            Identity.model_validate(dict(value)) for value in raw_registry_principals
        )
    except (TypeError, ValueError) as exc:
        _require_input(f"BARE_METAL.REGISTRY_PRINCIPALS is invalid: {exc}")
    if not registry_authority or not registry_principals:
        _require_input("BARE_METAL.REGISTRY_AUTHORITY and REGISTRY_PRINCIPALS are not configured")
    credential_variable = str(
        _setting(
            "BUYER_CREDENTIAL_ENVIRONMENT",
            "ARKHAI_E2E_BARE_METAL_MARKETPLACE_CREDENTIAL",
        )
    )
    credential = os.environ.get(credential_variable, "")
    if not credential:
        _require_input(f"{credential_variable} is not injected")

    yield create_profiled_buyer_cli(
        base_env=_buyer_environment(),
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
def management_reachability_probe() -> list[str]:
    """An operator-owned command proving the host's own access path survived.

    Deliberately not derived from the buyer's session: the buyer's credential,
    account, and endpoint are all the subject of the test, so reusing any of
    them could report the lease's own state as management health. The command
    runs with the operator's ambient credentials and this scenario never reads
    them.
    """
    raw = str(_setting("MANAGEMENT_PROBE_COMMAND") or "")
    if not raw:
        _require_input(
            "BARE_METAL.MANAGEMENT_PROBE_COMMAND must name an operator-owned "
            "command that proves host management access independently of the "
            "buyer lease"
        )
    argv = shlex.split(raw)
    buyer_credentials = {
        os.environ.get("ARKHAI_E2E_BARE_METAL_SSH_PRIVATE_KEY_FILE", ""),
        str(
            _setting(
                "BUYER_CREDENTIAL_ENVIRONMENT",
                "ARKHAI_E2E_BARE_METAL_MARKETPLACE_CREDENTIAL",
            )
        ),
    } - {""}
    borrowed = sorted(
        credential
        for credential in buyer_credentials
        if any(credential in part for part in argv)
    )
    if borrowed:
        raise AssertionError(
            "management probe must not reuse the buyer's lease credentials; it "
            "would then report the lease's own state as management health"
        )
    return argv


@pytest.fixture(scope="module")
def bare_metal_publication_command() -> list[str]:
    """Operator publication round used to re-advertise released capacity.

    Republication is not automatic. The seller runs one authenticated
    publication round, so relisting is proved by invoking that operator step
    explicitly and then observing the public registry, rather than by waiting
    for something the system does not do on its own.
    """
    raw = str(_setting("PUBLISH_COMMAND") or "")
    if not raw:
        _require_input(
            "BARE_METAL.PUBLISH_COMMAND must name the operator publication "
            "round; capacity relisting cannot be evidenced without it"
        )
    return shlex.split(raw)


@pytest.fixture(scope="module")
def bare_metal_ssh_private_key() -> Path:
    """Preflight the role-scoped access credential before any market effect."""
    file_name = os.environ.get(
        "ARKHAI_E2E_BARE_METAL_SSH_PRIVATE_KEY_FILE",
        "",
    )
    path = Path(file_name)
    if not file_name or not path.is_file():
        _require_input(
            "ARKHAI_E2E_BARE_METAL_SSH_PRIVATE_KEY_FILE is not an available "
            "role-scoped credential"
        )
    return path


def _buyer_environment() -> dict[str, str]:
    """The environment the buyer process starts from.

    An allowlist rather than a filtered copy of the operator's environment: a
    filter has to predict every name worth removing. The buyer's own credential
    is added separately by `BuyerCli`.
    """
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": os.environ.get("LANG", "C"),
    }


def _run_publication(publication_command: list[str]) -> None:
    """One operator publication round.

    The storefront closes listings whose capacity is no longer available during
    this command; fulfillment does not touch the registry. So the round has to
    run while the host is leased for its listing to disappear, and again after
    teardown for it to come back.
    """
    published = subprocess.run(
        publication_command,
        capture_output=True,
        text=True,
        timeout=float(_setting("PUBLISH_TIMEOUT_SECONDS", 300)),
        env=dict(os.environ),
    )
    if published.returncode != 0:
        raise AssertionError(
            "operator publication round failed; its output is withheld here "
            "because it is operator diagnostics rather than public evidence"
        )


def _requested_public_key(buy_args: list[str]) -> str | None:
    """The public key the buy command asks the seller to authorize.

    Read from the buyer's own `--ssh-public-key-file` argument, so the freeze
    check compares the held private key against what was actually requested
    rather than against a second copy of the same input.
    """
    for index, argument in enumerate(buy_args):
        if argument == "--ssh-public-key-file" and index + 1 < len(buy_args):
            return Path(buy_args[index + 1]).read_text(encoding="utf-8").strip()
        if argument.startswith("--ssh-public-key-file="):
            return Path(argument.split("=", 1)[1]).read_text(encoding="utf-8").strip()
    return None


def _request_teardown(cli: BuyerCli, run_id: str) -> dict[str, Any] | None:
    """Best-effort teardown used when the scenario is failing.

    Never raises: it runs in a `finally` whose job is to avoid leaving a host
    leased, and it must not replace the original failure with its own.
    """
    try:
        return _json_result(
            cli.run(["bare-metal", "teardown", "request", "--from", run_id, "--json"]),
            command="market bare-metal teardown request",
        )
    except Exception:
        return None


def test_bare_metal_complete_deal(
    bare_metal_buyer_cli: BuyerCli,
    bare_metal_ssh_private_key: Path,
    management_reachability_probe: list[str],
    bare_metal_publication_command: list[str],
    tmp_path: Path,
) -> None:
    raw_buy_args = str(_setting("BUY_ARGS") or "")
    if not raw_buy_args:
        _require_input(
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

    # Everything that can fail without spending anything is checked first.
    # The buyer names the public key it is asking the seller to authorize; the
    # private key held here must be that key's counterpart, or a later refusal
    # would say nothing about the lease that was actually granted.
    lease_key = freeze_lease_key(
        bare_metal_ssh_private_key,
        expected_public_key=_requested_public_key(buy_args),
    )
    operator_known_hosts = str(_setting("KNOWN_HOSTS_FILE") or "")
    trust = resolve_host_key_trust(
        known_hosts_file=Path(operator_known_hosts) if operator_known_hosts else None,
        session_known_hosts=tmp_path / "known_hosts",
    )
    known_hosts_file = trust.known_hosts_file
    if not trust.independently_verified:
        print(f"[bare-metal e2e] host key trust: {trust.caveat}")
    if _setting("REQUIRE_VERIFIED_HOST_KEY", False) and not trust.independently_verified:
        raise AssertionError(
            "this lane requires an operator-managed known_hosts file; first-use "
            "acceptance is a lower-assurance mode and is not acceptance evidence"
        )

    buy = bare_metal_buyer_cli.run(
        ["bare-metal", "buy", *buy_args],
        timeout=float(_setting("DEAL_TIMEOUT_SECONDS", 900)),
    )
    teardown_needed = True
    try:
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
            bare_metal_buyer_cli.run(
                ["bare-metal", "result", "--from", buy.run_id, "--json"]
            ),
            command="market bare-metal result",
        )
        state.complete(DealStage.DELIVERY, delivery=result)
        leased = _leased_host(result)

        # The listing published before the purchase stays open until an
        # operator publication round reconciles it against current capacity, so
        # run that round first. Without it the host would still look purchasable
        # while leased, and its later reappearance would prove nothing.
        _run_publication(bare_metal_publication_command)
        occupied_before_teardown = not _purchasable_offers(
            bare_metal_buyer_cli, leased
        )

        access = _json_result(
            bare_metal_buyer_cli.run(
                ["bare-metal", "access", "--from", buy.run_id, "--json"]
            ),
            command="market bare-metal access",
        )

        assert_lease_key_unchanged(lease_key)
        first_access = _buyer_ssh(
            access,
            private_key_file=lease_key.private_key_file,
            known_hosts_file=known_hosts_file,
            strict_host_key_checking=trust.strict_host_key_checking,
        )
        assert classify_ssh_probe(
            first_access, offered_fingerprint=lease_key.fingerprint
        ) is AccessVerdict.GRANTED, "granted lease did not admit the buyer key"
        assert first_access.stdout == _ACCESS_PROOF_OUTPUT
        assert known_hosts_file.is_file() and known_hosts_file.read_text().strip(), (
            "no host key is pinned, so later probes cannot verify the same host"
        )

        _json_result(
            bare_metal_buyer_cli.run(
                ["bare-metal", "teardown", "request", "--from", buy.run_id, "--json"]
            ),
            command="market bare-metal teardown request",
        )
        teardown_needed = False
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

        # The same key must still be readable, or a denial below could mean the
        # credential vanished rather than that the authority withdrew it.
        assert_lease_key_unchanged(lease_key)
        revoked_access = _buyer_ssh(
            access,
            private_key_file=lease_key.private_key_file,
            known_hosts_file=known_hosts_file,
            strict_host_key_checking="yes",
        )
        verdict = classify_ssh_probe(
            revoked_access, offered_fingerprint=lease_key.fingerprint
        )
        if verdict is AccessVerdict.GRANTED:
            raise AssertionError("SSH access survived authoritative teardown")
        # KEY_REJECTED is only reached when the pinned host answered and refused
        # this exact offered key, so it already carries reachability and host
        # identity. Every other verdict is reported as itself.
        assert verdict is AccessVerdict.KEY_REJECTED, (
            "teardown did not produce an authentication refusal for the lease "
            f"key (verdict={verdict.value})"
        )

        # Checked after revocation and outside the buyer session: reclaim edits
        # accounts and authorized_keys on a real host, and the operator path
        # must be observably untouched by that.
        management = subprocess.run(
            management_reachability_probe,
            capture_output=True,
            text=True,
            timeout=float(_setting("MANAGEMENT_PROBE_TIMEOUT_SECONDS", 60)),
            env=dict(os.environ),
        )
        assert management.returncode == 0, (
            "host management access did not survive bare-metal teardown"
        )

        state.complete(DealStage.TEARDOWN, teardown=teardown)
        state.assert_complete()

        _assert_capacity_relisted(
            bare_metal_buyer_cli,
            publication_command=bare_metal_publication_command,
            leased=leased,
            occupied_before_teardown=occupied_before_teardown,
        )
    finally:
        # A failure between purchase and teardown would otherwise leave a real
        # host leased. Requested without raising so the original failure stands.
        if teardown_needed:
            _request_teardown(bare_metal_buyer_cli, buy.run_id)


@dataclass(frozen=True)
class LeasedHost:
    """The exact whole host a deal bound, as both of its identity fields.

    Kept as a pair rather than a set of interchangeable strings: a machine id is
    executor-local and a physical host id is the cross-mode identity, so a
    listing whose machine id happens to equal another host's physical id is a
    different resource, not a match.
    """

    machine_id: str
    physical_host_id: str


def _leased_host(view: dict[str, Any]) -> LeasedHost:
    machine_id = str(view.get("machine_id") or "")
    physical_host_id = str(view.get("physical_host_id") or "")
    if not machine_id or not physical_host_id:
        raise AssertionError(
            "fulfillment result did not expose both host identity fields, so a "
            "relisted offer cannot be correlated to the host that was leased"
        )
    return LeasedHost(machine_id=machine_id, physical_host_id=physical_host_id)


def _purchasable_offers(cli: BuyerCli, leased: LeasedHost) -> list[dict[str, Any]]:
    """Listings for exactly this host that a buyer could still purchase.

    Reads the buyer CLI's declared envelope: `bare-metal list` serializes a
    `ListingListResponse`, whose records live under `listings` and carry their
    domain facts nested under `offer`.
    """
    limit = int(_setting("LIST_PAGE_LIMIT", 200))
    listed = _json_result(
        cli.run(["bare-metal", "list", "--limit", str(limit)]),
        command="market bare-metal list",
    )
    records = listed.get("listings")
    if not isinstance(records, list):
        raise AssertionError(
            "market bare-metal list did not return its declared listings envelope"
        )
    total = listed.get("total")
    if isinstance(total, int) and total > len(records):
        raise AssertionError(
            f"registry reported {total} listings but only {len(records)} were "
            "read; raise BARE_METAL.LIST_PAGE_LIMIT rather than judging "
            "availability from a partial page"
        )

    matches: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        offer = record.get("offer")
        if not isinstance(offer, dict):
            continue
        if (
            str(offer.get("machine_id") or "") != leased.machine_id
            or str(offer.get("physical_host_id") or "") != leased.physical_host_id
        ):
            continue
        status = str(record.get("status") or "").lower()
        if status and status not in {"open", "available", "active"}:
            continue
        # A listing with no settlement option cannot be bought, so its presence
        # is not the capacity being purchasable again.
        if not record.get("settlement_options"):
            continue
        matches.append(record)
    return matches


def _assert_capacity_relisted(
    cli: BuyerCli,
    *,
    publication_command: list[str],
    leased: LeasedHost,
    occupied_before_teardown: bool,
) -> None:
    """Prove released capacity returns to public discovery as purchasable.

    Republication is an operator action, not something the marketplace does on
    its own, so the operator's own publication round is invoked here and the
    result is then observed from the buyer's public view. Calling this
    "automatic relisting" would misdescribe the system.
    """
    if not occupied_before_teardown:
        raise AssertionError(
            "the leased host was still publicly purchasable while under lease, "
            "so its reappearance afterwards would prove nothing about release"
        )

    _run_publication(publication_command)

    deadline = time.monotonic() + float(_setting("RELIST_TIMEOUT_SECONDS", 180))
    while time.monotonic() < deadline:
        if _purchasable_offers(cli, leased):
            return
        time.sleep(float(_setting("POLL_INTERVAL_SECONDS", 2)))
    raise AssertionError(
        f"released whole host {leased.machine_id!r} was not offered again as a "
        "purchasable listing after the operator publication round"
    )
