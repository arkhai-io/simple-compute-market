"""The bare-metal buyer process receives its config and its funding key.

The scenario's own fixture body runs here, and the environment asserted on is
the one a real subprocess was started with: the binary is a script that prints
its environment, so a name the fixture forgot to export cannot pass. The
generated file is then read back through the shared `market_config` loader the
buyer uses, not re-parsed by this test.

Only two seams are substituted: the installed-plugin check (a distribution fact,
not a composition fact) and the `market` binary itself. Nothing is published,
purchased or funded.
"""

from __future__ import annotations

import base64
import subprocess
from pathlib import Path

import pytest
from market_config.config_loader import chains_from_config, set_user_config_path
from market_identity import IdentityScheme, create_signer

from tests.e2e.roles.scenarios.bare_metal import test_bare_metal_deal as scenario

CHAIN = "arkhai_dev"
RPC_URL = "http://chain.invalid:8545"
CHAIN_ID = 31337
# Obviously synthetic: deterministic development material with no value on any
# public network, and never to be used on one. The marketplace credential is a
# real ed25519 seed because `create_signer` derives a principal from it.
FUNDING_KEY = "0x" + "11" * 32
MARKETPLACE_CREDENTIAL = base64.urlsafe_b64encode(bytes(range(32))).rstrip(b"=").decode()
OPERATOR_ONLY_VARIABLE = "ARKHAI_E2E_OPERATOR_ONLY_FIXTURE_SECRET"

_PRINCIPAL = {
    "scheme": "ed25519",
    "identifier": create_signer(
        IdentityScheme.ED25519, MARKETPLACE_CREDENTIAL
    ).identity.identifier,
}


def _settings(tmp_path: Path, **overrides) -> dict:
    values = {
        "REGISTRY_URL": "https://registry.invalid",
        "REGISTRY_AUTHORITY": "https://registry.invalid",
        "REGISTRY_PRINCIPALS": [_PRINCIPAL],
        "BUYER_CREDENTIAL_ENVIRONMENT": "ARKHAI_E2E_BARE_METAL_MARKETPLACE_CREDENTIAL",
        "BUYER_CHAIN_NAME": CHAIN,
        "BUYER_CHAIN_RPC_URL": RPC_URL,
        "BUYER_CHAIN_ID": CHAIN_ID,
        "BUYER_ALKAHEST_ADDRESS_CONFIG_PATH": str(tmp_path / "alkahest.json"),
    }
    values.update(overrides)
    return values


@pytest.fixture
def env_dumping_binary(tmp_path: Path) -> Path:
    """A `market` stand-in that reports the environment it was started with."""
    binary = tmp_path / "market"
    binary.write_text("#!/bin/sh\nenv\n", encoding="utf-8")
    binary.chmod(0o755)
    return binary


