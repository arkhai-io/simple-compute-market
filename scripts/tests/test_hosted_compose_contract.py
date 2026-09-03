from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest
import tomllib

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE = (REPO_ROOT / "compose.hosted-settlement.yml").read_text(encoding="utf-8")
ROOT_MAKE = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
E2E_MAKE = (REPO_ROOT / "e2e-tests" / "Makefile").read_text(encoding="utf-8")
WORKFLOW = (REPO_ROOT / ".github" / "workflows" / "hosted-stripe-test.yml").read_text(
    encoding="utf-8"
)


def test_authority_port_coexists_with_registry_container_port() -> None:
    base = (REPO_ROOT / "domains" / "vms" / "compose.yml").read_text(encoding="utf-8")
    assert '"8080:8080"' in base
    assert '"127.0.0.1:${HOSTED_SETTLEMENT_HOST_PORT:-18080}:8080"' in COMPOSE
    assert '"127.0.0.1:${HOSTED_STOREFRONT_HOST_PORT:-18081}:8001"' in COMPOSE
    assert 'base_url = "http://127.0.0.1:8080"' in (
        REPO_ROOT / "e2e-tests" / "config" / "hosted-storefront.toml"
    ).read_text(encoding="utf-8")
    assert "network_mode: service:hosted-settlement-api" in COMPOSE
    assert "aliases: [bob-storefront]" in COMPOSE


def test_compose_contains_only_ordinary_hosted_roles() -> None:
    for service in (
        "hosted-settlement-migrate:",
        "hosted-settlement-api:",
        "hosted-settlement-worker:",
    ):
        assert service in COMPOSE
    for retired in (
        "hosted-settlement-simulator",
        "hosted-settlement-control",
        "hosted-settlement-admit-fixture",
        "hosted-settlement-event-worker",
        "hosted-compose-control",
        "hosted-e2e-runner",
        "hosted-hermetic",
        "controlled-clock",
        "controlled-events",
    ):
        assert retired not in COMPOSE
    assert 'command: ["hosted-settlement-migrate"]' in COMPOSE
    assert 'command: ["hosted-settlement-api"' in COMPOSE
    assert 'command: ["hosted-settlement-worker"' in COMPOSE
    worker = COMPOSE.split("  hosted-settlement-worker:", 1)[1].split(
        "\n  provisioning:", 1
    )[0]
    assert 'test: ["CMD", "python", "-c", "__import__(\'os\').kill(1,0)"]' in worker


def test_compose_has_no_source_or_editable_sibling_mount() -> None:
    lowered = COMPOSE.lower()
    assert "../hosted-settlement" not in lowered
    assert "editable" not in lowered
    assert "/src" not in lowered
    assert "source: ${HOSTED_SETTLEMENT_VERIFIED_RELEASE_DIR" in COMPOSE
    assert "read_only: true" in COMPOSE


def test_hosted_storefront_uses_hosted_inventory_seed() -> None:
    storefront = COMPOSE.split("  bob-storefront:", 1)[1].split("\nvolumes:", 1)[0]
    assert (
        "e2e-tests/config/hosted-resources.csv:/app/hosted-resources.csv:ro"
        in storefront
    )
    provisioning = COMPOSE.split("  provisioning:", 1)[1].split("  bob-storefront:", 1)[
        0
    ]
    assert "PROVISIONING_INVENTORY_INI:" in provisioning
    assert "kvm1 ansible_host=127.0.0.1 ansible_user=stub" in provisioning


def test_only_hosted_service_secret_environment_is_required() -> None:
    assert "HOSTED_SETTLEMENT_ENV_FILE:?" in COMPOSE
    assert "HOSTED_SETTLEMENT_E2E" not in COMPOSE
    preparer = (REPO_ROOT / "scripts" / "prepare-hosted-compose.py").read_text(
        encoding="utf-8"
    )
    for token in ("SECRET", "TOKEN", "CREDENTIAL", "PRIVATE_KEY", "WEBHOOK"):
        assert token in preparer


