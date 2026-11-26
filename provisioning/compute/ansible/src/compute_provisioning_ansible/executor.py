"""Runs a provisioning job as an Ansible playbook against its registered host.

``AnsibleJobExecutor`` is the compute family's job executor for any domain
whose actions run as playbooks: the job authority hands it a job's stored
parameters and the host the job runs against, and it renders the variables
and inventory, runs the playbook, and reports one outcome. The domain's
``AnsibleJobCodec`` says what the parameters mean as variables and what the
output means as a result; this module knows neither.

The host arrives as an ``ExecutionHost`` from the host authority's lookup; the
inventory is rendered from its connection alone, so a job runs only against
the registered host it names.

A failed run is classified from what the runner attaches to its error, never
from the run's printed output: first the runner's own outcomes, ``timed_out``
(retried) and ``cancelled``; then, from the last recorded failure neither
ignored nor rescued, ``unreachable`` (retried: a host that answered the
pre-start probe and then stopped is most often rebooting or briefly
partitioned), ``authentication_refused`` (an unreachable host refusing the SSH
login, which a retry meets again), or a task failure the domain's codec
classifies; and with no record, ``playbook_error`` (not retried: a playbook that
fails before any task fails the same way again), or ``internal_error`` where
the runner could not run or watch the playbook at all. Whatever the class, a failure
whose record or message contains one of the operator's
``additional_non_retryable_errors`` is not retried. The failure's message names
the host, the task and what failed; its details are redacted as logs are.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from compute_provisioning.hosts import ExecutionHost
from compute_provisioning.hosts.service import ConnectionChangeRefusedError, HostNotFoundError
from compute_provisioning.jobs import (
    INTERNAL_ERROR,
    JobFailure,
    JobOutcome,
    JobRun,
    JobSuccess,
    ProvisioningErrorEnvelope,
)

from .codec import AnsibleJobCodec, matches_any, write_extra_vars
from .failures import (
    AUTHENTICATION_REFUSED,
    CANCELLED,
    HOST_KEY_REFUSED,
    PLAYBOOK_ERROR,
    TIMED_OUT,
    UNREACHABLE,
    FailureClass,
    FailureRecord,
    last_failure,
)
from .mock import MockAnsibleRunner
from .host_keys import HostKeyRefusal, key_fingerprint, observe_host_key
from .runner import (
    GENERIC_SECRET_FIELDS,
    AnsibleError,
    AnsibleRunner,
    InventoryTarget,
    inventory_target,
    redact_ansible_output,
)

logger = logging.getLogger(__name__)

#: The SSH messages, in an unreachable host's record, that say the host refused
#: the login rather than stopped answering: ``authentication_refused``, which a
#: retry against the same host and key meets again.
TRANSPORT_FAILURES: tuple[str, ...] = (
    "Permission denied",
    "Authentication failed",
    "Too many authentication failures",
)


class AnsibleJobExecutor:
    """One runner, one domain's codec, and the playbook its actions run.

    ``additional_non_retryable_errors`` are operator-configured substrings: a
    failure whose recorded task message or output, or whose classified message,
    contains one is not retried, whatever its class. ``runner`` is an
    ``AnsibleRunner`` or a stand-in for one with the same playbook and
    inventory surface.
    """

    def __init__(
        self,
        runner: Any,
        codec: AnsibleJobCodec,
        playbook_path: Path,
        *,
        timeout_seconds: int,
        additional_non_retryable_errors: Iterable[str] = (),
        adopt_host_key: Callable[[ExecutionHost, str], ExecutionHost] | None = None,
    ) -> None:
        self._runner = runner
        self._codec = codec
        self._playbook_path = playbook_path
        self._timeout_seconds = timeout_seconds
        self._adopt_host_key = adopt_host_key
        self._additional_non_retryable_errors = tuple(additional_non_retryable_errors)

    @property
    def runner(self) -> Any:
        return self._runner

    @property
    def codec(self) -> AnsibleJobCodec:
        return self._codec

    @property
    def playbook_path(self) -> Path:
        return self._playbook_path

    @property
    def rules(self) -> Any:
        """The mock runner's rules when the runner is a mock, else ``None``.

        The family's executor table reads this to report a mode as mock.
        """
        return getattr(self._runner, "rules", None)

    async def execute(self, run: JobRun) -> JobOutcome:
        plan = self._codec.prepare(run)
        runner = self._runner
        host = inventory_target(run.host, include_host_keys=not isinstance(runner, MockAnsibleRunner))
        if issubclass(type(runner), AnsibleRunner):
            runner.validate_authentication_key(host)
            try:
                host = await self._verified_target(run.host, host)
            except HostKeyRefusal as exc:
                return JobFailure(
                    error=ProvisioningErrorEnvelope(
                        code=HOST_KEY_REFUSED,
                        message=self.redact(str(exc)),
                        retryable=False,
                        details={"host": run.host.host_id},
                    )
                )
        vars_path = write_extra_vars(plan)
        # Owns the inventory and any decrypted key file. It and the variables
        # file are removed in the finally below whether the run succeeds,
        # fails, times out, or is cancelled.
        inventory = None
        try:
            inventory = runner.write_inventory([host], group=self._codec.inventory_group)
            # The last step before the playbook can act on the host: a refusal
            # above, by the codec or the inventory, records no start, and if
            # the start cannot be recorded this raises and nothing is spawned.
            run.report_starting()
            playbook_run = runner.start_playbook(
                playbook_path=plan.playbook_path or self._playbook_path,
                inventory_path=inventory.path,
                extra_vars_path=vars_path,
                limit=plan.limit,
                job_parameters=dict(run.parameters),
            )
            handle = runner.execution_handle(playbook_run)
            run.report_handle(handle)
            logger.info("Job %s running as %s", run.job_id, handle)

            def log_callback(stdout: str, stderr: str) -> None:
                run.report_logs(self.redact(_joined(stdout, stderr)))

            try:
                output = await runner.wait_for_playbook(
                    playbook_run,
                    timeout_seconds=self._timeout_seconds,
                    log_callback=log_callback,
                    redact=self.redact,
                )
            except AnsibleError as exc:
                return JobFailure(
                    error=self.classify(run, exc),
                    logs=self.redact(_joined(exc.stdout, exc.stderr)),
                )
            interpretation = self._codec.interpret(run, host, output)
            return JobSuccess(
                result=interpretation.result,
                credentials=interpretation.credentials,
                logs=self.redact(_joined(output.stdout, output.stderr)),
            )
        finally:
            if inventory is not None:
                inventory.cleanup()
            vars_path.unlink(missing_ok=True)


    async def _verified_target(
        self, registered: ExecutionHost, target: InventoryTarget
    ) -> InventoryTarget:
        timeout = min(self._timeout_seconds, 10)
        if registered.host_key_adoption_pending and self._adopt_host_key is not None:
            discovery = await observe_host_key(target, pins=None, timeout_seconds=timeout)
            if not discovery.verified or discovery.key is None:
                raise HostKeyRefusal(target, discovery.presented, discovery.reason)
            try:
                committed = self._adopt_host_key(registered, discovery.key)
            except (ConnectionChangeRefusedError, HostNotFoundError):
                raise HostKeyRefusal(target, discovery.presented, discovery.reason) from None
            refreshed = inventory_target(committed)
            if (refreshed.ssh_host, refreshed.ssh_port) != (target.ssh_host, target.ssh_port):
                raise HostKeyRefusal(target, discovery.presented, discovery.reason)
            target = refreshed
            if discovery.presented not in {key_fingerprint(pin) for pin in target.host_keys}:
                raise HostKeyRefusal(target, discovery.presented, discovery.reason)

        if not target.host_keys:
            raise HostKeyRefusal(target, None)
        check = await observe_host_key(target, pins=target.host_keys, timeout_seconds=timeout)
        if not check.verified:
            raise HostKeyRefusal(target, check.presented, check.reason)
        return target

    async def cancel(self, handle: Mapping[str, Any]) -> None:
        """Ask the runner to stop the run ``handle`` names.

        The runner made the handle, so only it knows what stopping the run
        means: signalling a playbook process, or ending a mocked run's wait.
        """
        await self._runner.cancel(handle)

    def classify(self, run: JobRun, error: AnsibleError) -> ProvisioningErrorEnvelope:
        """A failed run's class, message and redacted details; see the module docstring."""
        host = run.host.host_id
        details: dict[str, Any] = {"host": host}
        record: FailureRecord | None = None
        if error.outcome == "timed_out":
            failure = FailureClass(TIMED_OUT, retryable=True)
            message = f"{host}: playbook timed out after {self._timeout_seconds} seconds"
        elif error.outcome == "cancelled":
            failure = FailureClass(CANCELLED, retryable=False)
            message = f"{host}: playbook cancelled"
        else:
            record = last_failure(error.failures)
            if record is None:
                failure = FailureClass(
                    INTERNAL_ERROR if error.outcome == "error" else PLAYBOOK_ERROR,
                    retryable=False,
                )
                message = f"{host}: {error}; no failed task was recorded"
                if error.returncode is not None:
                    message += f" (exit status {error.returncode})"
                details["rc"] = error.returncode
            else:
                host = record.host or host
                if record.unreachable:
                    failure = FailureClass(
                        AUTHENTICATION_REFUSED, retryable=False
                    ) if matches_any(record.msg, TRANSPORT_FAILURES) else FailureClass(
                        UNREACHABLE, retryable=True
                    )
                    message = f'{host}: unreachable at task "{record.task}": {record.msg}'
                else:
                    failure = self._codec.classify(run, record)
                    message = f'{host}: task "{record.task}" failed: {_reason(failure, record)}'
                details = _record_details(record)
                if failure.detail:
                    details["domain_detail"] = dict(failure.detail)

        retryable = failure.retryable
        if retryable and self._operator_refuses(message, record):
            retryable = False
        return ProvisioningErrorEnvelope(
            code=failure.code,
            message=self.redact(message),
            retryable=retryable,
            details=self._redacted(details),
        )

    def _operator_refuses(self, message: str, record: FailureRecord | None) -> bool:
        """Whether an operator's non-retryable substring is in the failure."""
        patterns = self._additional_non_retryable_errors
        texts = [message]
        if record is not None:
            texts += [record.msg, record.stdout, record.stderr]
        return any(matches_any(text, patterns) for text in texts if text)

    def _redacted(self, value: Any) -> Any:
        """``value`` with every string redacted, and the value of every key
        that names a secret field replaced whole."""
        if isinstance(value, str):
            return self.redact(value)
        if isinstance(value, Mapping):
            secret = GENERIC_SECRET_FIELDS | self._codec.secret_fields
            return {
                key: "[REDACTED]" if key in secret else self._redacted(item)
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [self._redacted(item) for item in value]
        return value

    def redact(self, text: str) -> str:
        """Scrub generic and codec-named secrets; see ``redact_ansible_output``."""
        return redact_ansible_output(text, self._codec.secret_fields)


def _joined(stdout: str, stderr: str) -> str:
    return stdout + ("\n\nSTDERR:\n" + stderr if stderr else "")


def _reason(failure: FailureClass, record: FailureRecord) -> str:
    """What failed, in a message: the codec's summary, else the task's own
    message, else the first line of its error output."""
    if failure.summary:
        return failure.summary
    if record.msg:
        return record.msg
    lines = record.stderr.strip().splitlines()
    return lines[0] if lines else "no message"


def _record_details(record: FailureRecord) -> dict[str, Any]:
    """The record's fields a failure's details carry: where it failed and how.

    Its output is not among them; the job's logs keep the run's whole output.
    """
    details: dict[str, Any] = {"host": record.host, "task": record.task}
    for name in ("play", "role", "module", "rc"):
        value = getattr(record, name)
        if value is not None:
            details[name] = value
    return details


__all__ = ["AnsibleJobExecutor", "TRANSPORT_FAILURES"]
