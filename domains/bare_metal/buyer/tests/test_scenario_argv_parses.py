"""Every argv the acceptance scenario sends reaches a real handler.

The scenario builds argv as literals and its offline boundary test used a fake
CLI, so an option that does not exist produced a green unit suite and a Typer
exit code 2 at the live run. This parses the scenario's own argv with the real
`bare_metal_app` and asserts the handler was entered.

Handlers are replaced at the module level, not the parser: a test that stubbed
the command function itself would stop exercising the thing that was broken.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from arkhai_bare_metal_buyer import cli as buy_cli
from typer.testing import CliRunner

RUN_ID = "run-1"
SCENARIO = (
    Path(__file__).resolve().parents[4]
    / "e2e-tests/tests/e2e/roles/scenarios/bare_metal/test_bare_metal_deal.py"
)

# The argv shapes the scenario sends, minus the `bare-metal` prefix the core
# CLI strips when it mounts this domain's app.
SCENARIO_ARGV = {
    "result": ["result", "--run-id", RUN_ID],
    "access": ["access", "--run-id", RUN_ID],
    "teardown": ["teardown", "--run-id", RUN_ID],
    "status": ["status", "--run-id", RUN_ID],
    "fund": [
        "fund",
        "--run-id",
        RUN_ID,
        "--buyer-evm-address",
        "0x0000000000000000000000000000000000000009",
    ],
}


@pytest.fixture()
def entered(monkeypatch):
    """Record that a handler ran, without letting it reach the network."""
    seen: list[str] = []

    class _Fulfillment:
        def result(self, negotiation_id):
            seen.append("result")
            return {"machine_id": "m"}

        def access(self, negotiation_id):
            seen.append("access")
            return {"host": "h", "port": 22, "username": "u"}

        def teardown(self, negotiation_id):
            seen.append("teardown")
            return {"status": "requested"}

        def status(self, negotiation_id):
            seen.append("status")
            return {"state": "released"}

        def settle(self, **kwargs):
            seen.append("settle")
            return {"obligation_ref": "o"}

        def begin(self, **kwargs):
            seen.append("begin")
            return {"state": "reserved"}

    from types import SimpleNamespace

    deal = SimpleNamespace(
        negotiation_id="neg-1",
        settlement_ref=None,
        escrow_uid="0xalready",
        settlement_plan={
            "obligations": [
                {
                    "payer": "buyer",
                    "claimant": "seller",
                    "amount": "1000",
                    "asset": "0x00000000000000000000000000000000000000aa",
                    "expiration_unix": 2_000_000_000,
                    "mechanism": "alkahest.v1",
                    "params": {
                        "chain_name": "base_sepolia",
                        "escrow_contract": (
                            "0x235e4d9d329460fee53a45cc6b14109bc74818aa"
                        ),
                        "obligation_data": {"amount": "1000"},
                    },
                }
            ]
        },
    )
    monkeypatch.setattr(
        buy_cli,
        "_recovered_transports",
        lambda run_id, config: (
            deal,
            SimpleNamespace(signer=object(), profile_id="p"),
            object(),
            _Fulfillment(),
        ),
    )
    monkeypatch.setattr(
        buy_cli,
        "open_run_log",
        lambda run_id, **kw: SimpleNamespace(event=lambda *a, **k: None),
    )
    return seen


@pytest.mark.parametrize("name", sorted(SCENARIO_ARGV))
def test_the_scenario_argv_reaches_its_handler(name, entered) -> None:
    result = CliRunner().invoke(buy_cli.bare_metal_app, SCENARIO_ARGV[name])

    assert result.exit_code == 0, result.output
    assert entered, f"{name} parsed but no handler ran"


@pytest.mark.parametrize("name", sorted(SCENARIO_ARGV))
def test_the_scenario_file_sends_exactly_these_argv(name) -> None:
    """The literals above must be the ones the scenario actually sends.

    Without this the parser test could keep passing while the scenario drifted
    back to options that do not exist.
    """
    if not SCENARIO.is_file():
        pytest.skip("acceptance scenario is not present in this checkout")
    source = SCENARIO.read_text(encoding="utf-8")

    assert '"--from"' not in source, "--from is not an option any command defines"
    assert '"--json"' not in source, "no command defines --json; output is always JSON"
    assert '"teardown", "request"' not in source
    assert '"teardown", "status"' not in source
    assert f'"{name}"' in source or name == "fund"


def test_no_scenario_command_is_a_subcommand_that_does_not_exist() -> None:
    if not SCENARIO.is_file():
        pytest.skip("acceptance scenario is not present in this checkout")
    source = SCENARIO.read_text(encoding="utf-8")
    registered = {command.name for command in buy_cli.bare_metal_app.registered_commands}

    for match in re.finditer(r'\["bare-metal", "([a-z-]+)"(?:, "([a-z-]+)")?', source):
        command, following = match.group(1), match.group(2)
        assert command in registered, f"{command!r} is not a registered command"
        if following and not following.startswith("--"):
            raise AssertionError(
                f"{command!r} has no {following!r} subcommand; it takes options only"
            )