def test_protected_report_signer_is_role_scoped_masked_and_ephemeral() -> None:
    assert ".evidence_signer_credential" in WORKFLOW
    assert ".evidence_signer_scheme" in WORKFLOW
    assert ".evidence_signer_identifier" in WORKFLOW
    assert 'echo "::add-mask::$value"' in WORKFLOW
    for variable in (
        "HOSTED_SETTLEMENT_E2E_EVIDENCE_SIGNER_CREDENTIAL",
        "HOSTED_SETTLEMENT_E2E_EVIDENCE_SIGNER_SCHEME",
        "HOSTED_SETTLEMENT_E2E_EVIDENCE_SIGNER_IDENTIFIER",
    ):
        assert f"export {variable}=" in WORKFLOW
        assert f"unset {variable}" in WORKFLOW


def test_protected_lane_activates_one_attested_marketplace_consumer_image() -> None:
    storefront = COMPOSE.split("  bob-storefront:", 1)[1].split("\nvolumes:", 1)[0]
    assert (
        "image: ${HOSTED_MARKETPLACE_VERIFIED_IMAGE:?run the selected marketplace "
        "release preflight}"
    ) in storefront
    preflight = ROOT_MAKE.split("prepare-hosted-compose:", 1)[1].split(
        "hosted-compose-up:", 1
    )[0]
    assert 'gh attestation verify "$(HOSTED_MARKETPLACE_RELEASE_MANIFEST)"' in preflight
    assert "--marketplace-manifest-sha256" in preflight
    assert "--marketplace-image-digest" in preflight
    assert "Download exact attested marketplace consumer release" in WORKFLOW
    assert "MARKETPLACE_RELEASE_ARTIFACT" in WORKFLOW
    assert (
        'HOSTED_MARKETPLACE_RELEASE_MANIFEST="$MARKETPLACE_RELEASE_DIR/'
        'marketplace-release-manifest.json"'
    ) in WORKFLOW


def test_up_restart_and_clean_have_distinct_volume_and_recreate_behavior() -> None:
    up = ROOT_MAKE.split("hosted-compose-up:", 1)[1].split(
        "hosted-compose-restart:", 1
    )[0]
    restart = ROOT_MAKE.split("hosted-compose-restart:", 1)[1].split(
        "hosted-compose-clean:", 1
    )[0]
    clean = ROOT_MAKE.split("hosted-compose-clean:", 1)[1].split(
        "hosted-stripe-test:", 1
    )[0]
    assert "hosted-preflight" in up
    assert "up -d --wait" in up
    assert "down" not in up
    assert "--force-recreate" not in up
    assert "up -d --wait --force-recreate" in restart
    assert " restart" not in restart
    assert "down -v" not in restart
    assert " down -v --remove-orphans" in clean
    for variable in (
        "VMS_REGISTRY_ADMIN_API_KEY",
        "VMS_REGISTRY_BOOTSTRAP_API_KEY",
        "VMS_BOB_STOREFRONT_SECRETS_FILE",
        "VMS_REGISTRY_IDENTITY_CREDENTIAL_FILE",
        "VMS_REGISTRY_B_IDENTITY_CREDENTIAL_FILE",
        "VMS_PROVISIONING_IDENTITY_ENV_FILE",
    ):
        assert variable in clean


def test_only_production_and_protected_stripe_targets_exist() -> None:
    for target in (
        "hosted-preflight:",
        "hosted-compose-up:",
        "hosted-compose-restart:",
        "hosted-compose-clean:",
        "hosted-stripe-test:",
    ):
        assert target in ROOT_MAKE
    for retired in (
        "hosted-hermetic-preflight:",
        "hosted-hermetic:",
        "hosted-local-eas:",
        "build-hosted:",
        "hosted-real-stripe:",
        "hosted-compose-start:",
    ):
        assert retired not in ROOT_MAKE
        assert retired not in E2E_MAKE


def test_active_composition_has_no_fixture_or_simulator_selector() -> None:
    surfaces = (
        REPO_ROOT / "Makefile",
        REPO_ROOT / "compose.hosted-settlement.yml",
        REPO_ROOT / "e2e-tests" / "Dockerfile",
        REPO_ROOT / "e2e-tests" / "Makefile",
        REPO_ROOT / "scripts" / "prepare-hosted-compose.py",
        REPO_ROOT / "scripts" / "verify-hosted-release.py",
    )
    forbidden = (
        "arkhai_hosted_settlement_e2e",
        "HOSTED_E2E_FIXTURE",
        "HOSTED_E2E_MANIFEST",
        "hosted-hermetic",
        "hosted-settlement-simulator",
        "hosted-settlement-control",
        "hosted-settlement-event-worker",
        "controlled-clock",
        "controlled-events",
        "e2e-fixture-wheel",
        "e2e-manifest",
        "verify_hermetic_release",
    )
    for path in surfaces:
        content = path.read_text(encoding="utf-8")
        assert not set(forbidden).intersection(content.split())
        for token in forbidden:
            assert token not in content, (
                f"{path.relative_to(REPO_ROOT)} contains {token}"
            )


