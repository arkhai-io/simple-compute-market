"""The provisioning chart's rendered configuration and the values it refuses.

Definition documents render, mount, and set their path together, or not at all.

The chart derives each definition document's path from the document's
presence. A document that renders and mounts while its path is unset is a
silent no-op, and a path set without the document points the service at
nothing, so each document's three parts are asserted together. An operator
file renders and mounts with no meaning the chart knows, under any name the
chart and the service do not read themselves. The schema also refuses the
retired VM playbook setting the service refuses at startup, and the smoke hook
selects the smoke checks that write nothing.
Standard library only: values are written as JSON, which is YAML.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

CHART = Path(__file__).resolve().parents[1]

_POOLS = {
    "pools": [
        {
            "id": "default",
            "label": "Default Pool",
            "provider": "vm.ansible",
            "provider_config": {"playbook_path": "playbooks/vm-operations.yaml"},
        }
    ]
}
_CAPACITY = {
    "resources": [
        {
            "resource_id": "compute-kvm1",
            "pool_id": "default",
            "resource_type": "compute.gpu",
            "host_id": "kvm1",
            "capacity": {"gpu_count": 8},
        }
    ]
}

# (definitions key, rendered file, config setting)
_DOCUMENTS = {
    "pools": ("pool-definitions.yaml", "pool_definitions_path"),
    "capacity": ("capacity-definitions.yaml", "capacity_definitions_path"),
}


def _render(values: dict) -> subprocess.CompletedProcess[str]:
    with tempfile.NamedTemporaryFile("w", suffix=".yaml") as handle:
        json.dump(values, handle)
        handle.flush()
        return subprocess.run(
            ["helm", "template", "provisioning-test", str(CHART), "--values", handle.name],
            check=False,
            capture_output=True,
            text=True,
        )


def _assert_document(manifest: str, key: str, *, present: bool) -> None:
    filename, setting = _DOCUMENTS[key]
    parts = {
        "document": f"  {filename}: |",
        "mount": f"mountPath: /app/config/{filename}",
        "path": f'"{setting}": "/app/config/{filename}"',
    }
    for part, text in parts.items():
        assert (text in manifest) is present, (
            f"{key}: {part} {'missing' if present else 'rendered'}"
        )


def test_empty_definitions_render_no_document_mount_or_path() -> None:
    rendered = _render({})
    assert rendered.returncode == 0, rendered.stderr
    for key in _DOCUMENTS:
        _assert_document(rendered.stdout, key, present=False)


def test_each_definition_renders_its_document_mount_and_path_alone() -> None:
    for key, document in (("pools", _POOLS), ("capacity", _CAPACITY)):
        rendered = _render({"definitions": {key: document}})
        assert rendered.returncode == 0, rendered.stderr
        for other in _DOCUMENTS:
            _assert_document(rendered.stdout, other, present=other == key)


def test_both_definitions_render_together() -> None:
    rendered = _render({"definitions": {"pools": _POOLS, "capacity": _CAPACITY}})
    assert rendered.returncode == 0, rendered.stderr
    for key in _DOCUMENTS:
        _assert_document(rendered.stdout, key, present=True)
    assert "resource_id: compute-kvm1" in rendered.stdout


def test_a_configured_definitions_path_is_refused() -> None:
    for _, setting in _DOCUMENTS.values():
        rendered = _render({"config": {setting: "/app/config/elsewhere.yaml"}})
        assert rendered.returncode != 0, f"{setting} was accepted"
        assert setting in rendered.stderr


def test_an_operator_file_renders_verbatim_and_mounts_beside_the_profile() -> None:
    """The chart gives an operator file no meaning: it renders and mounts it,
    and the setting naming it is the operator's own."""
    seed = "pools:\n  - id: gpu-h200\n    label: H200 nodes\n"
    rendered = _render({
        "configFiles": {"pool-seed.yaml": seed},
        "config": {"pool_seed_path": "/app/config/pool-seed.yaml"},
    })
    assert rendered.returncode == 0, rendered.stderr
    assert "  pool-seed.yaml: |\n    pools:\n      - id: gpu-h200\n" in rendered.stdout
    assert 'mountPath: "/app/config/pool-seed.yaml"' in rendered.stdout
    assert '"pool_seed_path": "/app/config/pool-seed.yaml"' in rendered.stdout

    rendered = _render({})
    assert rendered.returncode == 0, rendered.stderr
    assert "pool-seed.yaml" not in rendered.stdout


