"""The mock runner: rules over the gate mechanism, and a domain's default output.

Runs are driven through the real executor where what matters is what the
executor hands the runner (the job's parameters and its registered host).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from compute_provisioning.hosts import ConnectionEnvelope, ExecutionHost
from compute_provisioning.jobs import JobFailure, JobRun, JobSuccess
from compute_provisioning.jobs.executor_mock import MockRule

from compute_provisioning_ansible import (
    AnsibleJobExecutor,
    AnsibleJobInterpretation,
    AnsibleJobPlan,
    MockAnsibleRunner,
    MockPlaybook,
)
from compute_provisioning_ansible.runner import AnsibleError, AnsibleRun

_HOST = ExecutionHost(
    host_id="node-1",
    pool_id="default",
    connection=ConnectionEnvelope(
        kind="ssh",
        version=1,
        public={"ssh_host": "10.0.0.7", "ssh_port": 2201, "ssh_user": "ops", "key_path": "/k"},
    ),
)


def _default(playbook: MockPlaybook) -> str:
    host = playbook.host
    return f"DEFAULT {playbook.parameters.get('action')} {host.ssh_host if host else None}"


class _EchoCodec:
    """Reports the playbook's raw output as the job's result."""

    inventory_group = "nodes"
    secret_fields: frozenset[str] = frozenset()

    def prepare(self, run: JobRun) -> AnsibleJobPlan:
        return AnsibleJobPlan(variables={"host_id": run.host.host_id}, limit=run.host.host_id)

    def interpret(self, run, host, output) -> AnsibleJobInterpretation:
        from compute_provisioning_contracts import ResultEnvelope

        return AnsibleJobInterpretation(
            result=ResultEnvelope(
                offering_mode=run.offering_mode, result_kind="echo", value={"stdout": output.stdout}
            )
        )

    def is_retryable(self, message: str) -> bool:
        return True


def _run(**parameters) -> JobRun:
    return JobRun(
        job_id="job-1",
        offering_mode="test",
        action=parameters.get("action", "grant"),
        host=_HOST,
        parameters={"action": "grant", "host_id": "node-1", **parameters},
        report_handle=lambda handle: None,
        report_logs=lambda logs: None,
    )


def _execute(runner: MockAnsibleRunner, **parameters):
    executor = AnsibleJobExecutor(
        runner, _EchoCodec(), Path("/playbooks/p.yaml"), timeout_seconds=5
    )
    return executor.execute(_run(**parameters))


def _handle(parameters: dict | None) -> AnsibleRun:
    runner = MockAnsibleRunner(default_output=_default)
    return runner.start_playbook(
        Path("/p.yaml"), Path("/tmp/inventory"), Path("/tmp/vars"), "node-1",
        job_parameters=parameters,
    )


class TestDefaultOutput:
    async def test_the_domain_renders_it_from_the_job_and_its_registered_host(self):
        outcome = await _execute(MockAnsibleRunner(default_output=_default))

        assert isinstance(outcome, JobSuccess)
        assert outcome.result.value["stdout"] == "DEFAULT grant 10.0.0.7"

    async def test_a_run_without_an_inventory_has_no_host(self):
        runner = MockAnsibleRunner(default_output=_default)
        run = runner.start_playbook(
            Path("/p.yaml"), Path("/tmp/none"), Path("/tmp/vars"), "node-1",
            job_parameters={"action": "grant"},
        )

        result = await runner.wait_for_playbook(run, timeout_seconds=5)

        assert result.stdout == "DEFAULT grant None"

    async def test_logs_are_reported_as_a_real_run_reports_them(self):
        runner = MockAnsibleRunner(default_output=_default)
        lines: list[tuple[str, str]] = []
        run = runner.start_playbook(
            Path("/p.yaml"), Path("/tmp/none"), Path("/tmp/vars"), "node-1",
            job_parameters={"action": "grant"},
        )

        await runner.wait_for_playbook(
            run, timeout_seconds=5, log_callback=lambda out, err: lines.append((out, err))
        )

        assert lines == [("DEFAULT grant None", "")]


class TestRuleMatching:
    async def test_a_catch_all_rule_replaces_the_output(self):
        runner = MockAnsibleRunner(default_output=_default)
        runner.add_rule(MockRule(rule_id="any", match={}, result_stdout="CAUGHT"))

        assert (await _execute(runner)).result.value["stdout"] == "CAUGHT"

    async def test_a_rule_matches_the_jobs_stored_parameters(self):
        runner = MockAnsibleRunner(default_output=_default)
        runner.add_rule(
            MockRule(rule_id="n1", match={"action": "grant", "host_id": "node-1"}, result_stdout="N1")
        )
        runner.add_rule(MockRule(rule_id="other", match={"host_id": "node-2"}, result_stdout="N2"))

        assert (await _execute(runner)).result.value["stdout"] == "N1"

    async def test_the_first_matching_rule_wins(self):
        runner = MockAnsibleRunner(default_output=_default)
        runner.add_rule(MockRule(rule_id="first", match={"action": "grant"}, result_stdout="FIRST"))
        runner.add_rule(MockRule(rule_id="second", match={"action": "grant"}, result_stdout="SECOND"))

        assert (await _execute(runner)).result.value["stdout"] == "FIRST"

    async def test_a_rule_that_does_not_match_leaves_the_default(self):
        runner = MockAnsibleRunner(default_output=_default)
        runner.add_rule(MockRule(rule_id="n2", match={"host_id": "node-2"}, result_stdout="N2"))

        assert (await _execute(runner)).result.value["stdout"] == "DEFAULT grant 10.0.0.7"

    async def test_a_run_carrying_no_job_matches_no_rule(self):
        runner = MockAnsibleRunner(default_output=lambda playbook: "DEFAULT")
        runner.add_rule(MockRule(rule_id="any", match={}, result_stdout="CAUGHT"))
        run = runner.start_playbook(Path("/p.yaml"), Path("/tmp/i"), Path("/tmp/v"), "node-1")

        assert (await runner.wait_for_playbook(run, timeout_seconds=5)).stdout == "DEFAULT"

    async def test_rules_belong_to_their_runner(self):
        first = MockAnsibleRunner(default_output=_default)
        second = MockAnsibleRunner(default_output=_default)
        second.add_rule(MockRule(rule_id="any", match={}, fail_with="only the second"))

        assert isinstance(await _execute(first), JobSuccess)
        assert first.list_rules() == []


class TestFailure:
    async def test_fail_with_fails_the_run(self):
        runner = MockAnsibleRunner(default_output=_default)
        runner.add_rule(MockRule(rule_id="f", match={}, fail_with="disk image lock conflict"))

        outcome = await _execute(runner)

        assert isinstance(outcome, JobFailure)
        assert outcome.error.message == "disk image lock conflict"

    async def test_fail_with_takes_precedence_over_result_stdout(self):
        runner = MockAnsibleRunner(default_output=_default)
        runner.add_rule(MockRule(rule_id="f", match={}, fail_with="oops", result_stdout="no"))
        run = runner.start_playbook(
            Path("/p.yaml"), Path("/tmp/i"), Path("/tmp/v"), "node-1", job_parameters={}
        )

        with pytest.raises(AnsibleError, match="oops"):
            await runner.wait_for_playbook(run, timeout_seconds=5)


class TestGate:
    async def test_a_held_run_completes_only_when_resumed(self):
        runner = MockAnsibleRunner(default_output=_default)
        runner.add_rule(
            MockRule(rule_id="gate", match={}, pause_before_result=True, result_stdout="AFTER")
        )

        running = asyncio.create_task(_execute(runner))
        await asyncio.wait_for(runner.rules.wait_until_held("gate"), timeout=2.0)
        assert not running.done()

        assert runner.resume_rule("gate") is True
        outcome = await asyncio.wait_for(running, timeout=2.0)
        assert outcome.result.value["stdout"] == "AFTER"

    def test_resuming_an_unknown_or_ungated_rule_is_refused(self):
        runner = MockAnsibleRunner(default_output=_default)
        runner.add_rule(MockRule(rule_id="open", match={}))

        assert runner.resume_rule("missing") is False
        assert runner.resume_rule("open") is False

    def test_rules_are_listed_and_deleted(self):
        runner = MockAnsibleRunner(default_output=_default)
        runner.add_rule(MockRule(rule_id="r1", match={"action": "grant"}))
        runner.add_rule(MockRule(rule_id="r2", match={}, pause_before_result=True))

        assert [(r["rule_id"], r["paused"]) for r in runner.list_rules()] == [
            ("r1", False), ("r2", True)
        ]
        assert runner.delete_rule("r1") is True
        assert runner.delete_rule("r1") is False


class TestExecutorIntegration:
    def test_the_executor_reports_the_mocks_rules(self):
        runner = MockAnsibleRunner(default_output=_default)
        executor = AnsibleJobExecutor(runner, _EchoCodec(), Path("/p.yaml"), timeout_seconds=5)

        assert executor.rules is runner.rules

    def test_the_family_reports_a_mode_run_by_the_mock_as_mock(self):
        """What readiness reports as each offering mode's executor mode."""
        from compute_provisioning import JobExecutorTable
        from compute_provisioning_ansible.runner import AnsibleRunner
        from types import SimpleNamespace

        table = JobExecutorTable()
        table.register(
            "mocked", "grant",
            AnsibleJobExecutor(
                MockAnsibleRunner(default_output=_default), _EchoCodec(), Path("/p.yaml"),
                timeout_seconds=5,
            ),
        )
        table.register(
            "real", "grant",
            AnsibleJobExecutor(
                AnsibleRunner(SimpleNamespace()), _EchoCodec(), Path("/p.yaml"), timeout_seconds=5
            ),
        )

        assert table.mocked_by_offering_mode() == {"mocked": True, "real": False}

    async def test_cancelling_a_held_run_ends_it_without_a_resume(self):
        runner = MockAnsibleRunner(default_output=_default)
        runner.add_rule(MockRule(rule_id="gate", match={}, pause_before_result=True))
        handles: list = []
        executor = AnsibleJobExecutor(runner, _EchoCodec(), Path("/p.yaml"), timeout_seconds=5)
        run = JobRun(
            job_id="job-1", offering_mode="test", action="grant", host=_HOST,
            parameters={"action": "grant", "host_id": "node-1"},
            report_handle=handles.append, report_logs=lambda logs: None,
        )

        running = asyncio.create_task(executor.execute(run))
        await asyncio.wait_for(runner.rules.wait_until_held("gate"), timeout=2.0)
        await executor.cancel(handles[0])
        outcome = await asyncio.wait_for(running, timeout=2.0)

        assert "pid" not in handles[0]
        assert isinstance(outcome, JobFailure)
        assert outcome.error.message == "Playbook cancelled"
        await asyncio.wait_for(runner.rules.wait_until_released("gate"), timeout=2.0)
        assert runner.list_rules()[0]["waiting"] == 0

    async def test_a_run_cancelled_before_it_waits_never_reaches_the_gate(self):
        runner = MockAnsibleRunner(default_output=_default)
        runner.add_rule(MockRule(rule_id="gate", match={}, pause_before_result=True))
        run = runner.start_playbook(
            Path("/p.yaml"), Path("/tmp/i"), Path("/tmp/v"), "node-1", job_parameters={}
        )

        await runner.cancel(runner.execution_handle(run))

        with pytest.raises(AnsibleError, match="Playbook cancelled"):
            await runner.wait_for_playbook(run, timeout_seconds=5)
        assert runner.list_rules()[0]["waiting"] == 0

    async def test_cancelling_a_finished_or_unknown_run_does_nothing(self):
        runner = MockAnsibleRunner(default_output=_default)
        run = runner.start_playbook(
            Path("/p.yaml"), Path("/tmp/i"), Path("/tmp/v"), "node-1", job_parameters={}
        )
        await runner.wait_for_playbook(run, timeout_seconds=5)

        await runner.cancel(runner.execution_handle(run))
        await runner.cancel({"mock_run": "unknown"})

    async def test_every_host_is_reachable(self):
        runner = MockAnsibleRunner(default_output=_default)

        result = await runner.check_connectivity_with_inventory("node-1", Path("/tmp/i"))

        assert (result.host, result.reachable) == ("node-1", True)

    def test_the_inventory_names_the_group_and_is_removed_on_cleanup(self):
        runner = MockAnsibleRunner(default_output=_default)
        with runner.write_inventory([], group="nodes") as inventory:
            assert inventory.path.read_text() == "[nodes]\n"
        assert not inventory.path.exists()
