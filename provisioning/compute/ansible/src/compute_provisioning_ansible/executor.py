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
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from compute_provisioning.jobs import (
    JobFailure,
    JobOutcome,
    JobRun,
    JobSuccess,
    ProvisioningErrorEnvelope,
)

from .codec import AnsibleJobCodec, matches_any, write_extra_vars
from .runner import AnsibleError, inventory_target, redact_ansible_output

logger = logging.getLogger(__name__)

#: Failure messages that mean the host could not be reached or would not
#: admit the run. Running the same job again against the same host meets the
#: same refusal, so these are never retried, whatever a codec says.
TRANSPORT_FAILURES: tuple[str, ...] = (
    "Invalid SSH key",
    "Permission denied",
    "Authentication failed",
    "Host unreachable",
    "Operation timed out",
    "Connection refused",
    "UNREACHABLE",
)


class AnsibleJobExecutor:
    """One runner, one domain's codec, and the playbook its actions run.

    ``additional_non_retryable_errors`` are operator-configured substrings: a failure
    whose message contains one is not retried, in addition to the transport
    failures and the codec's own. ``runner`` is an ``AnsibleRunner`` or a
    stand-in for one with the same playbook and inventory surface.
    """

    def __init__(
        self,
        runner: Any,
        codec: AnsibleJobCodec,
        playbook_path: Path,
        *,
        timeout_seconds: int,
        additional_non_retryable_errors: Iterable[str] = (),
    ) -> None:
        self._runner = runner
        self._codec = codec
        self._playbook_path = playbook_path
        self._timeout_seconds = timeout_seconds
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
        host = inventory_target(run.host)
        runner = self._runner
        vars_path = write_extra_vars(plan)
        # Owns the inventory and any decrypted key file. It and the variables
        # file are removed in the finally below whether the run succeeds,
        # fails, times out, or is cancelled.
        inventory = None
        try:
            inventory = runner.write_inventory([host], group=self._codec.inventory_group)
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
                message = str(exc)
                return JobFailure(
                    error=ProvisioningErrorEnvelope(
                        code="execution_failed",
                        message=message,
                        retryable=self.is_retryable(message),
                    ),
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

    async def cancel(self, handle: Mapping[str, Any]) -> None:
        """Ask the runner to stop the run ``handle`` names.

        The runner made the handle, so only it knows what stopping the run
        means: signalling a playbook process, or ending a mocked run's wait.
        """
        await self._runner.cancel(handle)

    def is_retryable(self, message: str) -> bool:
        if matches_any(message, TRANSPORT_FAILURES):
            return False
        if matches_any(message, self._additional_non_retryable_errors):
            return False
        return self._codec.is_retryable(message)

    def redact(self, text: str) -> str:
        """Scrub generic and codec-named secrets; see ``redact_ansible_output``."""
        return redact_ansible_output(text, self._codec.secret_fields)


def _joined(stdout: str, stderr: str) -> str:
    return stdout + ("\n\nSTDERR:\n" + stderr if stderr else "")


__all__ = ["AnsibleJobExecutor", "TRANSPORT_FAILURES"]
