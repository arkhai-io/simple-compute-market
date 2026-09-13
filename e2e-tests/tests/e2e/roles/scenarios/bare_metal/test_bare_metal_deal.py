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

# One remote command, reporting what the buyer's own session is. A marker the
# command prints back only proves SSH succeeded; the lease is also required to
# be an ordinary account, so the identity and the sudo answer are read in the
# same session rather than inferred from how the account was created.
_ACCESS_PROOF_COMMAND = (
    "printf 'arkhai-uid=%s\\n' \"$(id -u)\"; "
    "printf 'arkhai-groups=%s\\n' \"$(id -Gn)\"; "
    "if sudo -n true >/dev/null 2>&1; "
    "then printf 'arkhai-sudo=granted\\n'; "
    "else printf 'arkhai-sudo=refused\\n'; fi"
)

# Membership of any of these is a privilege grant on a Debian-family host:
# `docker` and `lxd` are root-equivalent because their sockets can start a
# container that mounts the host filesystem.
_PRIVILEGED_GROUPS = frozenset(
    {"root", "sudo", "wheel", "admin", "adm", "docker", "lxd"}
)

# The bare-metal plugin reads its own configuration file by environment
# variable; the shared `--config` flag only reaches the core loader.
_BUYER_CONFIG_VARIABLE = "BARE_METAL_BUYER_CONFIG"

# Where this scenario reads the buyer's escrow funding key from, and the
# default name `bare-metal fund` reads it under. Exactly one secret is copied
# between them: the buyer process never inherits the operator's environment,
# and a key passed in argv would be visible to every account on this machine.
_FUNDING_KEY_SOURCE_VARIABLE = "ARKHAI_E2E_BARE_METAL_EVM_PRIVATE_KEY"
_DEFAULT_FUNDING_KEY_VARIABLE = "BARE_METAL_BUYER_EVM_PRIVATE_KEY"

# States from which a lease will not become active. The buyer CLI's own hosted
# wait ends on this set, and a poll that treated them as "not yet" would report
# a reported failure as a timeout.
_TERMINAL_FAILURE_STATES = frozenset(
    {"failed", "teardown_failed", "torn_down", "released"}
)

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


@dataclass(frozen=True)
class AccessProof:
    """What the buyer's own SSH session reported about itself."""

    uid: int
    groups: tuple[str, ...]
    sudo_granted: bool


def _parse_access_proof(stdout: str) -> AccessProof:
    """Read the proof lines, refusing anything incomplete.

    A partial answer fails rather than defaulting: a session that printed only
    some of these lines has not shown it is unprivileged, and treating a missing
    `arkhai-sudo` line as "no sudo" would turn a broken probe into a pass.
    """
    fields: dict[str, str] = {}
    for line in stdout.splitlines():
        key, separator, value = line.strip().partition("=")
        if separator and key.startswith("arkhai-"):
            fields[key] = value
    missing = sorted(
        {"arkhai-uid", "arkhai-groups", "arkhai-sudo"} - set(fields)
    )
    if missing:
        raise AssertionError(
            f"buyer session did not report {', '.join(missing)}; its privilege "
            "level is unknown, which is not the same as unprivileged"
        )
    try:
        uid = int(fields["arkhai-uid"])
    except ValueError as exc:
        raise AssertionError("buyer session reported a non-numeric uid") from exc
    sudo = fields["arkhai-sudo"]
    if sudo not in {"granted", "refused"}:
        raise AssertionError(f"buyer session reported an unknown sudo answer {sudo!r}")
    return AccessProof(
        uid=uid,
        groups=tuple(fields["arkhai-groups"].split()),
        sudo_granted=sudo == "granted",
    )


def _assert_unprivileged_buyer_session(proof: AccessProof) -> None:
    """The lease must be an ordinary account, not an administrator."""
    if proof.uid == 0:
        raise AssertionError("the buyer's lease session is root")
    privileged = sorted(_PRIVILEGED_GROUPS.intersection(proof.groups))
    if privileged:
        raise AssertionError(
            f"the buyer's lease account holds privileged groups: {privileged}"
        )
    if proof.sudo_granted:
        raise AssertionError("the buyer's lease account was granted sudo")


