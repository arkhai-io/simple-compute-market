"""Static stack contracts that protect role and package boundaries."""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]


def test_api_credit_stack_has_no_committed_admin_credential():
    compose = (_REPO_ROOT / "domains/apicredits/compose.yml").read_text(
        encoding="utf-8"
    )
    storefront = (
        _REPO_ROOT / "domains/apicredits/storefront/storefront.credits.toml"
    ).read_text(encoding="utf-8")

    assert "test-api-key" not in compose + storefront
    assert "${APICREDITS_ADMIN_KEY_FILE:?" in compose
    assert compose.count("/run/secrets/arkhai/api-credits-admin-key:ro") == 3
    assert 'admin_key_file      = "/run/secrets/arkhai/api-credits-admin-key"' in storefront


def test_api_credit_state_uses_independent_named_volumes():
    compose = (_REPO_ROOT / "domains/apicredits/compose.yml").read_text(
        encoding="utf-8"
    )

    assert "api-credits-service-data:/app/data" in compose
    assert "api-credits-storefront-data:/app/data" in compose
    assert "api-credits-service-data:" in compose
    assert "api-credits-storefront-data:" in compose


def test_api_credit_storefront_runtime_uses_staged_wheel_only():
    dockerfile = (
        _REPO_ROOT / "domains/apicredits/storefront/Dockerfile"
    ).read_text(encoding="utf-8")

    assert "arkhai-apicredits-storefront==0.2.0" in dockerfile
    assert "COPY domains/apicredits/storefront/src" not in dockerfile
    assert 'ENV PYTHONPATH="/app"' not in dockerfile
