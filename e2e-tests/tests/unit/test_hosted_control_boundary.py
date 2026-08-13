from __future__ import annotations

import json
import subprocess
from importlib.metadata import PackageNotFoundError
from pathlib import Path

import pytest

from tests.e2e.roles.scenarios.vms.hosted.control import (
    CONTROL_PROTOCOL,
    HostedControlError,
    HostedControlPrerequisiteError,
    ReleasedControlCli,
    stable_operation_ref,
)
from tests.e2e.roles.scenarios.vms.hosted.driver import BuyerAction
from tests.e2e.roles.scenarios.vms.hosted.funding import PrivateFundingDriver


class RecordingRunner:
    def __init__(self, result: object = None, *, returncode: int = 0) -> None:
        self.calls = []
        self.commands: list[dict[str, object]] = []
        self.result = {} if result is None else result
        self.returncode = returncode

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if "--help" in command:
            stdout = ""
        else:
            command_path = Path(command[command.index("--command-file") + 1])
            self.commands.append(json.loads(command_path.read_text(encoding="utf-8")))
            stdout = json.dumps({"generation": 1, "result": self.result})
        return subprocess.CompletedProcess(command, self.returncode, stdout=stdout, stderr="secret")


def _control(runner: RecordingRunner) -> ReleasedControlCli:
    return ReleasedControlCli(
        control_url="http://hosted-settlement-control:8083",
        credential="c" * 32,
        expected_version="0.1.0",
        expected_protocol=CONTROL_PROTOCOL,
        runner=runner,
        version_resolver=lambda _distribution: "0.1.0",
    )


def test_released_control_cli_supports_full_versioned_command_surface() -> None:
    runner = RecordingRunner()
    control = _control(runner)
    control.plan_outcome(
        operation_ref="collect_ref",
        outcomes=({"kind": "unknown_after_submission"},),
        request_id="plan-outcome-ref-0001",
    )
    control.checkout_transition(
        checkout_ref="checkout_ref",
        transition="fund",
        request_id="fund-checkout-ref-0001",
    )
    control.checkout_transition(
        checkout_ref="checkout_ref",
        transition="expire",
        request_id="expire-checkout-ref-0001",
    )
    control.event(
        action="withhold",
        event_refs=("event_ref",),
        request_id="withhold-event-ref-0001",
    )
    control.advance_clock(seconds=10, request_id="advance-clock-ref-0001")
    control.wait_state(
        resource_kind="transfer",
        resource_ref="transfer_ref",
        state="paid",
        request_id="wait-transfer-ref-0001",
    )
    commands = runner.commands
    assert [command["command"] for command in commands] == [
        "plan_outcome",
        "checkout_transition",
        "checkout_transition",
        "event",
        "advance_clock",
        "wait_state",
    ]
    for argv, kwargs in runner.calls:
        assert "c" * 32 not in argv
        assert kwargs["env"]["HOSTED_SETTLEMENT_E2E_CONTROL_CREDENTIAL"] == "c" * 32


def test_effect_inspection_is_sanitized_and_scoped_by_operation_ref() -> None:
    runner = RecordingRunner(
        [
            {
                "operation_ref": "collect_ref",
                "resource_ref": "escrow_ref",
                "kind": "transfer",
                "state": "paid",
                "amount": 2000,
                "currency": "usd",
                "destination_fixture": "fixture-account",
                "transfer_group": "escrow_ref",
                "source_relation": "source-charge",
                "attempts": 2,
                "created_at_unix": 1,
                "updated_at_unix": 2,
            }
        ]
    )
    effects = _control(runner).inspect_effects(
        operation_ref="collect_ref",
        request_id="inspect-effects-ref-0001",
    )
    assert len(effects) == 1
    assert effects[0].operation_ref == "collect_ref"
    assert not hasattr(effects[0], "provider_id")
    assert not hasattr(effects[0], "raw_event")


@pytest.mark.parametrize("field", ("provider_id", "checkout_url", "raw_event", "credential"))
def test_effect_inspection_rejects_private_fields(field: str) -> None:
    runner = RecordingRunner(
        [
            {
                "operation_ref": "collect_ref",
                "resource_ref": "escrow_ref",
                "kind": "transfer",
                "state": "paid",
                "attempts": 1,
                field: "private",
            }
        ]
    )
    with pytest.raises(HostedControlError, match="non-sanitized"):
        _control(runner).inspect_effects(
            operation_ref="collect_ref",
            request_id="inspect-private-ref-0001",
        )


def test_selected_control_fixture_missing_is_a_prerequisite_error(monkeypatch) -> None:
    monkeypatch.delenv("HOSTED_SETTLEMENT_E2E_CONTROL_URL", raising=False)
    with pytest.raises(HostedControlPrerequisiteError, match="missing prerequisite"):
        ReleasedControlCli.from_environment()


def test_missing_private_distribution_is_a_prerequisite_error(monkeypatch) -> None:
    runner = RecordingRunner()
    monkeypatch.setattr("shutil.which", lambda _name: "/bin/private-control")

    def missing(_distribution):
        raise PackageNotFoundError

    control = ReleasedControlCli(
        control_url="http://hosted-settlement-control:8083",
        credential="c" * 32,
        expected_version="0.1.0",
        runner=runner,
        version_resolver=missing,
    )
    with pytest.raises(HostedControlPrerequisiteError, match="requires arkhai-hosted"):
        control.verify_version()


def test_operation_ref_is_stable_and_provider_opaque() -> None:
    first = stable_operation_ref("collect", "obligation", "settlement")
    assert first == stable_operation_ref("collect", "obligation", "settlement")
    assert first.startswith("collect_")
    assert "obligation" not in first


def test_funding_control_request_ids_bind_checkout_identity() -> None:
    runner = RecordingRunner()
    funding = PrivateFundingDriver(_control(runner))

    funding.fund(
        BuyerAction(
            kind="checkout",
            expires_at_unix=1,
            url="https://checkout.test/session/checkout-a",
        ),
        operation_ref="fund-a",
    )
    funding.fund(
        BuyerAction(
            kind="checkout",
            expires_at_unix=1,
            url="https://checkout.test/session/checkout-b",
        ),
        operation_ref="fund-b",
    )

    request_ids = [argv[argv.index("--request-id") + 1] for argv, _kwargs in runner.calls]
    assert request_ids[0] != request_ids[2]
    assert "checkout-a" not in request_ids[0]
    assert "checkout-b" not in request_ids[2]
