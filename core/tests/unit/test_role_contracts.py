from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts/role_contracts.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("role_contracts", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_artifact_populates_shared_fields() -> None:
    module = _load_script_module()

    artifact = module.build_artifact(
        role="buyer",
        action="purchase",
        status="succeeded",
        request_url="http://127.0.0.1:28001/",
        auth_url="http://10.243.0.117:8000/",
        correlation={
            "order_id": "buyer-order-1",
            "job_id": "job-1",
            "vm_target": "tenant-1234",
        },
        details={"registry_url": "http://127.0.0.1:28080/"},
    )

    assert artifact["schema_version"] == module.SCHEMA_VERSION
    assert artifact["role"] == "buyer"
    assert artifact["action"] == "purchase"
    assert artifact["status"] == "succeeded"
    assert artifact["endpoints"] == {
        "request_url": "http://127.0.0.1:28001/",
        "auth_url": "http://10.243.0.117:8000/",
    }
    assert artifact["correlation"]["order_id"] == "buyer-order-1"
    assert artifact["correlation"]["job_id"] == "job-1"
    assert artifact["correlation"]["vm_target"] == "tenant-1234"
    assert artifact["details"]["registry_url"] == "http://127.0.0.1:28080/"
    assert "created_at" in artifact


def test_build_artifact_rejects_unknown_role() -> None:
    module = _load_script_module()

    try:
        module.build_artifact(
            role="unknown",
            action="purchase",
            status="succeeded",
            request_url="http://127.0.0.1:28001/",
            auth_url="http://10.243.0.117:8000/",
        )
    except ValueError as exc:
        assert "Unsupported role" in str(exc)
    else:
        raise AssertionError("build_artifact should reject unknown roles")
