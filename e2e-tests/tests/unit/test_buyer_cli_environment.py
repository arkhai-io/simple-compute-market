"""What the buyer subprocess actually receives.

Attribute assertions cannot detect broken forwarding. These run BuyerCli
against a real child process that prints its own environment, so the
observation is the environment the child got.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from tests.e2e.roles.buyer_cli import BuyerCli

# A child that reports its environment, used in place of the market binary.
_REPORTER = (
    "import json,os,sys;"
    "print(json.dumps({k: v for k, v in os.environ.items()}))"
)


def _cli(tmp_path: Path, **kwargs) -> BuyerCli:
    binary = tmp_path / "fake-market"
    binary.write_text(f'#!/bin/sh\nexec {sys.executable} -c \'{_REPORTER}\' "$@"\n')
    binary.chmod(0o755)
    return BuyerCli(
        binary=binary,
        config_path=tmp_path / "buyer.toml",
        state_dir=tmp_path / "state",
        data_dir=tmp_path / "data",
        home_dir=tmp_path / "home",
        credential_env={"ARKHAI_TEST_CREDENTIAL": "buyer-only-value"},
        **kwargs,
    )


def _child_environment(cli: BuyerCli) -> dict:
    run = cli.run(["--help"])
    return json.loads(run.stdout())


def test_default_still_forwards_the_inherited_environment(tmp_path, monkeypatch):
    """Other domain scenarios rely on inheritance; that behaviour is unchanged."""
    monkeypatch.setenv("SOME_OPERATOR_SECRET", "leaked")

    env = _child_environment(_cli(tmp_path))

    assert env.get("SOME_OPERATOR_SECRET") == "leaked"


def test_an_explicit_base_environment_reaches_the_child_without_operator_values(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("SOME_OPERATOR_SECRET", "leaked")
    monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/agent")

    env = _child_environment(_cli(tmp_path, base_env={"PATH": os.environ["PATH"]}))

    assert "SOME_OPERATOR_SECRET" not in env
    assert "SSH_AUTH_SOCK" not in env


def test_the_buyer_credential_reaches_the_child(tmp_path):
    env = _child_environment(_cli(tmp_path, base_env={"PATH": os.environ["PATH"]}))

    assert env.get("ARKHAI_TEST_CREDENTIAL") == "buyer-only-value"


def test_the_child_receives_the_buyer_profile_directories(tmp_path):
    cli = _cli(tmp_path, base_env={"PATH": os.environ["PATH"]})

    env = _child_environment(cli)

    assert env["HOME"] == str(cli.home_dir)
    assert env["XDG_STATE_HOME"] == str(cli.state_dir)
    assert env["XDG_DATA_HOME"] == str(cli.data_dir)
