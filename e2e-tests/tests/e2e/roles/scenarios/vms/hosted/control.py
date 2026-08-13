from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

CONTROL_PROTOCOL = "arkhai.hosted-settlement-e2e-control.v1"
DISTRIBUTION = "arkhai-hosted-settlement-e2e"
DEFAULT_EXECUTABLE = "hosted-settlement-e2e-control"


class HostedControlPrerequisiteError(RuntimeError):
    pass


class HostedControlError(RuntimeError):
    pass


@dataclass(frozen=True)
class ControlVersion:
    distribution: str
    version: str
    protocol: str


@dataclass(frozen=True)
class SanitizedEffect:
    operation_ref: str
    resource_ref: str
    kind: Literal["account", "checkout", "transfer", "refund"]
    state: str
    amount: int | None
    currency: str | None
    destination_fixture: str | None
    transfer_group: str | None
    source_relation: str | None
    attempts: int

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SanitizedEffect":
        allowed = {
            "operation_ref",
            "resource_ref",
            "kind",
            "state",
            "amount",
            "currency",
            "destination_fixture",
            "transfer_group",
            "source_relation",
            "attempts",
            "created_at_unix",
            "updated_at_unix",
        }
        extra = set(value).difference(allowed)
        if extra:
            raise HostedControlError(
                "effect inspection returned non-sanitized fields: " + ", ".join(sorted(extra))
            )
        operation_ref = value.get("operation_ref")
        resource_ref = value.get("resource_ref")
        kind = value.get("kind")
        state = value.get("state")
        attempts = value.get("attempts")
        if not isinstance(operation_ref, str) or not operation_ref:
            raise HostedControlError("effect inspection returned an invalid identity or state")
        if not isinstance(resource_ref, str) or not resource_ref:
            raise HostedControlError("effect inspection returned an invalid identity or state")
        if not isinstance(state, str) or not state:
            raise HostedControlError("effect inspection returned an invalid identity or state")
        kind = _effect_kind(kind)
        if not isinstance(attempts, int) or isinstance(attempts, bool) or attempts < 1:
            raise HostedControlError("effect inspection returned an invalid attempt count")
        return cls(
            operation_ref=operation_ref,
            resource_ref=resource_ref,
            kind=kind,
            state=state,
            amount=_optional_int(value.get("amount"), "amount"),
            currency=_optional_str(value.get("currency"), "currency"),
            destination_fixture=_optional_str(
                value.get("destination_fixture"), "destination_fixture"
            ),
            transfer_group=_optional_str(value.get("transfer_group"), "transfer_group"),
            source_relation=_optional_str(value.get("source_relation"), "source_relation"),
            attempts=attempts,
        )


def _effect_kind(value: object) -> Literal["account", "checkout", "transfer", "refund"]:
    if value == "account":
        return "account"
    if value == "checkout":
        return "checkout"
    if value == "transfer":
        return "transfer"
    if value == "refund":
        return "refund"
    raise HostedControlError("effect inspection returned an unsupported effect kind")


