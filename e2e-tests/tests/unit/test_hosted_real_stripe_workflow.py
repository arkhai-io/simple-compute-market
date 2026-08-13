from __future__ import annotations

from pathlib import Path


WORKFLOW = Path(__file__).parents[3] / ".github/workflows/hosted-real-stripe.yml"


def _workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_real_provider_workflow_is_manual_default_branch_and_environment_protected() -> None:
    text = _workflow()
    trigger = text.split("concurrency:", 1)[0]
    assert "workflow_dispatch:" in trigger
    assert "pull_request" not in trigger
    assert "pull_request_target" not in text
    assert "github.ref == format('refs/heads/{0}'" in text
    assert "environment: hosted-real-stripe" in text
    assert "persist-credentials: false" in text
    assert 'git merge-base --is-ancestor "$TRUSTED_COMMIT"' in text


def test_workflow_pins_both_source_and_release_identities() -> None:
    text = _workflow()
    for identity in (
        "marketplace_commit",
        "hosted_manifest_sha256",
        "hosted_source_commit",
        "hosted_image_digest",
        "hosted_release_run_id",
    ):
        assert identity in text
    assert 'test "$(git rev-parse HEAD)" = "$TRUSTED_COMMIT"' in text
    assert "HOSTED_PRODUCTION_MANIFEST_SHA256" in text
    assert "HOSTED_PRODUCTION_SOURCE_COMMIT" in text
    assert "HOSTED_PRODUCTION_IMAGE_DIGEST" in text


def test_short_lived_credentials_exist_only_in_protected_job_and_never_checkout() -> None:
    text = _workflow()
    assert "actions/create-github-app-token@" in text
    assert "HOSTED_E2E_CREDENTIAL_BROKER_URL" in text
    assert "ACTIONS_ID_TOKEN_REQUEST_TOKEN" in text
    assert "expires_at - now <= 3600" in text
    assert "'.stripe_restricted_key'" in text
    assert "::add-mask::$STRIPE_SECRET_KEY" in text
    checkout = text.split("- name: Checkout exact marketplace source", 1)[1].split(
        "- name: Reject non-default-branch", 1
    )[0]
    assert "secrets." not in checkout
    assert "STRIPE_SECRET_KEY" not in checkout


def test_workflow_uploads_only_sanitized_json_and_always_tears_down() -> None:
    text = _workflow()
    upload = text.split("- name: Upload allowlisted sanitized evidence only", 1)[1].split(
        "- name: Tear down", 1
    )[0]
    assert "path: hosted-real-stripe-evidence.json" in upload
    assert "compose-logs" not in upload
    assert ".env" not in upload
    teardown = text.split("- name: Tear down all local processes and volumes", 1)[1]
    assert "if: always()" in teardown
    assert "make hosted-compose-clean || true" in teardown


def test_real_provider_lane_has_no_fallback_or_non_external_evidence_label() -> None:
    text = _workflow().lower()
    assert "simulated" not in text
    assert "hermetic" not in text
    assert "continue-on-error: true" in text
    assert "fail for unavailable or failed external evidence" in text
