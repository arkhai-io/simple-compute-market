"""Definition documents render, mount, and set their path together, or not at all.

The chart derives each definition document's path from the document's
presence. A document that renders and mounts while its path is unset is a
silent no-op, and a path set without the document points the service at
nothing, so each document's three parts are asserted together. Standard
library only: values are written as JSON, which is YAML.
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
            "provider": "ansible",
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
        "path": f"{setting}: /app/config/{filename}",
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


if __name__ == "__main__":
    test_empty_definitions_render_no_document_mount_or_path()
    test_each_definition_renders_its_document_mount_and_path_alone()
    test_both_definitions_render_together()
    test_a_configured_definitions_path_is_refused()
    print("provisioning chart definition-document render checks passed")