@pytest.fixture(scope="module")
def bare_metal_buyer_cli(
    buyer_cli_binary, tmp_path_factory, settle_command: list[str]
) -> BuyerCli:
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
        base_env=_buyer_environment(settle_command),
        config_path_variables=(_BUYER_CONFIG_VARIABLE,),
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
            *_buyer_chain_sections(settle_command),
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
def settle_command() -> list[str]:
    """The rail's own settlement command, run after `buy` negotiates.

    Named rather than inferred: the crypto lane funds an escrow on chain
    (`bare-metal fund`) and the hosted lane authorizes an instrument
    (`bare-metal complete`). Choosing one silently would let a lane that was
    configured for the other report a purchase it never made.
    """
    raw = str(_setting("SETTLE_COMMAND") or "")
    if not raw:
        _require_input(
            "BARE_METAL.SETTLE_COMMAND must name the settlement command for the "
            "selected rail; a negotiated agreement is not a purchase"
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


def _is_crypto_settlement(settle_command: list[str]) -> bool:
    """Whether the selected rail funds an escrow on chain."""
    return settle_command[:2] == ["bare-metal", "fund"]


def _funding_key_variable(settle_command: list[str]) -> str:
    """The variable `bare-metal fund` will read its funding key from.

    Taken from the command's own `--private-key-env` when it names one, so a
    lane that renames the variable still receives the key.
    """
    for index, argument in enumerate(settle_command):
        if argument == "--private-key-env" and index + 1 < len(settle_command):
            return settle_command[index + 1]
        if argument.startswith("--private-key-env="):
            return argument.split("=", 1)[1]
    return _DEFAULT_FUNDING_KEY_VARIABLE


def _buyer_environment(settle_command: list[str]) -> dict[str, str]:
    """The environment the buyer process starts from.

    An allowlist rather than a filtered copy of the operator's environment: a
    filter has to predict every name worth removing. The buyer's own marketplace
    credential is added separately by `BuyerCli`, and the funding key is added
    here only for the rail that spends it, so a hosted lane is never required to
    hold an EVM secret.
    """
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": os.environ.get("LANG", "C"),
    }
    if _is_crypto_settlement(settle_command):
        funding_key = os.environ.get(_FUNDING_KEY_SOURCE_VARIABLE, "").strip()
        if not funding_key:
            _require_input(
                f"{_FUNDING_KEY_SOURCE_VARIABLE} must hold the buyer's escrow "
                "funding key for the crypto settlement rail"
            )
        environment[_funding_key_variable(settle_command)] = funding_key
    return environment


def _buyer_chain_sections(settle_command: list[str]) -> tuple[str, ...]:
    """The one `[chains.<name>]` table the crypto rail reads.

    `buy` resolves the address set for the chain it is about to propose on, and
    `fund` resolves the RPC to create the escrow. Both read the same shared
    loader, so the chain has to be in the file this scenario generates rather
    than in whatever config the operator happens to have.
    """
    if not _is_crypto_settlement(settle_command):
        return ()
    name = str(_setting("BUYER_CHAIN_NAME") or "").strip()
    rpc_url = str(_setting("BUYER_CHAIN_RPC_URL") or "").strip()
    if not name or not rpc_url:
        _require_input(
            "BARE_METAL.BUYER_CHAIN_NAME and BARE_METAL.BUYER_CHAIN_RPC_URL "
            "must name the chain the seller advertises; the crypto rail cannot "
            "propose or fund an escrow without them"
        )
    if not all(character.isalnum() or character in "_-" for character in name):
        raise AssertionError(
            f"BARE_METAL.BUYER_CHAIN_NAME {name!r} is not a bare TOML key, so it "
            "would not be read back as the chain the listing names"
        )
    lines = [
        "",
        f"[chains.{name}]",
        f"rpc_url = {json.dumps(rpc_url)}",
    ]
    chain_id = int(_setting("BUYER_CHAIN_ID", 0) or 0)
    if chain_id:
        lines.append(f"chain_id = {chain_id}")
    address_config_path = str(
        _setting("BUYER_ALKAHEST_ADDRESS_CONFIG_PATH") or ""
    ).strip()
    if address_config_path:
        # Deployed addresses for a development chain are not bundled, and an
        # unreadable file would silently fall back to the bundled set — a
        # different set of contracts than the operator deployed.
        if not Path(address_config_path).is_file():
            _require_input(
                "BARE_METAL.BUYER_ALKAHEST_ADDRESS_CONFIG_PATH is not a readable "
                f"file: {address_config_path}"
            )
        lines.append(
            "alkahest_address_config_path = " + json.dumps(address_config_path)
        )
    return tuple(lines)


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


