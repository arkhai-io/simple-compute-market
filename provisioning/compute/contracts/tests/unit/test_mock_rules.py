"""The mock mechanism's route template and wire models.

The expected declarations below are the paths, signed operations, roles, and
bound resources VM's and bare metal's mock routes are served and signed with.
A mount must reproduce them exactly, since every caller of those routes signs
against them.
"""

from __future__ import annotations

import pytest

from compute_provisioning_contracts import (
    MockJobEvaluation,
    MockRouteMount,
    MockRuleCreate,
    MockRuleView,
    assemble_provisioning_route_table,
)

_VM_TEST_ROUTES = (
    {
        "method": "POST",
        "path": r"/test/mock-rules",
        "operation": "provisioning_test_rule_add",
        "roles": ("admin",),
    },
    {
        "method": "GET",
        "path": r"/test/mock-rules",
        "operation": "provisioning_test_rules_list",
        "roles": ("admin",),
    },
    {
        "method": "DELETE",
        "path": r"/test/mock-rules/(?P<rule_id>[^/]+)",
        "operation": "provisioning_test_rule_delete",
        "roles": ("admin",),
        "path_resource": "rule_id",
    },
    {
        "method": "POST",
        "path": r"/test/mock-rules/(?P<rule_id>[^/]+)/resume",
        "operation": "provisioning_test_rule_resume",
        "roles": ("admin",),
        "path_resource": "rule_id",
    },
    {
        "method": "POST",
        "path": r"/test/evaluate-job",
        "operation": "provisioning_test_job_evaluate",
        "roles": ("admin",),
    },
)

_BARE_METAL_TEST_ROUTES = (
    {
        "method": "POST",
        "path": r"/test/bare-metal/mock-rules",
        "operation": "provisioning_test_bare_metal_rule_add",
        "roles": ("admin",),
    },
    {
        "method": "GET",
        "path": r"/test/bare-metal/mock-rules",
        "operation": "provisioning_test_bare_metal_rules_list",
        "roles": ("admin",),
    },
    {
        "method": "DELETE",
        "path": r"/test/bare-metal/mock-rules/(?P<rule_id>[^/]+)",
        "operation": "provisioning_test_bare_metal_rule_delete",
        "roles": ("admin",),
        "path_resource": "rule_id",
    },
    {
        "method": "POST",
        "path": r"/test/bare-metal/mock-rules/(?P<rule_id>[^/]+)/resume",
        "operation": "provisioning_test_bare_metal_rule_resume",
        "roles": ("admin",),
        "path_resource": "rule_id",
    },
    {
        "method": "POST",
        "path": r"/test/bare-metal/evaluate-job",
        "operation": "provisioning_test_bare_metal_job_evaluate",
        "roles": ("admin",),
    },
)

_VM = MockRouteMount("/test", "provisioning_test")
_BARE_METAL = MockRouteMount("/test/bare-metal", "provisioning_test_bare_metal")


@pytest.mark.parametrize(
    ("mount", "expected"),
    ((_VM, _VM_TEST_ROUTES), (_BARE_METAL, _BARE_METAL_TEST_ROUTES)),
    ids=("vm", "bare-metal"),
)
def test_a_mount_yields_the_routes_its_domain_declared(mount, expected) -> None:
    assert mount.route_declarations() == expected


def test_two_mounts_compose_into_one_table() -> None:
    table = assemble_provisioning_route_table(
        _VM.route_declarations(), _BARE_METAL.route_declarations()
    )

    vm, vm_rule = table.resolve("POST", "/test/mock-rules/r1/resume")
    bare_metal, bare_metal_rule = table.resolve(
        "POST", "/test/bare-metal/mock-rules/r1/resume"
    )

    assert (vm.operation, vm_rule) == ("provisioning_test_rule_resume", "r1")
    assert (bare_metal.operation, bare_metal_rule) == (
        "provisioning_test_bare_metal_rule_resume",
        "r1",
    )


@pytest.mark.parametrize("mount", (_VM, _BARE_METAL), ids=("vm", "bare-metal"))
def test_the_paths_a_mount_builds_resolve_to_its_routes(mount) -> None:
    table = assemble_provisioning_route_table(mount.route_declarations())
    requests = (
        ("POST", mount.rules_path(), "rule_add", ""),
        ("GET", mount.rules_path(), "rules_list", ""),
        ("DELETE", mount.rule_path("r1"), "rule_delete", "r1"),
        ("POST", mount.rule_resume_path("r1"), "rule_resume", "r1"),
        ("POST", mount.evaluate_path(), "job_evaluate", ""),
    )

    for method, path, action, resource in requests:
        contract, bound = table.resolve(method, path, {})
        assert (contract.operation, bound) == (mount.operation(action), resource)
        assert mount.declaration(action)["operation"] == contract.operation


@pytest.mark.parametrize(
    ("prefix", "operation_prefix"),
    (
        ("test", "provisioning_test"),
        ("/test/", "provisioning_test"),
        ("/test/(.*)", "provisioning_test"),
        ("/test", "Provisioning-Test"),
        ("/test", ""),
    ),
)
def test_a_mount_refuses_a_prefix_that_is_not_literal(prefix, operation_prefix) -> None:
    with pytest.raises(ValueError):
        MockRouteMount(prefix, operation_prefix)


def test_an_unknown_action_has_no_declaration() -> None:
    with pytest.raises(KeyError):
        _VM.declaration("rule_rename")


def test_the_wire_models_read_what_the_rule_routes_answer() -> None:
    view = MockRuleView.model_validate(
        {
            "rule_id": "gate",
            "match": {"action": "grant"},
            "pause_before_result": True,
            "fail_with": None,
            "result_stdout": False,
            "paused": True,
            "waiting": 1,
        }
    )
    evaluation = MockJobEvaluation.model_validate(
        {"params_valid": True, "host_exists": True, "rule_matched": "gate", "would_pause": True}
    )

    assert (view.paused, view.waiting) == (True, 1)
    assert evaluation.errors == []
    assert MockRuleCreate().model_dump() == {
        "rule_id": "",
        "match": {},
        "pause_before_result": False,
        "result_stdout": None,
        "fail_with": None,
    }