def test_wallet_free_fixtures_have_only_public_portable_configuration() -> None:
    forbidden = {
        "wallet",
        "chains",
        "rpc_url",
        "private_key",
        "webhook",
        "database",
        "administrator",
        "control_url",
        "stripe_secret",
        "provider",
    }

    def field_paths(value: object) -> set[str]:
        if not isinstance(value, Mapping):
            return set()
        result = {str(key).lower() for key in value}
        for child in value.values():
            result.update(field_paths(child))
        return result

    expected_urls = {
        "hosted-storefront.toml": "http://127.0.0.1:8080",
        "hosted-buyer.toml": "http://hosted-settlement-api:8080",
    }
    for filename, expected_url in expected_urls.items():
        path = REPO_ROOT / "e2e-tests" / "config" / filename
        document = tomllib.loads(path.read_text(encoding="utf-8"))
        if filename == "hosted-storefront.toml":
            assert "Identity" in document
        else:
            assert "BuyerProfile" in document
        assert document["Settlement"]["stripe"]["enabled"] is True
        assert document["Settlement"]["stripe"]["base_url"] == expected_url
        assert field_paths(document).isdisjoint(forbidden)
        stripe = document["Settlement"]["stripe"]
        assert "expected_api_version" not in stripe
        assert "expected_schema_version" not in stripe
        assert "required_capabilities" not in stripe


def test_marketplace_hosted_configs_contain_no_provider_fixture_identity() -> None:
    for filename in ("hosted-storefront.toml", "hosted-buyer.toml"):
        content = (REPO_ROOT / "e2e-tests" / "config" / filename).read_text(
            encoding="utf-8"
        )
        for forbidden in (
            "fixture-account",
            "account_ref",
            "connected_account",
            "provider_credential",
            "webhook_secret",
            "control_url",
        ):
            assert forbidden not in content