def _assert_discovered_from_the_trusted_registry(started: dict[str, Any]) -> None:
    """The purchased listing came from the configured authenticated registry.

    `buy` records the registry it read, the listing it read, and the publisher
    principals that listing was signed under, all from the authenticated
    response. Checking those is what makes this a discovery assertion rather
    than an assertion that some command ran.
    """
    registry_url = str(_setting("REGISTRY_URL") or "").rstrip("/")
    registry_authority = str(_setting("REGISTRY_AUTHORITY") or "")
    if str(started.get("source_registry_url") or "").rstrip("/") != registry_url:
        raise AssertionError(
            "the purchased listing did not come from the configured registry"
        )
    if str(started.get("source_registry_authority") or "") != registry_authority:
        raise AssertionError(
            "the purchased listing was not read under the configured registry "
            "authority"
        )
    for field in ("listing_id", "storefront_url", "publisher_id"):
        if not started.get(field):
            raise AssertionError(f"discovery recorded no {field}")
    principals = (started.get("publisher_principals") or {}).get("identities")
    if not principals:
        raise AssertionError(
            "the listing carried no publisher principals, so nothing binds the "
            "seller that was negotiated with to the listing that was discovered"
        )


def _fulfillment_state(view: dict[str, Any]) -> str:
    """The physical state out of `market bare-metal status`'s envelope.

    That command emits `{"fulfillment": <projection>}`, with a `settlement` key
    beside it on the hosted rail. A missing key is an error rather than an empty
    string: reading an unreadable projection as "not yet" turns a converged
    lease into a timeout.
    """
    fulfillment = view.get("fulfillment")
    if not isinstance(fulfillment, dict) or "state" not in fulfillment:
        raise AssertionError(
            "bare-metal status did not return its declared fulfillment projection"
        )
    return str(fulfillment.get("state") or "")


def _await_fulfillment_state(
    cli: BuyerCli,
    run_id: str,
    *,
    target: str,
    failure_states: frozenset[str],
    timeout_seconds: float,
) -> dict[str, Any]:
    """Poll the physical projection until it reaches *target*.

    The settlement command returns once fulfillment has begun, not once the host
    is provisioned. A terminal failure ends the wait immediately: polling on
    would report it as a timeout instead.
    """
    deadline = time.monotonic() + timeout_seconds
    observed = ""
    while True:
        view = _json_result(
            cli.run(["bare-metal", "status", "--run-id", run_id]),
            command="market bare-metal status",
        )
        observed = _fulfillment_state(view)
        if observed == target:
            return view
        if observed in failure_states:
            raise AssertionError(
                f"bare-metal fulfillment ended in state {observed!r} while "
                f"waiting for {target!r}"
            )
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"bare-metal fulfillment did not reach {target!r} before timeout "
                f"(last state {observed!r})"
            )
        time.sleep(float(_setting("POLL_INTERVAL_SECONDS", 2)))


def _request_teardown(cli: BuyerCli, run_id: str) -> dict[str, Any] | None:
    """Best-effort teardown used when the scenario is failing.

    Never raises: it runs in a `finally` whose job is to avoid leaving a host
    leased, and it must not replace the original failure with its own.
    """
    try:
        return _json_result(
            cli.run(["bare-metal", "teardown", "--run-id", run_id]),
            command="market bare-metal teardown request",
        )
    except Exception:
        return None


