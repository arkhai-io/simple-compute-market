"""Test controller — remote mock control API.

Only mounted when ``mock`` is in ``ACTIVE_PROFILES``.  Never present in
production or staging deployments.

Provides an HTTP API for configuring ``ProgrammableMockAnsibleService``
rules and synchronising test assertions against job lifecycle events
without polling loops.

Endpoints
---------
``POST /test/mock-rules``                Add a when→then mock rule
``GET  /test/mock-rules``                List active rules
``DELETE /test/mock-rules/{rule_id}``    Remove a rule
``POST /test/mock-rules/{rule_id}/resume`` Release a paused job gate

``GET  /test/jobs/drain``               Long-poll until all jobs terminal
``GET  /test/jobs/summary``             Status counts (no blocking)
``GET  /test/jobs/{job_id}/wait``       Long-poll until one job is terminal

Rule schema (POST /test/mock-rules body)
----------------------------------------
::

    {
        "rule_id": "my-ww1-create",     // optional; auto-assigned if absent
        "match": {                       // subset of AnsibleJobParams fields
            "vm_action": "create",
            "vm_host": "ww1"
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

import asyncio
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

import container as _container_module
from models.system_model import EvaluateJobRequest, EvaluateJobResponse
from services.job_service import AnsibleJobService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/test", tags=["test"])


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


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------


def _get_programmable_mock():
    """Resolve the ProgrammableMockAnsibleService from the container.

    Raises HTTP 503 if the service is not the programmable mock (e.g.,
    because the 'mock' profile is not active — should not happen since
    this router is only mounted under that condition, but defensive).
    """
    svc = _container_module.resolved_ansible_service
    from services.mock_ansible_service import ProgrammableMockAnsibleService
    if not isinstance(svc, ProgrammableMockAnsibleService):
        raise HTTPException(
            status_code=503,
            detail="ProgrammableMockAnsibleService is not active (ACTIVE_PROFILES != mock)",
        )
    return svc


def _get_job_service() -> AnsibleJobService:
    return _container_module.resolved_job_service


# ---------------------------------------------------------------------------
# Mock rule endpoints
# ---------------------------------------------------------------------------


@router.post("/mock-rules", summary="Add a mock rule")
def add_mock_rule(body: MockRuleRequest) -> dict:
    """Add a when→then mock rule.

    Rules are evaluated in insertion order.  The first rule whose ``match``
    dict is a subset of the incoming job params wins.
    """
    mock = _get_programmable_mock()
    from services.mock_ansible_service import MockRule
    rule = MockRule(
        rule_id=body.rule_id,
        match=body.match,
        pause_before_result=body.pause_before_result,
        result_stdout=body.result_stdout,
        fail_with=body.fail_with,
    )
    mock.add_rule(rule)
    return {"rule_id": rule.rule_id, "status": "added"}


@router.get("/mock-rules", summary="List active mock rules")
def list_mock_rules() -> list[dict]:
    """Return the current set of mock rules in evaluation order."""
    return _get_programmable_mock().list_rules()


@router.delete("/mock-rules/{rule_id}", summary="Remove a mock rule")
def delete_mock_rule(rule_id: str) -> dict:
    """Remove a rule by ID.  No-op if the rule does not exist."""
    deleted = _get_programmable_mock().delete_rule(rule_id)
    return {"rule_id": rule_id, "deleted": deleted}


@router.post("/mock-rules/{rule_id}/resume", summary="Release a paused job gate")
def resume_mock_rule(rule_id: str) -> dict:
    """Release the asyncio gate for a rule with ``pause_before_result=true``.

    The job blocked on this rule's gate will proceed to its result or failure
    immediately after this call returns.
    """
    resumed = _get_programmable_mock().resume_rule(rule_id)
    if not resumed:
        raise HTTPException(
            status_code=404,
            detail=f"Rule {rule_id!r} not found or not paused",
        )
    return {"rule_id": rule_id, "resumed": True}


# ---------------------------------------------------------------------------
# Job observation endpoints
# ---------------------------------------------------------------------------


TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}


@router.get("/jobs/summary", summary="Job status counts")
def job_summary(
    job_service: AnsibleJobService = Depends(_get_job_service),
) -> dict:
    """Return counts of jobs by status — non-blocking diagnostic snapshot."""
    result = job_service.list_jobs(agent_id=None, limit=1000)
    counts: dict[str, int] = {}
    for job in result.jobs:
        counts[job.status] = counts.get(job.status, 0) + 1
    total_terminal = sum(
        v for k, v in counts.items() if k in TERMINAL_STATUSES
    )
    total_active = sum(
        v for k, v in counts.items() if k not in TERMINAL_STATUSES
    )
    return {
        "counts": counts,
        "total": result.total,
        "total_terminal": total_terminal,
        "total_active": total_active,
    }


@router.get("/jobs/drain", summary="Wait until all jobs are terminal")
async def drain_jobs(
    timeout: float = Query(default=30.0, description="Max seconds to wait"),
    job_service: AnsibleJobService = Depends(_get_job_service),
) -> dict:
    """Long-poll until every job in the queue has reached a terminal state.

    Returns immediately if all jobs are already terminal.  Times out with
    HTTP 408 if active jobs remain after ``timeout`` seconds.

    Useful for test teardown: call drain before making final assertions to
    ensure no background jobs are still running.
    """
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        result = job_service.list_jobs(agent_id=None, limit=1000)
        active = [j for j in result.jobs if j.status not in TERMINAL_STATUSES]
        if not active:
            summary = {}
            for j in result.jobs:
                summary[j.status] = summary.get(j.status, 0) + 1
            return {"drained": True, "counts": summary}
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            raise HTTPException(
                status_code=408,
                detail=f"Drain timed out: {len(active)} job(s) still active after {timeout}s",
            )
        await asyncio.sleep(min(0.25, remaining))


@router.get("/jobs/{job_id}/wait", summary="Wait for a specific job to reach terminal state")
async def wait_for_job(
    job_id: str,
    timeout: float = Query(default=10.0, description="Max seconds to wait"),
    job_service: AnsibleJobService = Depends(_get_job_service),
) -> dict:
    """Long-poll until ``job_id`` reaches a terminal status.

    Returns the final job status immediately if already terminal.
    Times out with HTTP 408 if the job has not terminated within ``timeout``.

    This is the replacement for ``asyncio.sleep`` polling loops in tests.
    """
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        try:
            job = job_service.get_job(job_id, agent_id=None)
        except LookupError:
            raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")
        if job.status in TERMINAL_STATUSES:
            return {"job_id": job_id, "status": job.status, "result": job.result,
                    "error": job.error}
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            raise HTTPException(
                status_code=408,
                detail=f"Job {job_id!r} did not reach terminal state within {timeout}s "
                       f"(current status: {job.status!r})",
            )
        await asyncio.sleep(min(0.25, remaining))


@router.post(
    "/evaluate-job",
    response_model=EvaluateJobResponse,
    summary="Dry-run: would this job be accepted and which mock rule would match?",
)
async def evaluate_job(body: EvaluateJobRequest) -> EvaluateJobResponse:
    """Evaluate a provisioning job spec without creating a job.

    Delegates to ProgrammableMockAnsibleService.evaluate_job which checks
    host existence and mock rule matching. Only available when the service
    is running in mock mode. Used by e2e stage 08c.
    """
    from models.jobs_model import AnsibleJobParams
    from services.mock_ansible_service import ProgrammableMockAnsibleService

    ansible_svc = _container_module.resolved_ansible_service
    host_svc = _container_module.resolved_host_service

    if not isinstance(ansible_svc, ProgrammableMockAnsibleService):
        raise HTTPException(
            status_code=503,
            detail="evaluate-job is only available when ACTIVE_PROFILES=mock",
        )
    if host_svc is None:
        raise HTTPException(status_code=503, detail="HostService not available")

    params = AnsibleJobParams(
        vm_host=body.host,
        vm_action=body.vm_action,
        vm_target=body.vm_target,
        ssh_pubkey=body.ssh_pubkey,
    )
    return ansible_svc.evaluate_job(params, host_svc)


def make_router() -> APIRouter:
    return router
