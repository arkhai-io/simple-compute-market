from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "hosted-stripe-test.yml"


def _workflow() -> dict[str, object]:
    document = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def test_protected_workflow_requires_exact_release_and_run_identities() -> None:
    workflow = _workflow()
    triggers = workflow.get("on", workflow.get(True))
    assert isinstance(triggers, dict)
    dispatch = triggers["workflow_dispatch"]
    inputs = dispatch["inputs"]
    required = {
        "marketplace_commit",
        "hosted_release_run_id",
        "hosted_release_artifact",
        "hosted_manifest_sha256",
        "hosted_client_wheel_sha256",
        "hosted_source_commit",
        "hosted_workflow_ref",
        "hosted_image_digest",
        "scenario",
    }
    assert set(inputs) == required
    assert all(value["required"] is True for value in inputs.values())

    job = workflow["jobs"]["stripe-test"]
    assert job["environment"] == "hosted-stripe-test"
    assert job["strategy"]["max-parallel"] == 1
    assert job["timeout-minutes"] == 90
    run = "\n".join(
        step.get("run", "") for step in job["steps"] if isinstance(step, dict)
    )
    for identity in (
        "TRUSTED_MARKETPLACE_COMMIT",
        "HOSTED_RELEASE_RUN_ID",
        "HOSTED_MANIFEST_SHA256",
        "HOSTED_CLIENT_WHEEL_SHA256",
        "HOSTED_SOURCE_COMMIT",
        "HOSTED_WORKFLOW_REF",
        "HOSTED_IMAGE_DIGEST",
    ):
        assert identity in run
    assert "git merge-base --is-ancestor" in run
    assert "make hosted-stripe-test" in run


def test_protected_workflow_scopes_credentials_and_always_cleans_up() -> None:
    workflow = _workflow()
    job = workflow["jobs"]["stripe-test"]
    steps = job["steps"]
    lane = next(step for step in steps if step.get("id") == "lane")
    script = lane["run"]
    for field in (
        ".authority_env",
        ".buyer_identity_credential",
        ".storefront_identity_credential",
        ".admin_identity_credential",
        ".registry_a_identity_credential",
        ".registry_b_identity_credential",
        ".provisioning_identity_credential",
        ".registry_admin_api_key",
        ".registry_bootstrap_api_key",
    ):
        assert field in script
    assert "umask 077" in script
    assert 'echo "::add-mask::$value"' in script
    assert 'trap cleanup EXIT' in script
    assert 'rm -rf "$secret_dir"' in script

    upload = next(step for step in steps if step["name"].startswith("Upload allowlisted"))
    assert upload["if"].startswith("always()")
    assert upload["with"]["path"] == "stripe-test-evidence/${{ matrix.scenario }}.json"
    stop = next(step for step in steps if step["name"].startswith("Stop protected"))
    assert stop["if"] == "always()"
    assert "hosted-stripe-test-stop" in stop["run"]


def test_public_workflows_do_not_request_protected_stripe_credentials() -> None:
    protected_tokens = (
        "STRIPE_SECRET_KEY",
        "HOSTED_E2E_CREDENTIAL_BROKER_URL",
        "HOSTED_RELEASE_APP_PRIVATE_KEY",
    )
    for path in (ROOT / ".github" / "workflows").glob("*.yml"):
        if path == WORKFLOW_PATH:
            continue
        body = path.read_text(encoding="utf-8")
        assert not any(token in body for token in protected_tokens), path.name