def _optional_str(value: object, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise HostedControlError(f"effect inspection returned invalid {name}")
    return value


def _optional_int(value: object, name: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise HostedControlError(f"effect inspection returned invalid {name}")
    return value


def stable_operation_ref(prefix: str, *parts: str) -> str:
    """Build the operation identity defined by the released E2E control contract."""

    if not prefix or not parts or any(not part for part in parts):
        raise ValueError("stable operation references require a prefix and non-empty parts")
    digest = hashlib.sha256("\x00".join(parts).encode()).hexdigest()
    return f"{prefix}_{digest[:40]}"


Runner = Callable[..., subprocess.CompletedProcess[str]]
VersionResolver = Callable[[str], str]


class ReleasedControlCli:
    """Subprocess-only adapter for the released private control CLI.

    The marketplace test suite knows the versioned command schema but imports no
    private Python module. The control URL and credential are supplied only to the
    child process and never included in commands, results, or errors.
    """

    def __init__(
        self,
        *,
        executable: str = DEFAULT_EXECUTABLE,
        control_url: str,
        credential: str,
        expected_version: str,
        expected_protocol: str = CONTROL_PROTOCOL,
        runner: Runner = subprocess.run,
        version_resolver: VersionResolver = importlib.metadata.version,
    ) -> None:
        if not control_url.startswith(("http://", "https://")):
            raise HostedControlPrerequisiteError("private control URL must be absolute")
        if len(credential) < 32:
            raise HostedControlPrerequisiteError(
                "private control credential must contain at least 32 characters"
            )
        if expected_protocol != CONTROL_PROTOCOL:
            raise HostedControlPrerequisiteError(
                f"unsupported private control protocol: {expected_protocol!r}"
            )
        self._executable = executable
        self._control_url = control_url
        self._credential = credential
        self._expected_version = expected_version
        self._runner = runner
        self._version_resolver = version_resolver

    @classmethod
    def from_environment(cls) -> "ReleasedControlCli":
        required = (
            "HOSTED_SETTLEMENT_E2E_CONTROL_URL",
            "HOSTED_SETTLEMENT_E2E_CONTROL_CREDENTIAL",
            "HOSTED_SETTLEMENT_E2E_FIXTURE_VERSION",
            "HOSTED_SETTLEMENT_E2E_CONTROL_PROTOCOL",
        )
        missing = tuple(name for name in required if not os.environ.get(name, "").strip())
        if missing:
            raise HostedControlPrerequisiteError(
                "selected hosted E2E scenario is missing prerequisite(s): " + ", ".join(missing)
            )
        return cls(
            executable=os.environ.get("HOSTED_SETTLEMENT_E2E_CONTROL_CLI", DEFAULT_EXECUTABLE),
            control_url=os.environ["HOSTED_SETTLEMENT_E2E_CONTROL_URL"],
            credential=os.environ["HOSTED_SETTLEMENT_E2E_CONTROL_CREDENTIAL"],
            expected_version=os.environ["HOSTED_SETTLEMENT_E2E_FIXTURE_VERSION"],
            expected_protocol=os.environ["HOSTED_SETTLEMENT_E2E_CONTROL_PROTOCOL"],
        )

    def verify_version(self) -> ControlVersion:
        executable = shutil.which(self._executable)
        if executable is None:
            raise HostedControlPrerequisiteError(
                f"selected hosted E2E scenario requires {self._executable!r} from "
                f"{DISTRIBUTION}=={self._expected_version}"
            )
        try:
            installed = self._version_resolver(DISTRIBUTION)
        except importlib.metadata.PackageNotFoundError as exc:
            raise HostedControlPrerequisiteError(
                f"selected hosted E2E scenario requires {DISTRIBUTION}=={self._expected_version}"
            ) from exc
        if installed != self._expected_version:
            raise HostedControlPrerequisiteError(
                f"private control fixture version mismatch: expected {self._expected_version}, "
                f"installed {installed}"
            )
        completed = self._runner(
            [executable, "--help"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if completed.returncode != 0:
            raise HostedControlPrerequisiteError("private control CLI is not executable")
        return ControlVersion(DISTRIBUTION, installed, CONTROL_PROTOCOL)

    def reset(self, *, initial_time_unix: int, request_id: str) -> Mapping[str, Any]:
        return self._command(
            {"command": "reset", "initial_time_unix": initial_time_unix}, request_id
        )

    def set_account(
        self, *, account_ref: str, request_id: str, ready: bool = True
    ) -> Mapping[str, Any]:
        return self._command(
            {
                "command": "set_account",
                "account_ref": account_ref,
                "details_submitted": ready,
                "charges_enabled": ready,
                "payouts_enabled": ready,
                "capabilities": ["transfers"] if ready else [],
            },
            request_id,
        )

    def plan_outcome(
        self,
        *,
        operation_ref: str,
        outcomes: Sequence[Mapping[str, Any]],
        request_id: str,
    ) -> Mapping[str, Any]:
        if not outcomes:
            raise ValueError("at least one outcome is required")
        return self._command(
            {
                "command": "plan_outcome",
                "operation_ref": operation_ref,
                "steps": [dict(item) for item in outcomes],
            },
            request_id,
        )

    def checkout_transition(
        self,
        *,
        checkout_ref: str,
        transition: Literal["fund", "expire"],
        request_id: str,
    ) -> Mapping[str, Any]:
        return self._command(
            {
                "command": "checkout_transition",
                "checkout_ref": checkout_ref,
                "transition": transition,
            },
            request_id,
        )

    def event(
        self,
        *,
        action: Literal["withhold", "release", "duplicate", "reorder"],
        event_refs: Sequence[str],
        request_id: str,
    ) -> Mapping[str, Any]:
        if not event_refs:
            raise ValueError("at least one event reference is required")
        return self._command(
            {"command": "event", "action": action, "event_refs": list(event_refs)},
            request_id,
        )

    def advance_clock(
        self,
        *,
        request_id: str,
        seconds: int | None = None,
        now_unix: int | None = None,
    ) -> Mapping[str, Any]:
        if (seconds is None) == (now_unix is None):
            raise ValueError("supply exactly one clock target")
        command: dict[str, Any] = {"command": "advance_clock"}
        command["seconds" if seconds is not None else "now_unix"] = (
            seconds if seconds is not None else now_unix
        )
        return self._command(command, request_id)

    def wait_state(
        self,
        *,
        resource_kind: Literal["account", "checkout", "transfer", "refund", "event"],
        resource_ref: str,
        state: str,
        request_id: str,
        timeout_milliseconds: int = 30_000,
    ) -> Mapping[str, Any]:
        return self._command(
            {
                "command": "wait_state",
                "resource_kind": resource_kind,
                "resource_ref": resource_ref,
                "state": state,
                "timeout_milliseconds": timeout_milliseconds,
            },
            request_id,
        )

    def inspect_effects(
        self, *, operation_ref: str, request_id: str
    ) -> tuple[SanitizedEffect, ...]:
        result = self._command(
            {"command": "inspect_effects", "operation_ref": operation_ref}, request_id
        )
        effects = result.get("items", result.get("effects", result))
        if isinstance(effects, Mapping):
            values: object = effects.get("items", ())
        else:
            values = effects
        if not isinstance(values, (list, tuple)):
            raise HostedControlError("effect inspection result is not a sequence")
        parsed = tuple(
            SanitizedEffect.from_mapping(item) for item in values if isinstance(item, Mapping)
        )
        if len(parsed) != len(values):
            raise HostedControlError("effect inspection result contains a non-object")
        if any(item.operation_ref != operation_ref for item in parsed):
            raise HostedControlError("effect inspection crossed operation identities")
        return parsed

    def _command(self, command: Mapping[str, Any], request_id: str) -> Mapping[str, Any]:
        if len(request_id) < 16:
            raise ValueError("control request identity must contain at least 16 characters")
        with tempfile.TemporaryDirectory(prefix="arkhai-control-") as directory:
            command_path = Path(directory, "command.json")
            command_path.write_text(
                json.dumps(dict(command), separators=(",", ":"), sort_keys=True),
                encoding="utf-8",
            )
            env = dict(os.environ)
            env["HOSTED_SETTLEMENT_E2E_CONTROL_URL"] = self._control_url
            env["HOSTED_SETTLEMENT_E2E_CONTROL_CREDENTIAL"] = self._credential
            completed = self._runner(
                [self._executable, "--command-file", str(command_path), "--request-id", request_id],
                capture_output=True,
                text=True,
                timeout=70,
                check=False,
                env=env,
            )
        if completed.returncode != 0:
            raise HostedControlError(f"private control command {command.get('command')!r} failed")
        try:
            envelope = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise HostedControlError("private control CLI returned invalid JSON") from exc
        if not isinstance(envelope, Mapping) or set(envelope) != {"generation", "result"}:
            raise HostedControlError("private control CLI returned an invalid envelope")
        result = envelope["result"]
        if isinstance(result, Mapping):
            return result
        if isinstance(result, list):
            return {"items": result}
        raise HostedControlError("private control CLI returned an invalid result")
