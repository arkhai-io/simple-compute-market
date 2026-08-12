from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
RESOLVER = REPO_ROOT / "scripts" / "resolve-review-scope.py"


def test_identity_change_expands_to_every_runtime_and_deployment_consumer() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(RESOLVER),
            "--root",
            str(REPO_ROOT),
            "--projects",
            "kit/identity",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert set(payload["validation_projects"]) >= {
        "kit/identity",
        "kit/hosted-settlement",
        "kit/settlement-runtime",
        "kit/policy",
        "kit/site-client",
        "core/registry-client",
        "core/registry",
        "core/buyer",
        "core/storefront",
        "core/storefront-client",
        "domains/vms/domain",
        "domains/vms/buyer",
        "domains/vms/storefront",
        "domains/vms/provisioning/adapter",
        "domains/apicredits",
        "domains/apicredits/buyer",
        "domains/apicredits/service",
        "domains/apicredits/storefront",
        "domains/bare_metal",
        "domains/bare_metal/storefront",
        "domains/bare_metal/provisioning/adapter",
        "provisioning/compute/service",
        "e2e-tests",
    }
    assert "dist-identity" in payload["dist_targets"]
    assert "dist-hosted-client" in payload["dist_targets"]
    assert "dist-storefront-client" in payload["dist_targets"]
    assert "dist-arkhai-core-registry" in payload["dist_targets"]
