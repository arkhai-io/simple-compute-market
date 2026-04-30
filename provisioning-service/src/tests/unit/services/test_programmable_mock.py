"""Unit tests for ProgrammableMockAnsibleService.

Tests:
  - Rule matching: exact match, wildcard (empty match), first-match-wins
  - pause_before_result gate
  - fail_with
  - No matching rule → base MockAnsibleService fallback
  - add/delete/list/resume API
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from services.mock_ansible_service import MockRule, ProgrammableMockAnsibleService
from services.ansible_service import AnsibleError, AnsibleRun
from models.jobs_model import AnsibleJobParams


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_service() -> ProgrammableMockAnsibleService:
    mock_settings = MagicMock()
    return ProgrammableMockAnsibleService(mock_settings)


def _make_run(params: AnsibleJobParams | None = None) -> AnsibleRun:
    run = AnsibleRun(
        process=MagicMock(),
        process_id=0,
        vars_path=Path("/tmp/fake.yml"),
    )
    run._params = params  # type: ignore[attr-defined]
    return run


def _params(**kwargs) -> AnsibleJobParams:
    defaults = dict(vm_host="ww1", vm_action="create")
    defaults.update(kwargs)
    return AnsibleJobParams(**defaults)


# ---------------------------------------------------------------------------
# Rule matching
# ---------------------------------------------------------------------------

class TestRuleMatching:
    async def test_no_rules_uses_base_fake_stdout(self):
        svc = _make_service()
        run = _make_run(_params())
        result = await svc.wait_for_playbook(run, timeout_seconds=30)
        assert "mock-vm" in result.stdout  # base _FAKE_STDOUT

    async def test_catchall_rule_matches_any_job(self):
        svc = _make_service()
        svc.add_rule(MockRule(rule_id="catchall", match={}, result_stdout="CATCHALL OK"))
        run = _make_run(_params(vm_action="list"))
        result = await svc.wait_for_playbook(run, timeout_seconds=30)
        assert result.stdout == "CATCHALL OK"

    async def test_specific_rule_matches_by_field(self):
        svc = _make_service()
        svc.add_rule(MockRule(rule_id="create-ww1", match={"vm_action": "create", "vm_host": "ww1"},
                              result_stdout="WW1 CREATE OK"))
        svc.add_rule(MockRule(rule_id="catchall", match={}, result_stdout="FALLBACK"))
        run = _make_run(_params(vm_action="create", vm_host="ww1"))
        result = await svc.wait_for_playbook(run, timeout_seconds=30)
        assert result.stdout == "WW1 CREATE OK"

    async def test_first_match_wins(self):
        svc = _make_service()
        svc.add_rule(MockRule(rule_id="first", match={"vm_action": "create"}, result_stdout="FIRST"))
        svc.add_rule(MockRule(rule_id="second", match={"vm_action": "create"}, result_stdout="SECOND"))
        run = _make_run(_params(vm_action="create"))
        result = await svc.wait_for_playbook(run, timeout_seconds=30)
        assert result.stdout == "FIRST"

    async def test_non_matching_rule_falls_through_to_base(self):
        svc = _make_service()
        svc.add_rule(MockRule(rule_id="ww2-only", match={"vm_host": "ww2"}, result_stdout="WW2"))
        run = _make_run(_params(vm_host="ww1"))
        result = await svc.wait_for_playbook(run, timeout_seconds=30)
        # Falls through to base fake stdout
        assert "mock-vm" in result.stdout

    async def test_no_params_falls_through_to_base(self):
        """Run without attached params — no rule can match, base stdout used."""
        svc = _make_service()
        svc.add_rule(MockRule(rule_id="r", match={"vm_action": "create"}, result_stdout="NOPE"))
        run = _make_run(None)  # no params attached
        result = await svc.wait_for_playbook(run, timeout_seconds=30)
        assert "mock-vm" in result.stdout


# ---------------------------------------------------------------------------
# fail_with
# ---------------------------------------------------------------------------

class TestFailWith:
    async def test_fail_with_raises_ansible_error(self):
        svc = _make_service()
        svc.add_rule(MockRule(rule_id="fail", match={}, fail_with="disk image lock conflict"))
        run = _make_run(_params())
        with pytest.raises(AnsibleError) as exc_info:
            await svc.wait_for_playbook(run, timeout_seconds=30)
        assert "disk image lock conflict" in str(exc_info.value)

    async def test_fail_with_takes_precedence_over_result_stdout(self):
        """fail_with wins even when result_stdout is also set."""
        svc = _make_service()
        svc.add_rule(MockRule(rule_id="r", match={},
                              fail_with="oops", result_stdout="should not appear"))
        run = _make_run(_params())
        with pytest.raises(AnsibleError):
            await svc.wait_for_playbook(run, timeout_seconds=30)


# ---------------------------------------------------------------------------
# pause_before_result gate
# ---------------------------------------------------------------------------

class TestPauseGate:
    async def test_pause_blocks_until_resumed(self):
        svc = _make_service()
        svc.add_rule(MockRule(rule_id="paused-rule", match={},
                              pause_before_result=True, result_stdout="AFTER RESUME"))
        run = _make_run(_params())

        # Start wait_for_playbook — it should block on the gate
        task = asyncio.create_task(svc.wait_for_playbook(run, timeout_seconds=30))

        # Let the event loop tick; task should NOT complete yet
        await asyncio.sleep(0)
        assert not task.done()

        # Resume and collect
        svc.resume_rule("paused-rule")
        result = await asyncio.wait_for(task, timeout=2.0)
        assert result.stdout == "AFTER RESUME"

    async def test_resume_nonexistent_rule_returns_false(self):
        svc = _make_service()
        assert svc.resume_rule("does-not-exist") is False

    async def test_resume_unpaused_rule_returns_false(self):
        svc = _make_service()
        svc.add_rule(MockRule(rule_id="no-pause", match={}, pause_before_result=False))
        assert svc.resume_rule("no-pause") is False


# ---------------------------------------------------------------------------
# Rule lifecycle: add / list / delete
# ---------------------------------------------------------------------------

class TestRuleLifecycle:
    def test_add_assigns_rule_id_if_empty(self):
        svc = _make_service()
        rule = MockRule(match={})
        svc.add_rule(rule)
        assert rule.rule_id != ""

    def test_list_rules_reflects_additions(self):
        svc = _make_service()
        svc.add_rule(MockRule(rule_id="r1", match={"vm_action": "create"}))
        svc.add_rule(MockRule(rule_id="r2", match={}))
        listed = svc.list_rules()
        ids = {r["rule_id"] for r in listed}
        assert {"r1", "r2"} == ids

    def test_delete_removes_rule(self):
        svc = _make_service()
        svc.add_rule(MockRule(rule_id="del-me", match={}))
        assert svc.delete_rule("del-me") is True
        assert all(r["rule_id"] != "del-me" for r in svc.list_rules())

    def test_delete_nonexistent_returns_false(self):
        svc = _make_service()
        assert svc.delete_rule("ghost") is False

    def test_list_shows_paused_state(self):
        svc = _make_service()
        svc.add_rule(MockRule(rule_id="gated", match={}, pause_before_result=True))
        rules = svc.list_rules()
        gated = next(r for r in rules if r["rule_id"] == "gated")
        assert gated["paused"] is True
        svc.resume_rule("gated")
        rules = svc.list_rules()
        gated = next(r for r in rules if r["rule_id"] == "gated")
        assert gated["paused"] is False
