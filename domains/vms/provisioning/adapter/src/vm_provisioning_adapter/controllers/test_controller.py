"""Test controller — remote mock control API.

Only mounted when ``mock`` is in ``ACTIVE_PROFILES``.  Never present in
production or staging deployments.

Provides an HTTP API for configuring the VM mock runner's
rules and synchronising test assertions against job lifecycle events
without polling loops.

Endpoints
---------
``POST /test/mock-rules``                Add a when→then mock rule
``GET  /test/mock-rules``                List active rules
``DELETE /test/mock-rules/{rule_id}``    Remove a rule
``POST /test/mock-rules/{rule_id}/resume`` Release a paused job gate
``POST /test/evaluate-job``              Dry-run a VM job against the rules

The job observation routes (``/test/jobs/*``) are the compute family's,
mounted by the provisioning service under the same profile.

Rule schema (POST /test/mock-rules body)
----------------------------------------
::

    {
        "rule_id": "my-kvm1-create",     // optional; auto-assigned if absent
        "match": {                       // subset of VmJobParams fields
            "vm_action": "create",
            "host_id": "kvm1"
        },
        "pause_before_result": true,     // block at wait_for_playbook until resumed
        "result_stdout": "...",          // Ansible stdout to inject (optional)
        "fail_with": null                // error string to raise, or null for success
    }

Matching
--------
Rules are evaluated in insertion order; the first whose ``match`` dict is
a subset of the incoming job params wins.  ``match: {}`` is a catch-all.
If no rule matches, the default ``_FAKE_STDOUT`` success path runs.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from compute_provisioning.jobs.executor_mock import (
    MockRuleRouteService,
    MockRuleSet,
)
from compute_provisioning_ansible import MockAnsibleRunner
from vm_provisioning_adapter.controllers.route_binding import routed
from vm_provisioning_adapter.models.jobs_model import VmJobParams
from vm_provisioning_adapter.models.system_model import EvaluateJobRequest, EvaluateJobResponse  # server-only test controller models


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class MockRuleRequest(BaseModel):
    """Body for POST /test/mock-rules."""

    rule_id: str = ""
    match: dict[str, Any] = {}
    pause_before_result: bool = False
    result_stdout: Optional[str] = None
    fail_with: Optional[str] = None


def make_mock_router(
    *,
    vm_runner: Callable[[], Any],
    host_authority: Callable[[], Any],
) -> APIRouter:
    """The VM mock's control routes.

    ``vm_runner`` resolves the runner VM jobs run on, which has rules only
    under the mock profile; ``host_authority`` resolves the host registry a
    dry run checks the host against. Both are read per request.
    """
    router = APIRouter(prefix="/test", tags=["test"])

    def vm_mock_rules() -> MockRuleSet | None:
        """The VM mock's rules, or ``None`` when the mock profile is not active."""
        runner = vm_runner()
        if not isinstance(runner, MockAnsibleRunner):
            return None
        return runner.rules

    rule_routes = MockRuleRouteService(vm_mock_rules)

    @router.post("/mock-rules", summary="Add a mock rule")
    def add_mock_rule(body: MockRuleRequest) -> dict:
        """Add a when→then mock rule for VM jobs.

        Rules are evaluated in insertion order.  The first rule whose ``match``
        dict is a subset of the incoming job params wins.
        """
        return routed(lambda: rule_routes.add(body.model_dump()))

    @router.get("/mock-rules", summary="List active mock rules")
    def list_mock_rules() -> list[dict]:
        """Return the current set of VM mock rules in evaluation order."""
        return routed(rule_routes.list)

    @router.delete("/mock-rules/{rule_id}", summary="Remove a mock rule")
    def delete_mock_rule(rule_id: str) -> dict:
        """Remove a rule by ID.  No-op if the rule does not exist."""
        return routed(lambda: rule_routes.delete(rule_id))

    @router.post("/mock-rules/{rule_id}/resume", summary="Release a paused job gate")
    def resume_mock_rule(rule_id: str) -> dict:
        """Release the gate of a rule with ``pause_before_result=true``.

        The job held by this rule's gate proceeds to its result or failure
        immediately after this call returns.
        """
        return routed(lambda: rule_routes.resume(rule_id))

    @router.post(
        "/evaluate-job",
        response_model=EvaluateJobResponse,
        summary="Dry-run: would this job be accepted and which mock rule would match?",
    )
    async def evaluate_job(body: EvaluateJobRequest) -> EvaluateJobResponse:
        """Evaluate a provisioning job spec without creating a job.

        Checks the host is registered and which of the VM mock's rules the job
        would meet. Only available when the service is running in mock mode.
        """
        runner = vm_runner()
        hosts = host_authority()

        if not isinstance(runner, MockAnsibleRunner):
            raise HTTPException(
                status_code=503,
                detail="evaluate-job is only available when ACTIVE_PROFILES=mock",
            )
        if hosts is None:
            raise HTTPException(status_code=503, detail="host registry not available")

        params = VmJobParams(
            host_id=body.host,
            vm_action=body.vm_action,
            offering_mode="vm",
            vm_target=body.vm_target,
            ssh_pubkey=body.ssh_pubkey,
        )
        report = runner.rules.evaluate(
            dataclasses.asdict(params),
            host_id=params.host_id,
            host_lookup=hosts.get_host,
            required=("vm_action",),
        )
        return EvaluateJobResponse(**report)

    return router
