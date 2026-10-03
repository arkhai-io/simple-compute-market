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

``GET  /test/jobs/drain``               Long-poll until all jobs terminal
``GET  /test/jobs/summary``             Status counts (no blocking)
``GET  /test/jobs/{job_id}/wait``       Long-poll until one job is terminal

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

import asyncio
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from compute_provisioning.jobs.executor_mock import (
    MockRouteError,
    MockRuleRouteService,
    MockRuleSet,
)
from compute_provisioning_ansible import MockAnsibleRunner
from compute_provisioning_service import container as _container_module
from vm_provisioning_adapter.models.system_model import EvaluateJobRequest, EvaluateJobResponse  # server-only test controller models
from vm_provisioning_adapter.services.job_service import AnsibleJobService

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


def _vm_mock_rules() -> MockRuleSet | None:
    """The VM mock's rules, or ``None`` when the mock profile is not active."""
    svc = _container_module.resolved_ansible_service
    if not isinstance(svc, MockAnsibleRunner):
        return None
    return svc.rules


_rule_routes = MockRuleRouteService(_vm_mock_rules)


def _routed(call):
    try:
        return call()
    except MockRouteError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


def _get_job_service() -> AnsibleJobService:
    return _container_module.resolved_job_service


# ---------------------------------------------------------------------------
# Mock rule endpoints
# ---------------------------------------------------------------------------


@router.post("/mock-rules", summary="Add a mock rule")
def add_mock_rule(body: MockRuleRequest) -> dict:
    """Add a when→then mock rule for VM jobs.

    Rules are evaluated in insertion order.  The first rule whose ``match``
    dict is a subset of the incoming job params wins.
    """
    return _routed(lambda: _rule_routes.add(body.model_dump()))


@router.get("/mock-rules", summary="List active mock rules")
def list_mock_rules() -> list[dict]:
    """Return the current set of VM mock rules in evaluation order."""
    return _routed(_rule_routes.list)


@router.delete("/mock-rules/{rule_id}", summary="Remove a mock rule")
def delete_mock_rule(rule_id: str) -> dict:
    """Remove a rule by ID.  No-op if the rule does not exist."""
    return _routed(lambda: _rule_routes.delete(rule_id))


@router.post("/mock-rules/{rule_id}/resume", summary="Release a paused job gate")
def resume_mock_rule(rule_id: str) -> dict:
    """Release the gate of a rule with ``pause_before_result=true``.

    The job held by this rule's gate proceeds to its result or failure
    immediately after this call returns.
    """
    return _routed(lambda: _rule_routes.resume(rule_id))


# ---------------------------------------------------------------------------
# Job observation endpoints
# ---------------------------------------------------------------------------


TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}


@router.get("/jobs/summary", summary="Job status counts")
def job_summary(
    job_service: AnsibleJobService = Depends(_get_job_service),
) -> dict:
    """Return counts of jobs by status — non-blocking diagnostic snapshot."""
    result = job_service.list_jobs(limit=1000)
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
        result = job_service.list_jobs(limit=1000)
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
    """Wait until ``job_id`` reaches a terminal status.

    Returns the final job status immediately if already terminal; answers 404
    if the job does not exist by the deadline and 408 if it is not terminal by
    then. The job authority signals completion in-process, and re-reads the job
    for one finished elsewhere.

    This is the replacement for ``asyncio.sleep`` polling loops in tests.
    """
    try:
        job = await job_service.wait_for_terminal(job_id, timeout)
    except LookupError:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")
    except TimeoutError as exc:
        raise HTTPException(status_code=408, detail=str(exc))
    return {
        "job_id": job_id,
        "status": job.status,
        "result": job.result.model_dump(mode="json") if job.result is not None else None,
        "error": job.error,
    }

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
    from vm_provisioning_adapter.models.jobs_model import VmJobParams

    ansible_svc = _container_module.resolved_ansible_service
    host_svc = _container_module.resolved_host_service

    if not isinstance(ansible_svc, MockAnsibleRunner):
        raise HTTPException(
            status_code=503,
            detail="evaluate-job is only available when ACTIVE_PROFILES=mock",
        )
    if host_svc is None:
        raise HTTPException(status_code=503, detail="host registry not available")

    params = VmJobParams(
        host_id=body.host,
        vm_action=body.vm_action,
        offering_mode="vm",
        vm_target=body.vm_target,
        ssh_pubkey=body.ssh_pubkey,
    )
    report = ansible_svc.rules.evaluate(
        dataclasses.asdict(params),
        host_id=params.host_id,
        host_lookup=host_svc.get_host,
        required=("vm_action",),
    )
    return EvaluateJobResponse(**report)


def make_router() -> APIRouter:
    return router