@pytest.mark.parametrize(
    "field,value",
    (
        ("manifest_digest", "sha256:" + "0" * 64),
        ("schema_version", 3),
        ("capabilities", []),
    ),
)
def test_ready_gate_rejects_digest_schema_and_capability_mismatch(
    field: str, value: object
) -> None:
    import importlib.util

    path = REPO_ROOT / "scripts" / "verify-hosted-release.py"
    spec = importlib.util.spec_from_file_location("hosted_ready_verifier", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    production = {
        "manifest_digest": "sha256:" + "1" * 64,
        "api_version": "0.2.0",
        "schema_version": 5,
        "capabilities": ["required.v2"],
    }
    response = {
        "ready": True,
        "manifest_digest": production["manifest_digest"],
        "api_version": production["api_version"],
        "schema_version": production["schema_version"],
        "capabilities": production["capabilities"],
    }
    response[field] = value
    with pytest.raises(module.ReleaseVerificationError, match="ready response"):
        module.verify_ready_response(production, response)


def test_the_readiness_check_names_no_release_of_its_own() -> None:
    """It asserts the bound contract, and is handed it rather than stating it.

    A literal here refuses every release but one -- including the next real
    one -- as an unready authority, which is indistinguishable from a genuine
    contract mismatch.
    """

    api = COMPOSE.split("  hosted-settlement-api:", 1)[1].split(
        "\n  hosted-settlement-worker:", 1
    )[0]
    check = api.split("healthcheck:", 1)[1]

    for named in ("0.2.1", "0.3.0", "schema_version')==5", "conditional-escrow.v2"):
        assert named not in check, named
    for handed in (
        "HOSTED_VERIFIED_API_VERSION",
        "HOSTED_VERIFIED_SCHEMA_VERSION",
        "HOSTED_VERIFIED_CAPABILITIES",
        "HOSTED_VERIFIED_FUNDING_PROFILES",
        "HOSTED_VERIFIED_PRODUCTION_MANIFEST_DIGEST",
    ):
        assert handed in check, handed
        assert f"{handed}: ${{HOSTED_SETTLEMENT_VERIFIED_" in COMPOSE or handed.endswith(
            "PRODUCTION_MANIFEST_DIGEST"
        )


def test_a_development_run_can_bind_a_producer_built_here() -> None:
    """One variable selects it, and the two places that say so agree."""

    assert "HOSTED_LOCAL_HOSTED_IMAGE ?=" in ROOT_MAKE
    assert "build-hosted-producer:" in ROOT_MAKE
    assert "$(MAKE) -C \"$(HOSTED_SETTLEMENT_SOURCE)\" image artifacts" in ROOT_MAKE
    for selector in ("HOSTED_PRODUCER_INPUTS", "HOSTED_PRODUCER_PINS"):
        assert f"{selector} = $(if $(HOSTED_LOCAL_HOSTED_IMAGE)" in ROOT_MAKE
    local = ROOT_MAKE.split("hosted-stripe-test-local:", 1)[1].split("\nhosted-compose-up:", 1)[0]
    assert "$(HOSTED_PRODUCER_PINS)" in local
    # The protected target keeps every pin it has, spelled out.
    protected = ROOT_MAKE.split("\nhosted-stripe-test:", 1)[1].split("\nhosted-compose-up:", 1)[0]
    for pin in (
        "--hosted-manifest-sha256",
        "--hosted-client-wheel-sha256",
        "--hosted-image-digest",
        "--hosted-source-commit",
        "--hosted-workflow-ref",
        "--hosted-workflow-run-id",
    ):
        assert f'{pin} "$(HOSTED_PRODUCTION_' in protected, pin
    assert "HOSTED_PRODUCER_PINS" not in protected


def test_the_released_producer_identities_come_from_the_trust_config() -> None:
    """Five of six, so a development run stops copying digests in by hand.

    The trust config is named here rather than left to the default, because the
    default follows whichever version the tree pins and that version is signed
    only after it is published. What this asserts is that the identities are
    derived from whatever config is in force, which is independent of which one
    that currently is.
    """

    trust_path = REPO_ROOT / "manifests" / "hosted-settlement-v0.2.1-trust.json"
    trust = json.loads(trust_path.read_text(encoding="utf-8"))
    derived = subprocess.run(
        [
            "make",
            "--no-print-directory",
            "-f",
            str(REPO_ROOT / "Makefile"),
            "-n",
            "hosted-stripe-test-local",
            f"HOSTED_RELEASE_TRUST={trust_path}",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    ).stdout

    for value in (
        "sha256:" + trust["manifest_sha256"],
        "sha256:" + trust["client_wheel"]["sha256"],
        trust["service_image"]["digest"],
        trust["source_commit"],
        trust["workflow_ref"],
    ):
        assert value in derived, value
    # The run id is not in the trust config and stays an operator input.
    assert 'HOSTED_PRODUCTION_WORKFLOW_RUN_ID ?=\n' in ROOT_MAKE


def test_the_build_names_the_artifacts_of_the_release_it_binds(tmp_path: Path) -> None:
    """A later release needs a trust config, not an edit to three Makefiles.

    The client wheel filename was spelled out beside the trust config it had to
    agree with. Nothing kept the two in step, so the first thing a version bump
    broke was a path that silently named the previous release.

    The generated contract documents were checked here too, while the build
    staged them. It no longer does, so what remains is the wheel the verifier
    reads.
    """

    trust = tmp_path / "trust.json"
    trust.write_text(
        json.dumps({"release_version": "0.3.0", "schema_version": 6}),
        encoding="utf-8",
    )

    recipe = subprocess.run(
        [
            "make",
            "-n",
            "verify-hosted-release",
            f"HOSTED_RELEASE_TRUST={trust}",
            f"HOSTED_RELEASE_DIR={tmp_path / 'release'}",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    assert "arkhai_hosted_settlement_client-0.3.0-py3-none-any.whl" in recipe
    assert "0.2.1" not in recipe


@pytest.mark.parametrize(
    "makefile",
    ["Makefile", "kit/hosted-settlement/Makefile", "domains/vms/storefront/Makefile"],
)
def test_no_makefile_spells_the_client_wheel_it_verifies(makefile: str) -> None:
    text = (REPO_ROOT / makefile).read_text(encoding="utf-8")

    assert "arkhai_hosted_settlement_client-0.2.1" not in text