def test_bare_metal_complete_deal(
    settle_command: list[str],
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
        started, _accepted, _ended = ordered_event_groups(
            buy.read_events(),
            ("run_started",),
            ("agreement_accepted",),
            ("run_ended",),
        )
        _assert_discovered_from_the_trusted_registry(started)

        state = DomainDealState(domain_identity="bare_metal.v1")
        state.complete(DealStage.DISCOVERY)
        state.complete(DealStage.NEGOTIATION)

        # `buy` negotiates and stops. Nothing is funded, verified or reserved
        # until the rail's own settlement command runs, so a lane that went
        # straight to `result` here would be asserting delivery of a lease
        # nobody paid for.
        _json_result(
            bare_metal_buyer_cli.run(
                [*settle_command, "--run-id", buy.run_id],
                timeout=float(_setting("SETTLE_TIMEOUT_SECONDS", 900)),
            ),
            command="market " + " ".join(settle_command),
        )
        ordered_event_groups(
            buy.read_events(),
            ("agreement_accepted",),
            (
                "escrow_created",
                "settlement_submitted",
                "settlement_started",
            ),
            ("settlement_verified", "settlement_completed"),
        )
        state.complete(DealStage.SETTLEMENT)

        # The settlement command returns once fulfillment has begun, which is
        # earlier than the host being usable. Reading the result or the access
        # coordinates before the lease is active would report provisioning
        # state as delivery.
        _await_fulfillment_state(
            bare_metal_buyer_cli,
            buy.run_id,
            target=str(_setting("ACTIVE_FULFILLMENT_STATE", "active")),
            failure_states=_TERMINAL_FAILURE_STATES,
            timeout_seconds=float(_setting("PROVISIONING_TIMEOUT_SECONDS", 900)),
        )

        result = _json_result(
            bare_metal_buyer_cli.run(
                ["bare-metal", "result", "--run-id", buy.run_id]
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
                ["bare-metal", "access", "--run-id", buy.run_id]
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
        # Judged before teardown: afterwards the lease key is refused, so this
        # session cannot be re-entered to establish what it was allowed to do.
        _assert_unprivileged_buyer_session(_parse_access_proof(first_access.stdout))
        assert known_hosts_file.is_file() and known_hosts_file.read_text().strip(), (
            "no host key is pinned, so later probes cannot verify the same host"
        )

        _json_result(
            bare_metal_buyer_cli.run(
                ["bare-metal", "teardown", "--run-id", buy.run_id]
            ),
            command="market bare-metal teardown request",
        )
        teardown_needed = False
        terminal_state = str(_setting("TERMINAL_TEARDOWN_STATE", "released"))
        teardown = _await_fulfillment_state(
            bare_metal_buyer_cli,
            buy.run_id,
            target=terminal_state,
            # `teardown_failed` is terminal here rather than a failure to wait
            # through: the release did not happen and polling on would only
            # report it as a timeout.
            failure_states=frozenset({"failed", "teardown_failed"}),
            timeout_seconds=float(_setting("TEARDOWN_TIMEOUT_SECONDS", 300)),
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
    """The host identity out of `market bare-metal result`'s real envelope.

    That command returns the storefront's own result response — a negotiation
    id, the durable `receipt`, and the executor's `result` — so the identity
    fields live under `receipt`. The executor's view is required to name the
    same host: they are produced by different authorities, and a disagreement
    means the relisting check below would be correlating against the wrong one.
    """
    receipt = view.get("receipt")
    if not isinstance(receipt, dict):
        raise AssertionError(
            "fulfillment result carried no receipt, so the leased host is unknown"
        )
    machine_id = str(receipt.get("machine_id") or "")
    physical_host_id = str(receipt.get("physical_host_id") or "")
    if not machine_id or not physical_host_id:
        raise AssertionError(
            "fulfillment receipt did not expose both host identity fields, so a "
            "relisted offer cannot be correlated to the host that was leased"
        )
    executor = view.get("result")
    if isinstance(executor, dict):
        executor_machine = str(executor.get("machine_id") or "")
        executor_host = str(executor.get("physical_host_id") or "")
        if executor_machine and executor_machine != machine_id:
            raise AssertionError(
                "the receipt and the executor result name different machines"
            )
        if executor_host and executor_host != physical_host_id:
            raise AssertionError(
                "the receipt and the executor result name different physical hosts"
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