def _compose(monkeypatch, tmp_path_factory, tmp_path, binary, settle_command, **over):
    (tmp_path / "alkahest.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(scenario, "_require_bare_metal_plugin", lambda: None)
    values = _settings(tmp_path, **over)
    monkeypatch.setattr(
        scenario, "_setting", lambda name, default="": values.get(name, default)
    )
    monkeypatch.setenv(
        "ARKHAI_E2E_BARE_METAL_MARKETPLACE_CREDENTIAL", MARKETPLACE_CREDENTIAL
    )
    monkeypatch.setenv(OPERATOR_ONLY_VARIABLE, "operator-only")
    # The scenario's own fixture body, reached past pytest's direct-call guard
    # so the composition under test is the one an acceptance run uses.
    compose = scenario.bare_metal_buyer_cli.__wrapped__
    generator = compose(binary, tmp_path_factory, settle_command)
    cli = next(generator)
    return cli, generator


def _subprocess_environment(cli) -> dict[str, str]:
    run = cli.run(["bare-metal", "list"])
    assert run.returncode == 0, run.stderr()
    environment: dict[str, str] = {}
    for line in run.stdout().splitlines():
        name, separator, value = line.partition("=")
        if separator:
            environment[name] = value
    return environment


def test_the_crypto_buyer_process_gets_its_config_and_only_its_own_key(
    monkeypatch, tmp_path_factory, tmp_path, env_dumping_binary
):
    monkeypatch.setenv(scenario._FUNDING_KEY_SOURCE_VARIABLE, FUNDING_KEY)
    cli, generator = _compose(
        monkeypatch,
        tmp_path_factory,
        tmp_path,
        env_dumping_binary,
        ["bare-metal", "fund", "--buyer-evm-address", "0x" + "33" * 20],
    )

    environment = _subprocess_environment(cli)

    assert environment[scenario._BUYER_CONFIG_VARIABLE] == str(cli.config_path), (
        "the plugin reads its configuration by environment variable, so the "
        "shared --config flag alone leaves it loading a different file or none"
    )
    assert environment["BARE_METAL_BUYER_EVM_PRIVATE_KEY"] == FUNDING_KEY
    assert environment["ARKHAI_E2E_BARE_METAL_MARKETPLACE_CREDENTIAL"] == (
        MARKETPLACE_CREDENTIAL
    )
    assert OPERATOR_ONLY_VARIABLE not in environment, (
        "the buyer inherited the operator's environment; an operator credential "
        "could then answer a challenge on the buyer's behalf"
    )
    assert scenario._FUNDING_KEY_SOURCE_VARIABLE not in environment, (
        "the key must reach the buyer only under the name the command reads"
    )
    generator.close()


def test_a_renamed_funding_variable_still_reaches_the_buyer(
    monkeypatch, tmp_path_factory, tmp_path, env_dumping_binary
):
    """`fund --private-key-env` names the variable; the fixture must follow it."""
    monkeypatch.setenv(scenario._FUNDING_KEY_SOURCE_VARIABLE, FUNDING_KEY)
    cli, generator = _compose(
        monkeypatch,
        tmp_path_factory,
        tmp_path,
        env_dumping_binary,
        ["bare-metal", "fund", "--private-key-env", "DEMO_FUNDING_KEY"],
    )

    environment = _subprocess_environment(cli)

    assert environment["DEMO_FUNDING_KEY"] == FUNDING_KEY
    assert "BARE_METAL_BUYER_EVM_PRIVATE_KEY" not in environment
    generator.close()


def test_the_generated_profile_carries_the_chain_the_shared_loader_reads(
    monkeypatch, tmp_path_factory, tmp_path, env_dumping_binary
):
    """`buy` and `fund` both resolve the chain through `chains_from_config`."""
    monkeypatch.setenv(scenario._FUNDING_KEY_SOURCE_VARIABLE, FUNDING_KEY)
    cli, generator = _compose(
        monkeypatch,
        tmp_path_factory,
        tmp_path,
        env_dumping_binary,
        ["bare-metal", "fund"],
    )

    try:
        set_user_config_path(cli.config_path)
        chains = chains_from_config()
    finally:
        set_user_config_path(None)

    assert CHAIN in chains, (
        "the buyer has no configuration for the advertised chain, so it would "
        "refuse before proposing and could never fund"
    )
    chain = chains[CHAIN]
    assert chain.rpc_url == RPC_URL
    assert chain.chain_id == CHAIN_ID
    assert chain.alkahest_address_config_path == str(tmp_path / "alkahest.json")
    generator.close()


def test_the_hosted_rail_needs_no_evm_secret_or_chain(
    monkeypatch, tmp_path_factory, tmp_path, env_dumping_binary
):
    """A Stripe lane must not be made to hold an on-chain funding key."""
    monkeypatch.delenv(scenario._FUNDING_KEY_SOURCE_VARIABLE, raising=False)
    cli, generator = _compose(
        monkeypatch,
        tmp_path_factory,
        tmp_path,
        env_dumping_binary,
        ["bare-metal", "complete"],
        BUYER_CHAIN_NAME="",
        BUYER_CHAIN_RPC_URL="",
    )

    environment = _subprocess_environment(cli)

    assert "BARE_METAL_BUYER_EVM_PRIVATE_KEY" not in environment
    try:
        set_user_config_path(cli.config_path)
        assert chains_from_config() == {}
    finally:
        set_user_config_path(None)
    generator.close()


@pytest.mark.parametrize(
    ("missing", "expected", "overrides"),
    [
        ("funding key", "ARKHAI_E2E_BARE_METAL_EVM_PRIVATE_KEY", {}),
        ("chain", "BUYER_CHAIN_RPC_URL", {"BUYER_CHAIN_RPC_URL": ""}),
        (
            "address config file",
            "BUYER_ALKAHEST_ADDRESS_CONFIG_PATH",
            {"BUYER_ALKAHEST_ADDRESS_CONFIG_PATH": "/nonexistent"},
        ),
    ],
)
def test_a_selected_crypto_lane_refuses_before_the_purchase(
    monkeypatch,
    tmp_path_factory,
    tmp_path,
    env_dumping_binary,
    missing,
    expected,
    overrides,
):
    """Missing crypto input fails while composing, not after negotiating.

    `require_acceptance_lane` is the deliberately selected mode: a lane that
    reported success having skipped everything would be the failure this guards.
    """
    if missing != "funding key":
        monkeypatch.setenv(scenario._FUNDING_KEY_SOURCE_VARIABLE, FUNDING_KEY)
    else:
        monkeypatch.delenv(scenario._FUNDING_KEY_SOURCE_VARIABLE, raising=False)

    with pytest.raises(AssertionError) as refusal:
        _compose(
            monkeypatch,
            tmp_path_factory,
            tmp_path,
            env_dumping_binary,
            ["bare-metal", "fund"],
            REQUIRE_ACCEPTANCE_LANE=True,
            **overrides,
        )

    assert expected in str(refusal.value), (
        f"the lane failed, but not for the missing {missing}"
    )


def test_the_fixture_binary_is_never_the_real_market_command(env_dumping_binary):
    """Guard: these tests must not be able to spawn a real buyer."""
    completed = subprocess.run(
        [str(env_dumping_binary)], capture_output=True, text=True, timeout=30
    )
    assert completed.returncode == 0
    assert "--version" not in completed.stdout
