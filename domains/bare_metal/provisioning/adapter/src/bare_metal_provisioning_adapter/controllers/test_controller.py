"""Bare-metal mock control routes, mounted only under the mock profile.

Rules installed here match bare-metal access jobs only; the VM adapter's
``/test/mock-rules`` routes control VM jobs. Job draining and waiting stay on the
shared ``/test/jobs/*`` routes.

``POST   /test/bare-metal/mock-rules``                  add a rule
``GET    /test/bare-metal/mock-rules``                  list rules
``DELETE /test/bare-metal/mock-rules/{rule_id}``        remove a rule
``POST   /test/bare-metal/mock-rules/{rule_id}/resume`` release a held job
``POST   /test/bare-metal/evaluate-job``                dry-run a job
"""

from __future__ import annotations

from typing import Any

from arkhai_bare_metal import BARE_METAL_ACCESS_ACTIONS
from compute_provisioning.jobs.executor_mock import (
    MockRouteError,
    MockRuleRouteService,
    MockRuleSet,
)
from compute_provisioning_service import container as _container_module
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/test/bare-metal", tags=["test", "bare-metal"])


class BareMetalMockRuleRequest(BaseModel):
    rule_id: str = ""
    match: dict[str, Any] = Field(default_factory=dict)
    pause_before_result: bool = False
    result_stdout: str | None = None
    fail_with: str | None = None


class BareMetalEvaluateJobRequest(BaseModel):
    host: str = Field(min_length=1)
    action: str = Field(min_length=1)
    physical_host_id: str | None = None
    escrow_uid: str | None = None


class BareMetalEvaluateJobResponse(BaseModel):
    params_valid: bool
    host_exists: bool
    rule_matched: str | None = None
    would_pause: bool = False
    errors: list[str] = Field(default_factory=list)


def _bare_metal_mock_rules() -> MockRuleSet | None:
    mock = _container_module.resolved_bare_metal_mock_executor
    return mock.rules if mock is not None else None


_rule_routes = MockRuleRouteService(_bare_metal_mock_rules)


def _routed(call):
    try:
        return call()
    except MockRouteError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/mock-rules", summary="Add a bare-metal mock rule")
def add_mock_rule(body: BareMetalMockRuleRequest) -> dict:
    return _routed(lambda: _rule_routes.add(body.model_dump()))


@router.get("/mock-rules", summary="List bare-metal mock rules")
def list_mock_rules() -> list[dict]:
    return _routed(_rule_routes.list)


@router.delete("/mock-rules/{rule_id}", summary="Remove a bare-metal mock rule")
def delete_mock_rule(rule_id: str) -> dict:
    return _routed(lambda: _rule_routes.delete(rule_id))


@router.post(
    "/mock-rules/{rule_id}/resume", summary="Release a held bare-metal job"
)
def resume_mock_rule(rule_id: str) -> dict:
    return _routed(lambda: _rule_routes.resume(rule_id))


@router.post(
    "/evaluate-job",
    response_model=BareMetalEvaluateJobResponse,
    summary="Dry-run: would this bare-metal job run, and which rule would it meet?",
)
def evaluate_job(body: BareMetalEvaluateJobRequest) -> BareMetalEvaluateJobResponse:
    rules = _routed(lambda: _rule_routes_rule_set())
    host_service = _container_module.resolved_host_service
    if host_service is None:
        raise HTTPException(status_code=503, detail="HostService not available")
    # Shaped as a submitted job's stored parameters, which rules match.
    params = {
        "action": body.action,
        "host_id": body.host,
        "physical_host_id": body.physical_host_id,
        "escrow_uid": body.escrow_uid,
    }
    report = rules.evaluate(
        params, host_id=body.host, host_lookup=host_service.get_host
    )
    if body.action not in BARE_METAL_ACCESS_ACTIONS:
        report["errors"].append(
            f"action must be one of {', '.join(BARE_METAL_ACCESS_ACTIONS)}"
        )
        report["params_valid"] = False
    return BareMetalEvaluateJobResponse(**report)


def _rule_routes_rule_set() -> MockRuleSet:
    rules = _bare_metal_mock_rules()
    if rules is None:
        raise MockRouteError(
            503, "the bare-metal mock executor is not active (ACTIVE_PROFILES != mock)"
        )
    return rules


def make_router() -> APIRouter:
    return router