def test_an_operator_file_keeps_its_exact_content_and_name() -> None:
    """Content with an indented first line and no final newline, and a name
    YAML would otherwise read as a boolean, render as given: Helm parses every
    rendered manifest, so a broken block scalar fails the render."""
    rendered = _render({"configFiles": {"yes": "  indented: 1\nflush: 2"}})
    assert rendered.returncode == 0, rendered.stderr
    assert "  \"yes\": |2-\n      indented: 1\n    flush: 2\n" in rendered.stdout
    assert 'subPath: "yes"' in rendered.stdout


def test_an_operator_file_may_not_take_a_name_the_service_or_chart_reads() -> None:
    """Names the chart mounts itself, and profiles the service would load
    around `config`, are refused; so is a name that is no single file."""
    for name in (
        "pool-definitions.yaml", "config-production.yml", "config.yml",
        "config-local.yaml", "../pool-seed.yaml", ".", "..", "..data",
    ):
        rendered = _render({"configFiles": {name: "x: 1\n"}})
        assert rendered.returncode != 0, f"{name} was accepted"
        assert f"invalid propertyName '{name}'" in rendered.stderr, rendered.stderr


def test_the_profile_carries_the_vm_playbook_under_its_domain_name() -> None:
    rendered = _render({})
    assert rendered.returncode == 0, rendered.stderr
    assert (
        '"vm_playbook_path": "/opt/domains/vms/provisioning/iac/ansible/playbooks/'
        'single-tenant/vm-operations.yaml"'
    ) in rendered.stdout
    assert '"playbook_path"' not in rendered.stdout


def test_the_smoke_hook_selects_the_read_only_and_security_checks() -> None:
    """The hook runs every smoke check that writes nothing: the read-only ones
    and the unauthenticated-request refusal."""
    rendered = _render({})
    assert rendered.returncode == 0, rendered.stderr
    hook = rendered.stdout.split("# Source: provisioning/templates/tests/provisioning-smoke-test.yaml", 1)
    assert len(hook) == 2, "the smoke-test hook did not render"
    assert '"helm.sh/hook": test' in hook[1].split("\n---", 1)[0]
    assert (
        "- -m\n        - provisioning_readonly or provisioning_security\n"
        in hook[1].split("\n---", 1)[0]
    )


def test_the_retired_playbook_setting_is_refused() -> None:
    """The service refuses ``playbook_path`` at startup; the schema refuses it
    before anything renders, so a stale values file never reaches a pod."""
    rendered = _render({"config": {"playbook_path": "/opt/vm-operations.yaml"}})
    assert rendered.returncode != 0, "config.playbook_path was accepted"
    assert "playbook_path" in rendered.stderr
    assert "vm_playbook_path" not in rendered.stderr


if __name__ == "__main__":
    test_empty_definitions_render_no_document_mount_or_path()
    test_each_definition_renders_its_document_mount_and_path_alone()
    test_both_definitions_render_together()
    test_a_configured_definitions_path_is_refused()
    test_an_operator_file_renders_verbatim_and_mounts_beside_the_profile()
    test_an_operator_file_keeps_its_exact_content_and_name()
    test_an_operator_file_may_not_take_a_name_the_service_or_chart_reads()
    test_the_profile_carries_the_vm_playbook_under_its_domain_name()
    test_the_smoke_hook_selects_the_read_only_and_security_checks()
    test_the_retired_playbook_setting_is_refused()
    print("provisioning chart render checks passed")
