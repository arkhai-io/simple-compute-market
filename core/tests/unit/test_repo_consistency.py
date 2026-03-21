from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from service.clients.alkahest import BASE_SEPOLIA_ADDRESSES


ROOT = Path(__file__).resolve().parents[3]
ASYNC_PROD_ENV = ROOT / "async-provisioning-service/.env.production.sample"
AGENT_PROD_ENV = ROOT / "core/agent/.env.production.sample"
INVENTORY_PATH = ROOT / "compute-provisioning-iac/ansible/inventory/hosts"
ASYNC_DOCKERFILE = ROOT / "async-provisioning-service/Dockerfile"
ASYNC_README = ROOT / "async-provisioning-service/README.md"
ASYNC_START_SCRIPT = ROOT / "async-provisioning-service/start.sh"
ASYNC_CONTAINER_SMOKE_TEST = (
    ROOT / "async-provisioning-service/tests/integration/test_container_smoke.py"
)
RUNBOOK_PATH = ROOT / "docs/production-canary.md"
E2E_PLAN_PATH = ROOT / "docs/e2e-deployment-test-plan.md"
CHECKLIST_PATH = ROOT / "docs/deployment-input-checklist.md"
STANDUP_DIR = ROOT / "docs/standup"
STANDUP_OVERVIEW_PATH = STANDUP_DIR / "overview.md"
STANDUP_IMAGE_SELECTION_PATH = STANDUP_DIR / "image-selection.md"
STANDUP_CONTRACTS_PATH = STANDUP_DIR / "contracts.md"
STANDUP_ZEROTIER_FRP_PATH = STANDUP_DIR / "zerotier-frp.md"
STANDUP_REGISTRY_PATH = STANDUP_DIR / "registry.md"
STANDUP_PROVISIONING_PATH = STANDUP_DIR / "provisioning.md"
STANDUP_AGENT_SELLER_PATH = STANDUP_DIR / "agent-seller.md"
STANDUP_AGENT_BUYER_PATH = STANDUP_DIR / "agent-buyer.md"
STANDUP_RESOURCE_SEEDING_PATH = STANDUP_DIR / "resource-seeding.md"
STANDUP_CANARY_PATH = STANDUP_DIR / "canary.md"
SUBAGENT_DIR = ROOT / "docs/subagents"
SUBAGENT_INDEX_PATH = SUBAGENT_DIR / "README.md"
SUBAGENT_LOCAL_STACK_PATH = SUBAGENT_DIR / "local-stack.md"
SUBAGENT_REGISTRY_PATH = SUBAGENT_DIR / "registry-deploy.md"
SUBAGENT_PROVISIONING_PATH = SUBAGENT_DIR / "provisioning-deploy.md"
SUBAGENT_IAC_PATH = SUBAGENT_DIR / "iac-host-kit.md"
SUBAGENT_AGENT_SELLER_PATH = SUBAGENT_DIR / "agent-seller.md"
SUBAGENT_AGENT_BUYER_PATH = SUBAGENT_DIR / "agent-buyer.md"
SUBAGENT_NETWORK_PATH = SUBAGENT_DIR / "network-overlay.md"
SUBAGENT_CANARY_PATH = SUBAGENT_DIR / "canary-e2e.md"
SUBAGENT_ROLLBACK_PATH = SUBAGENT_DIR / "rollback.md"
SUBAGENT_CLEAN_ROOM_PATH = SUBAGENT_DIR / "clean-room.md"
SUBAGENT_SUMMARY_PATH = SUBAGENT_DIR / "2026-03-20-audit-summary.md"
CANARY_MODULE_PATH = ROOT / "cli/market/canary.py"
ALKAHEST_REPO = ROOT.parent / "alkahest"
ALKAHEST_BASE_DEPLOYMENT = (
    ALKAHEST_REPO / "contracts/deployments/deployment_base_sepolia.json"
)
PROVISIONING_IAC_GITIGNORE = ROOT / "compute-provisioning-iac/.gitignore"
PROVISIONING_IAC_README = ROOT / "compute-provisioning-iac/README.md"
PROVISIONING_IAC_MAKEFILE = ROOT / "compute-provisioning-iac/Makefile"
PROVISIONING_IAC_VM_CONTRACT_TESTS = (
    ROOT / "compute-provisioning-iac/tests/test_vm_management_contracts.py"
)
PROVISIONING_IAC_ACCEPTANCE_SCRIPT = (
    ROOT / "compute-provisioning-iac/scripts/run_acceptance_validation.sh"
)
FRP_SETUP_TASKS = ROOT / "compute-provisioning-iac/ansible/roles/frp-setup/tasks/main.yml"
VM_SETUP_SYSTEM_PACKAGES = (
    ROOT / "compute-provisioning-iac/ansible/roles/vm-setup/tasks/system-packages.yml"
)
VM_CREATE_TASKS = ROOT / "compute-provisioning-iac/ansible/roles/vm-management/tasks/vm-create.yml"
VM_PREREQUISITES_TASKS = ROOT / "compute-provisioning-iac/ansible/roles/vm-management/tasks/prerequisites.yml"
VM_UNDEFINE_TASKS = ROOT / "compute-provisioning-iac/ansible/roles/vm-management/tasks/vm-undefine.yml"
GROUP_VARS_ALL = ROOT / "compute-provisioning-iac/ansible/group_vars/all.yml"
AGENT_DATA_DIR = ROOT / "core/agent/app/data"
REGISTRY_CONFIG = ROOT / "erc-8004-registry-py/src/config.py"
REGISTRY_README = ROOT / "erc-8004-registry-py/README.md"
REGISTRY_DOCKERFILE = ROOT / "erc-8004-registry-py/Dockerfile"
REGISTRY_MAKEFILE = ROOT / "erc-8004-registry-py/Makefile"
REGISTRY_CONTAINER_SMOKE_TEST = (
    ROOT / "erc-8004-registry-py/tests/integration/test_container_smoke.py"
)
CORE_CONTAINER_SMOKE_TEST = ROOT / "core/tests/integration/test_container_smoke.py"
LOCAL_DUAL_AGENT_E2E_TEST = ROOT / "tests/e2e/test_local_dual_agent_stack.py"
CONTRACTS_PACKAGE_JSON = ROOT / "erc-8004-contracts/package.json"
CONTRACTS_PACKAGE_LOCK = ROOT / "erc-8004-contracts/package-lock.json"
CONTRACTS_NVMRC = ROOT / "erc-8004-contracts/.nvmrc"
FULL_REPO_VALIDATION_SCRIPT = ROOT / "scripts/run_full_repo_validation.py"
RELEASE_GATE_SCRIPT = ROOT / "scripts/run_release_gate_checks.py"
TEST_MATRIX_WORKFLOW = ROOT / ".github/workflows/test-matrix.yml"
ENTRYPOINT_PATH = ROOT / "core/entrypoint.sh"
ROOT_README = ROOT / "README.md"
AGENT_README = ROOT / "core/agent/README.md"
TRAINING_README = ROOT / "domain/compute/training/README.md"
GITMODULES_PATH = ROOT / ".gitmodules"


def _parse_env_file(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        env[key] = value
    return env


def _parse_inventory(path: Path) -> dict[str, set[str]]:
    inventory: dict[str, set[str]] = {}
    section: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1]
            inventory.setdefault(section, set())
            continue
        if section is None:
            continue
        alias = stripped.split()[0]
        inventory[section].add(alias)
    return inventory


def _parse_script_args(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    return set(re.findall(r'add_argument\("(?P<arg>--[a-z0-9-]+)"', text))


def _parse_semver_floor(raw: str) -> tuple[int, int, int]:
    stripped = raw.strip().lstrip("^~<>=")
    core = stripped.split("-", 1)[0]
    parts = core.split(".")
    padded = (parts + ["0", "0", "0"])[:3]
    return tuple(int(part) for part in padded)


def _parse_runbook_args(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    section_match = re.search(
        r"## Canary smoke run\s+(?P<section>.*?)(?:\n## |\Z)",
        text,
        re.DOTALL,
    )
    if section_match:
        text = section_match.group("section")
    ignored = {"--no-config"}
    return {
        arg
        for arg in re.findall(r"(--[a-z0-9-]+)", text)
        if arg not in ignored
    }


def _iter_markdown_paths() -> list[Path]:
    return [
        ROOT / "README.md",
        *sorted((ROOT / "docs").rglob("*.md")),
        ROOT / "domain/compute/training/README.md",
        ROOT / "erc-8004-registry-py/README.md",
        ROOT / "async-provisioning-service/README.md",
        ROOT / "core/agent/README.md",
        ROOT / "compute-provisioning-iac/README.md",
    ]


def test_async_provisioning_production_sample_includes_required_runtime_vars() -> None:
    env = _parse_env_file(ASYNC_PROD_ENV)
    required = {
        "DATABASE_URL",
        "REDIS_URL",
        "REDIS_QUEUE_NAME",
        "ANSIBLE_TIMEOUT_SECONDS",
        "DEFAULT_VM_HOST",
        "ANSIBLE_BECOME_PASS",
        "ZEROTIER_NETWORK",
        "ENABLE_AUTH",
        "AUTH_FAIL_OPEN",
        "REGISTRY_URL",
        "REGISTRY_CACHE_TTL_SECONDS",
        "REGISTRY_CACHE_MAX_SIZE",
        "ENABLE_RATE_LIMITING",
        "RATE_LIMIT_REQUESTS_PER_MINUTE",
        "FRP_SERVER_ADDR",
        "FRP_DOMAIN",
        "FRP_DASHBOARD_PASSWORD",
        "SSH_PRIVATE_KEY",
        "MANAGEMENT_VARS_YAML",
    }

    missing = sorted(required - env.keys())
    assert not missing, f"Missing required async provisioning env vars: {missing}"
    assert env["ENABLE_AUTH"] == "true"
    assert env["AUTH_FAIL_OPEN"] == "false"


def test_async_provisioning_contract_does_not_reference_admin_secret() -> None:
    dockerfile_text = ASYNC_DOCKERFILE.read_text(encoding="utf-8")
    readme_text = ASYNC_README.read_text(encoding="utf-8")
    sample_text = ASYNC_PROD_ENV.read_text(encoding="utf-8")

    assert "ADMIN_SECRET" not in dockerfile_text
    assert "ADMIN_SECRET" not in readme_text
    assert "ADMIN_SECRET" not in sample_text


def test_repo_exposes_canonical_full_repo_validation_entrypoint() -> None:
    assert FULL_REPO_VALIDATION_SCRIPT.exists(), (
        "scripts/run_full_repo_validation.py must exist as the canonical "
        "full-matrix test entrypoint"
    )


def test_repo_exposes_ci_test_matrix_workflow() -> None:
    assert TEST_MATRIX_WORKFLOW.exists(), (
        ".github/workflows/test-matrix.yml must exist for the canonical "
        "full-matrix CI workflow"
    )

    text = TEST_MATRIX_WORKFLOW.read_text(encoding="utf-8")
    assert "scripts/run_full_repo_validation.py" in text
    assert "node-version: 22.12.0" in text or "node-version: '22.12.0'" in text


def test_repo_exposes_release_gate_entrypoint() -> None:
    assert RELEASE_GATE_SCRIPT.exists(), (
        "scripts/run_release_gate_checks.py must exist as the canonical "
        "expanded release gate entrypoint"
    )


def test_compute_provisioning_iac_exposes_validation_entrypoints() -> None:
    assert PROVISIONING_IAC_MAKEFILE.exists(), (
        "compute-provisioning-iac/Makefile must exist with runnable IaC "
        "validation entrypoints"
    )

    text = PROVISIONING_IAC_MAKEFILE.read_text(encoding="utf-8")
    for required_token in (
        "validate:",
        "validate-inventory:",
        "validate-playbooks:",
        "ansible/inventory/hosts --list",
        "playbooks/frp/frp-server-setup.yaml --syntax-check",
        "playbooks/frp/docker-app-setup.yaml --syntax-check",
        "playbooks/host-kit/vm-setup.yaml --syntax-check",
        "playbooks/single-tenant/vm-operations.yaml --syntax-check",
    ):
        assert required_token in text, (
            "compute-provisioning-iac/Makefile is missing a validation contract "
            f"token: {required_token}"
        )


def test_compute_provisioning_iac_readme_documents_validation_entrypoints() -> None:
    text = PROVISIONING_IAC_README.read_text(encoding="utf-8")

    for required_token in (
        "## Validation",
        "make validate",
        "make validate-inventory",
        "make validate-playbooks",
    ):
        assert required_token in text, (
            "compute-provisioning-iac/README.md must document the validation "
            f"entrypoints: {required_token}"
        )


def test_compute_provisioning_iac_makefile_exposes_vm_contract_tests() -> None:
    text = PROVISIONING_IAC_MAKEFILE.read_text(encoding="utf-8")

    for required_token in (
        "validate-tests:",
        "validate: validate-inventory validate-playbooks validate-tests",
        "python3 -m unittest discover -s tests -p 'test_*.py' -v",
    ):
        assert required_token in text, (
            "compute-provisioning-iac/Makefile must expose the VM lifecycle "
            f"contract tests via '{required_token}'"
        )


def test_compute_provisioning_iac_role_contract_tests_exist_and_cover_vm_lifecycle() -> None:
    text = PROVISIONING_IAC_VM_CONTRACT_TESTS.read_text(encoding="utf-8")

    for required_token in (
        "VmManagementContractTests",
        "test_main_orchestrates_prerequisites_actions_and_json_output",
        "test_prerequisites_fail_fast_if_vm_already_exists",
        "test_vm_create_reads_frp_dashboard_from_compressed_response_env",
        "test_vm_destroy_emits_force_destroy_json_contract",
        "test_vm_undefine_requires_stopped_vm_and_cleans_up_access_artifacts",
        "test_json_output_exports_create_destroy_and_undefine_payloads",
    ):
        assert required_token in text, (
            "compute-provisioning-iac VM lifecycle contract tests are "
            f"missing '{required_token}'"
        )


def test_compute_provisioning_iac_readme_documents_vm_contract_test_entrypoint() -> None:
    text = PROVISIONING_IAC_README.read_text(encoding="utf-8")

    for required_token in (
        "make validate-tests",
        "VM lifecycle contract tests",
        "tests/test_vm_management_contracts.py",
    ):
        assert required_token in text, (
            "compute-provisioning-iac/README.md must document the VM "
            f"contract test path including '{required_token}'"
        )


def test_compute_provisioning_iac_exposes_acceptance_validation_entrypoint() -> None:
    makefile_text = PROVISIONING_IAC_MAKEFILE.read_text(encoding="utf-8")
    script_text = PROVISIONING_IAC_ACCEPTANCE_SCRIPT.read_text(encoding="utf-8")

    for required_token in (
        "validate-acceptance:",
        "./scripts/run_acceptance_validation.sh",
    ):
        assert required_token in makefile_text, (
            "compute-provisioning-iac/Makefile must expose the heavier IaC "
            f"acceptance path via '{required_token}'"
        )

    for required_token in (
        "ansible/playbooks/host-kit/vm-setup.yaml",
        "ansible/playbooks/single-tenant/vm-operations.yaml",
        "vm_action=create",
        "vm_action=check",
        "vm_action=destroy",
        "vm_action=undefine",
        "--limit",
        "KVM_HOST",
    ):
        assert required_token in script_text, (
            "compute-provisioning-iac/scripts/run_acceptance_validation.sh "
            f"is missing acceptance token '{required_token}'"
        )


def test_compute_provisioning_iac_readme_documents_optional_acceptance_path() -> None:
    text = PROVISIONING_IAC_README.read_text(encoding="utf-8")

    for required_token in (
        "make validate-acceptance",
        "run_acceptance_validation.sh",
        "not part of the default CI",
        "KVM_HOST=ww1",
        "host-kit",
        "vm_action=create",
        "vm_action=undefine",
    ):
        assert required_token in text, (
            "compute-provisioning-iac/README.md must document the heavier IaC "
            f"acceptance path including '{required_token}'"
        )


def test_async_provisioning_startup_regenerates_matching_public_ssh_key() -> None:
    text = ASYNC_START_SCRIPT.read_text(encoding="utf-8")

    assert "ssh-keygen -y -f ~/.ssh/id_ed25519" in text
    assert "~/.ssh/id_ed25519.pub" in text


def test_async_provisioning_makefile_exposes_container_smoke_target() -> None:
    text = (ROOT / "async-provisioning-service/Makefile").read_text(encoding="utf-8")

    for required_token in (
        "test-container-smoke:",
        "uv run pytest tests/integration/test_container_smoke.py -q",
    ):
        assert required_token in text, (
            "async-provisioning-service/Makefile must expose the container "
            f"smoke target via '{required_token}'"
        )


def test_async_provisioning_container_smoke_test_exists_and_covers_runtime_stack() -> None:
    text = ASYNC_CONTAINER_SMOKE_TEST.read_text(encoding="utf-8")

    for required_token in (
        "docker compose",
        "redis:7-alpine",
        "postgres:16-alpine",
        "/api/v1/jobs",
        "/health",
        "credentials",
        "Processing job",
    ):
        assert required_token in text, (
            "async-provisioning-service container smoke coverage is missing "
            f"'{required_token}'"
        )


def test_async_provisioning_readme_documents_container_smoke_path() -> None:
    text = ASYNC_README.read_text(encoding="utf-8")

    for required_token in (
        "make test-container-smoke",
        "Redis",
        "Postgres",
        "worker",
        "/api/v1/jobs",
    ):
        assert required_token in text, (
            "async-provisioning-service/README.md must document the container "
            f"smoke path including '{required_token}'"
        )


def test_core_makefile_exposes_container_smoke_target() -> None:
    text = (ROOT / "core/Makefile").read_text(encoding="utf-8")

    for required_token in (
        "test-container-smoke:",
        "uv run pytest tests/integration/test_container_smoke.py -q",
    ):
        assert required_token in text, (
            "core/Makefile must expose the container smoke target via "
            f"'{required_token}'"
        )


def test_core_container_smoke_test_exists_and_covers_env_persistence_contract() -> None:
    text = CORE_CONTAINER_SMOKE_TEST.read_text(encoding="utf-8")

    for required_token in (
        "docker build",
        "docker run",
        "ENV_FILE",
        "ONCHAIN_AGENT_ID",
        "BASE_URL_OVERRIDE",
        "ZEROTIER_IP",
        "/.well-known/agent-card.json",
        "/.well-known/erc-8004-registration.json",
    ):
        assert required_token in text, (
            "core container smoke coverage is missing "
            f"'{required_token}'"
        )


def test_core_agent_readme_documents_container_smoke_path() -> None:
    text = AGENT_README.read_text(encoding="utf-8")

    for required_token in (
        "make test-container-smoke",
        "ENV_FILE",
        "ONCHAIN_AGENT_ID",
        "BASE_URL_OVERRIDE",
        "ZEROTIER_IP",
        "/.well-known/agent-card.json",
    ):
        assert required_token in text, (
            "core/agent/README.md must document the container smoke path "
            f"including '{required_token}'"
        )


def test_root_makefile_exposes_local_dual_agent_e2e_target() -> None:
    text = (ROOT / "Makefile").read_text(encoding="utf-8")

    for required_token in (
        "test-local-e2e:",
        "cd core && uv --no-config run pytest ../tests/e2e/test_local_dual_agent_stack.py -q",
    ):
        assert required_token in text, (
            "Makefile must expose the local dual-agent e2e target via "
            f"'{required_token}'"
        )


def test_local_dual_agent_e2e_test_exists_and_covers_stack_contract() -> None:
    text = LOCAL_DUAL_AGENT_E2E_TEST.read_text(encoding="utf-8")

    for required_token in (
        "docker compose",
        "18080",
        "18000",
        "18001",
        "/resources/portfolio",
        "/orders/create",
        "/orders/close",
        "maker_attestation",
        "accepted",
    ):
        assert required_token in text, (
            "local dual-agent e2e coverage is missing "
            f"'{required_token}'"
        )


def test_root_readme_documents_local_dual_agent_e2e_path() -> None:
    text = ROOT_README.read_text(encoding="utf-8")

    for required_token in (
        "make test-local-e2e",
        "/resources/portfolio",
        "/orders/create",
        "/orders/close",
        "seller agent",
        "buyer agent",
    ):
        assert required_token in text, (
            "README.md must document the local dual-agent e2e path including "
            f"'{required_token}'"
        )


def test_production_default_vm_hosts_exist_in_inventory() -> None:
    inventory = _parse_inventory(INVENTORY_PATH)
    kvm_hosts = inventory.get("kvm_hosts", set())
    agent_env = _parse_env_file(AGENT_PROD_ENV)
    provisioning_env = _parse_env_file(ASYNC_PROD_ENV)

    defaults = {
        "core/agent/.env.production.sample": agent_env["DEFAULT_VM_HOST"],
        "async-provisioning-service/.env.production.sample": provisioning_env[
            "DEFAULT_VM_HOST"
        ],
    }
    missing = [
        f"{source} -> {vm_host}"
        for source, vm_host in defaults.items()
        if vm_host not in kvm_hosts
    ]
    assert not missing, f"Unknown DEFAULT_VM_HOST values: {missing}"


def test_inventory_contains_environment_host_aliases() -> None:
    inventory = _parse_inventory(INVENTORY_PATH)
    required = {
        "frp_servers": {"proxy-dev", "proxy-staging", "proxy-production"},
        "provisioning_servers": {
            "provisioning-dev",
            "provisioning-staging",
            "provisioning-production",
        },
        "kvm_hosts": {"ww1"},
    }

    missing: list[str] = []
    for section, aliases in required.items():
        section_aliases = inventory.get(section, set())
        for alias in sorted(aliases - section_aliases):
            missing.append(f"{section}:{alias}")
    assert not missing, f"Missing inventory aliases: {missing}"


def test_vm_create_role_uses_stable_current_ubuntu_image_url() -> None:
    vm_create = VM_CREATE_TASKS.read_text(encoding="utf-8")

    assert "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img" in vm_create
    assert re.search(r"cloud-images\\.ubuntu\\.com/noble/\\d{8}/", vm_create) is None
    assert "packer_variables.iso_url" not in vm_create


def test_vm_management_defaults_to_supported_lts_os_variant() -> None:
    group_vars = GROUP_VARS_ALL.read_text(encoding="utf-8")
    prerequisites = VM_PREREQUISITES_TASKS.read_text(encoding="utf-8")

    assert "os_variant: ubuntu-lts-latest" in group_vars
    assert "ubuntu24.04" not in prerequisites


def test_production_canary_runbook_matches_smoke_script_cli() -> None:
    script_args = _parse_script_args(CANARY_MODULE_PATH)
    runbook_args = _parse_runbook_args(RUNBOOK_PATH)
    documented_required_args = {
        "--registry-url",
        "--provisioning-url",
        "--seller-agent-url",
        "--buyer-agent-url",
        "--seller-agent-id",
        "--buyer-agent-id",
        "--seller-private-key",
        "--buyer-private-key",
        "--gpu-model",
        "--region",
        "--token-symbol",
        "--token-amount",
        "--ssh-private-key-path",
    }

    undocumented = sorted(documented_required_args - runbook_args)
    unknown = sorted(runbook_args - script_args)
    assert not undocumented, f"Runbook is missing documented required args: {undocumented}"
    assert not unknown, f"Runbook references args not supported by smoke script: {unknown}"


def test_canonical_standup_docs_exist() -> None:
    required_paths = [
        STANDUP_OVERVIEW_PATH,
        STANDUP_IMAGE_SELECTION_PATH,
        STANDUP_ZEROTIER_FRP_PATH,
        STANDUP_REGISTRY_PATH,
        STANDUP_PROVISIONING_PATH,
        STANDUP_AGENT_SELLER_PATH,
        STANDUP_AGENT_BUYER_PATH,
        STANDUP_RESOURCE_SEEDING_PATH,
        STANDUP_CANARY_PATH,
    ]

    missing = [str(path.relative_to(ROOT)) for path in required_paths if not path.exists()]
    assert not missing, f"Missing canonical stand-up docs: {missing}"


def test_root_readme_points_to_canonical_standup_docs() -> None:
    text = ROOT_README.read_text(encoding="utf-8")

    assert "docs/standup/overview.md" in text
    assert "docs/standup/canary.md" in text


def test_image_selection_doc_defines_deployable_manifest_contract() -> None:
    text = STANDUP_IMAGE_SELECTION_PATH.read_text(encoding="utf-8")

    for required_heading in (
        "## Inputs",
        "## Output Manifest",
        "## Publish Paths",
        "## Verification",
    ):
        assert required_heading in text, (
            f"image-selection.md is missing section: {required_heading}"
        )

    for required_token in (
        "/etc/simple-market-service/image-manifest.env",
        "REGISTRY_IMAGE=",
        "PROVISIONING_IMAGE=",
        "SELLER_AGENT_IMAGE=",
        "BUYER_AGENT_IMAGE=",
        "@sha256:",
        ".github/workflows/docker-build-push-erc8004-registry.yml",
        ".github/workflows/docker-build-push-async-provisioning.yml",
        ".github/workflows/docker-build-push-core-agent.yml",
        "git rev-parse HEAD",
    ):
        assert required_token in text, (
            f"image-selection.md is missing image-manifest detail: {required_token}"
        )


def test_deployed_service_runbooks_reference_image_manifest() -> None:
    for path in (
        STANDUP_REGISTRY_PATH,
        STANDUP_PROVISIONING_PATH,
        STANDUP_AGENT_SELLER_PATH,
        STANDUP_AGENT_BUYER_PATH,
    ):
        text = path.read_text(encoding="utf-8")
        assert "docs/standup/image-selection.md" in text, (
            f"{path.name} must point to the canonical image-selection doc"
        )
        assert "/etc/simple-market-service/image-manifest.env" in text, (
            f"{path.name} must document the shared image manifest"
        )


def test_deployment_docs_reference_canonical_standup_overview() -> None:
    required_paths = [RUNBOOK_PATH, E2E_PLAN_PATH, CHECKLIST_PATH]

    missing: list[str] = []
    for path in required_paths:
        text = path.read_text(encoding="utf-8")
        if "docs/standup/overview.md" not in text:
            missing.append(path.name)
    assert not missing, (
        "Deployment docs must point to the canonical stand-up overview: "
        f"{missing}"
    )


def test_standup_overview_includes_contract_bootstrap_step() -> None:
    text = STANDUP_OVERVIEW_PATH.read_text(encoding="utf-8")

    assert "contracts.md" in text
    assert "Contract Address Bootstrap" in text


def test_root_readme_uses_current_core_agent_paths() -> None:
    text = ROOT_README.read_text(encoding="utf-8")

    assert "`agent/`" not in text
    assert "cd agent" not in text
    assert re.search(r"(?<!core/)agent/\.env", text) is None
    assert "`core/agent/`" in text
    assert "cd core/agent" in text


def test_root_readme_documents_full_local_compose_stack() -> None:
    text = ROOT_README.read_text(encoding="utf-8")

    for required_token in (
        "Docker",
        "Docker Compose",
        "/dev/net/tun",
        "Linux host",
        "make init-submodules",
        "make build",
        "make deploy-local",
        "make stop-local",
        "~/.ssh/id_ed25519",
        "http://localhost:18080/health",
        "http://localhost:18081/health",
        "http://localhost:18000/.well-known/agent-card.json",
        "http://localhost:18001/.well-known/agent-card.json",
    ):
        assert required_token in text, (
            f"README.md is missing local compose stack guidance: {required_token}"
        )


def test_makefile_local_build_path_does_not_require_zerotier_install() -> None:
    text = (ROOT / "Makefile").read_text(encoding="utf-8")

    build_cli_line = next(
        line for line in text.splitlines() if line.startswith("build-cli:")
    )
    assert "init-dependencies" not in build_cli_line
    assert "init-zero-tier" not in build_cli_line
    assert "init-prerequisites" in build_cli_line

    assert "init-registry:\n\tcd erc-8004-registry-py && make init" in text


def test_zerotier_frp_standup_doc_defines_service_network_model() -> None:
    text = STANDUP_ZEROTIER_FRP_PATH.read_text(encoding="utf-8")

    for required_heading in (
        "## Inputs",
        "## ZeroTier",
        "## FRP",
        "## Verification",
    ):
        assert required_heading in text, (
            f"zerotier-frp.md is missing section: {required_heading}"
        )

    for required_token in (
        "FRP is only used for leased VM SSH access",
        "Do not put the registry or agent HTTP APIs behind FRP",
        "https://frp-admin.<domain>",
        "FRP_SERVER_ADDR",
        "FRP_DOMAIN",
        "FRP_DASHBOARD_PASSWORD",
        'curl -u "${FRP_USER}:${FRP_PASSWORD}"',
        "${FRP_API_URL}/serverinfo",
        "ping -c 1 <peer-zerotier-ip>",
        "curl http://<registry-zerotier-ip>:8080/health",
        "curl http://<seller-zerotier-ip>:8000/.well-known/agent-card.json",
    ):
        assert required_token in text, (
            f"zerotier-frp.md is missing overlay detail: {required_token}"
        )


def test_core_agent_readme_does_not_reference_missing_deployment_readme() -> None:
    text = AGENT_README.read_text(encoding="utf-8")

    assert "deployment/README.md" not in text
    assert "docs/standup/agent-seller.md" in text
    assert "docs/standup/agent-buyer.md" in text


def test_registry_readme_uses_tracked_env_sample_names() -> None:
    text = REGISTRY_README.read_text(encoding="utf-8")

    assert ".env.example" not in text
    assert ".env.sample" in text
    assert ".env.production.sample" in text


def test_registry_makefile_exposes_container_smoke_target() -> None:
    text = REGISTRY_MAKEFILE.read_text(encoding="utf-8")

    for required_token in (
        "test-container-smoke:",
        "uv run pytest tests/integration/test_container_smoke.py -q",
    ):
        assert required_token in text, (
            "erc-8004-registry-py/Makefile must expose the container smoke "
            f"target via '{required_token}'"
        )


def test_registry_container_smoke_test_exists_and_covers_runtime_stack() -> None:
    text = REGISTRY_CONTAINER_SMOKE_TEST.read_text(encoding="utf-8")

    for required_token in (
        "docker compose",
        "postgres:16-alpine",
        "ghcr.io/foundry-rs/foundry",
        "/health",
        "/agents",
        "/orders",
        "Event sync service started",
    ):
        assert required_token in text, (
            "erc-8004-registry-py container smoke coverage is missing "
            f"'{required_token}'"
        )


def test_registry_readme_documents_container_smoke_path() -> None:
    text = REGISTRY_README.read_text(encoding="utf-8")

    for required_token in (
        "make test-container-smoke",
        "Docker",
        "Postgres",
        "Anvil",
        "/health",
    ):
        assert required_token in text, (
            "erc-8004-registry-py/README.md must document the container smoke "
            f"path including '{required_token}'"
        )


def test_compute_provisioning_iac_readme_uses_current_repo_paths() -> None:
    text = PROVISIONING_IAC_README.read_text(encoding="utf-8")

    assert "image-and-ssh-provisioning-iac/ansible" not in text
    assert "compute-provisioning-iac/ansible" in text


@pytest.mark.parametrize(
    ("path", "env_path", "container_name"),
    [
        (
            STANDUP_AGENT_SELLER_PATH,
            "/etc/simple-market-service/seller-agent.env",
            "sms-seller-agent",
        ),
        (
            STANDUP_AGENT_BUYER_PATH,
            "/etc/simple-market-service/buyer-agent.env",
            "sms-buyer-agent",
        ),
    ],
)
def test_agent_standup_docs_cover_container_runtime_contract(
    path: Path,
    env_path: str,
    container_name: str,
) -> None:
    text = path.read_text(encoding="utf-8")
    required = {
        env_path,
        f"ENV_FILE={env_path}",
        "docker pull",
        "docker run -d",
        container_name,
        "--cap-add NET_ADMIN",
        "--cap-add SYS_MODULE",
        "--device /dev/net/tun:/dev/net/tun",
        "/var/lib/zerotier-one",
        "grep '^ONCHAIN_AGENT_ID='",
        "CHAIN_ID=84532",
        "IDENTITY_REGISTRY_ADDRESS",
        "REPUTATION_REGISTRY_ADDRESS",
        "VALIDATION_REGISTRY_ADDRESS",
        "/.well-known/agent-card.json",
        "/.well-known/erc-8004-registration.json",
    }

    missing = sorted(token for token in required if token not in text)
    assert not missing, (
        f"{path.name} is missing executable deployment runtime coverage: {missing}"
    )


def test_seller_agent_standup_doc_covers_portfolio_verification() -> None:
    text = STANDUP_AGENT_SELLER_PATH.read_text(encoding="utf-8")

    assert "/resources/portfolio" in text
    assert "resource-seeding.md" in text


@pytest.mark.parametrize(
    ("path", "env_path"),
    [
        (STANDUP_AGENT_SELLER_PATH, "/etc/simple-market-service/seller-agent.env"),
        (STANDUP_AGENT_BUYER_PATH, "/etc/simple-market-service/buyer-agent.env"),
    ],
)
def test_agent_deployment_docs_are_executable_runbooks(
    path: Path,
    env_path: str,
) -> None:
    text = path.read_text(encoding="utf-8")

    for required_heading in (
        "## Inputs",
        "## Image",
        "## Host Preparation",
        "## Container Launch",
        "## Registration And Identity Capture",
        "## Verification",
    ):
        assert required_heading in text, f"{path.name} is missing section: {required_heading}"

    for required_token in (
        env_path,
        "docker pull",
        "docker run",
        "ENV_FILE=",
        "/var/lib/market",
        "/var/lib/zerotier-one",
        "ONCHAIN_AGENT_ID",
        "BASE_URL_OVERRIDE",
        "ZEROTIER_IP",
        "/.well-known/agent-card.json",
        "/.well-known/erc-8004-registration.json",
    ):
        assert required_token in text, f"{path.name} is missing deployment detail: {required_token}"


def test_seller_deployment_doc_references_resource_seeding_and_portfolio_verification() -> None:
    text = STANDUP_AGENT_SELLER_PATH.read_text(encoding="utf-8")

    assert "docs/standup/resource-seeding.md" in text
    assert "/resources/portfolio" in text


def test_resource_seeding_doc_uses_deployed_seller_paths() -> None:
    text = STANDUP_RESOURCE_SEEDING_PATH.read_text(encoding="utf-8")

    for required_token in (
        "/etc/simple-market-service/seller-agent.env",
        "make import-resources",
        "market portfolio import-csv",
        "core/agent/app/data/resources.sample.csv",
        "grep '^BASE_URL_OVERRIDE=' /etc/simple-market-service/seller-agent.env",
        "/resources/portfolio",
        "docs/standup/canary.md",
    ):
        assert required_token in text, (
            f"resource-seeding.md is missing deployment detail: {required_token}"
        )


def test_standup_canary_doc_covers_prereq_collection_flow() -> None:
    text = STANDUP_CANARY_PATH.read_text(encoding="utf-8")

    for required_token in (
        "/etc/simple-market-service/prod-canary.env",
        "python scripts/run_deployment_gate_checks.py --skip-smoke-help",
        "python scripts/validate_deployment_bundle.py",
        "--vm-host",
        "CANARY_VM_HOSTS",
        "--ssh-private-key-path",
        "docs/e2e-runbook.md",
        "docs/production-canary.md",
    ):
        assert required_token in text, (
            f"canary.md is missing prerequisite or execution detail: {required_token}"
        )


def test_registry_standup_doc_is_executable_runbook() -> None:
    text = STANDUP_REGISTRY_PATH.read_text(encoding="utf-8")

    for required_heading in (
        "## Inputs",
        "## Image",
        "## Host Preparation",
        "## Container Launch",
        "## Verification",
        "## Outputs",
    ):
        assert required_heading in text, (
            f"registry.md is missing section: {required_heading}"
        )

    for required_token in (
        "docs/standup/contracts.md",
        "/etc/simple-market-service/contracts.env",
        "/etc/simple-market-service/registry.env",
        "docker pull",
        "docker run",
        "docker login -u oauth2accesstoken --password-stdin",
        "DATABASE_URL",
        "RPC_URL",
        "IDENTITY_REGISTRY_ADDRESS",
        "REPUTATION_REGISTRY_ADDRESS",
        "VALIDATION_REGISTRY_ADDRESS",
        "host is already joined to the ZeroTier network",
        "does not join ZeroTier from inside the container",
        "docker ps",
        "docker logs --tail 200 sms-registry",
        "curl http://<registry-host>:8080/health",
    ):
        assert required_token in text, (
            f"registry.md is missing deployment detail: {required_token}"
        )


def test_contract_bootstrap_doc_is_executable_runbook() -> None:
    text = STANDUP_CONTRACTS_PATH.read_text(encoding="utf-8")

    for required_heading in (
        "## Inputs",
        "## Use Published Base Sepolia Registries",
        "## Record The Shared Contract Bundle",
        "## Verification",
        "## Outputs",
    ):
        assert required_heading in text, (
            f"contracts.md is missing section: {required_heading}"
        )

    for required_token in (
        "erc-8004-contracts/README.md",
        "Base Sepolia",
        "/etc/simple-market-service/contracts.env",
        "CHAIN_ID=84532",
        "RPC_URL=https://<rpc-provider>",
        "IDENTITY_REGISTRY_ADDRESS=",
        "REPUTATION_REGISTRY_ADDRESS=",
        "VALIDATION_REGISTRY_ADDRESS=",
        "eth_getCode",
    ):
        assert required_token in text, (
            f"contracts.md is missing contract-bootstrap detail: {required_token}"
        )


def test_contracts_submodule_points_to_canonical_upstream() -> None:
    gitmodules = GITMODULES_PATH.read_text(encoding="utf-8")
    assert "https://github.com/erc-8004/erc-8004-contracts.git" in gitmodules


def test_contracts_package_declares_hardhat_test_entrypoint() -> None:
    package = json.loads(CONTRACTS_PACKAGE_JSON.read_text(encoding="utf-8"))
    package_lock = json.loads(CONTRACTS_PACKAGE_LOCK.read_text(encoding="utf-8"))

    assert "test" in package["scripts"]
    assert "hardhat" in package["devDependencies"]
    assert "node_modules/hardhat" in package_lock["packages"]


def test_contracts_package_declares_node_runtime_metadata() -> None:
    package = json.loads(CONTRACTS_PACKAGE_JSON.read_text(encoding="utf-8"))

    assert CONTRACTS_NVMRC.exists(), "erc-8004-contracts must declare its Node runtime in .nvmrc"
    engines = package.get("engines")
    assert isinstance(engines, dict), "erc-8004-contracts/package.json must declare engines"
    node_range = engines.get("node")
    assert isinstance(node_range, str) and node_range, (
        "erc-8004-contracts/package.json must declare engines.node"
    )

    nvmrc_version = CONTRACTS_NVMRC.read_text(encoding="utf-8").strip()
    assert nvmrc_version == "22.12.0"
    assert "22.12.0" in node_range, (
        "erc-8004-contracts engines.node should align with the pinned .nvmrc version"
    )


def test_registry_readme_points_deployed_users_to_standup_runbook() -> None:
    text = REGISTRY_README.read_text(encoding="utf-8")

    assert "docs/standup/registry.md" in text
    assert "docs/standup/overview.md" in text


@pytest.mark.parametrize(
    "path",
    [
        STANDUP_REGISTRY_PATH,
        STANDUP_AGENT_SELLER_PATH,
        STANDUP_AGENT_BUYER_PATH,
    ],
)
def test_deployed_service_docs_reference_shared_contract_bundle(path: Path) -> None:
    text = path.read_text(encoding="utf-8")

    assert "/etc/simple-market-service/contracts.env" in text, (
        f"{path.name} must reference the shared deployed contract bundle"
    )


def test_provisioning_standup_doc_is_executable_runbook() -> None:
    text = STANDUP_PROVISIONING_PATH.read_text(encoding="utf-8")

    for required_heading in (
        "## Inputs",
        "## Image",
        "## Host Preparation",
        "## Container Launch",
        "## Verification",
        "## Outputs",
    ):
        assert required_heading in text, (
            f"provisioning.md is missing section: {required_heading}"
        )

    for required_token in (
        "/etc/simple-market-service/provisioning.env",
        "/etc/simple-market-service/management-vars.yaml",
        "docker pull",
        "docker run",
        "DATABASE_URL",
        "REDIS_URL",
        "ENABLE_AUTH=true",
        "AUTH_FAIL_OPEN=false",
        "SSH_PRIVATE_KEY",
        "MANAGEMENT_VARS_YAML",
        "base64 < /path/to/id_ed25519",
        "/app/compute-provisioning-iac/ansible/inventory/management-vars.yaml",
        "compute-provisioning-iac/ansible/inventory/hosts",
        "compute-provisioning-iac/ansible/inventory/vm-vars-example.yaml",
        "root_ssh_filename",
        "golden_image_name",
        "gcs_bucket_url",
        "gcs_image_path",
        "image_setup_type=scratch does not require management-vars.yaml",
        "image_setup_type=golden requires management-vars.yaml",
        "worker",
        "docker logs --tail 200 sms-provisioning",
        "SSH private key written to ~/.ssh/id_ed25519",
        "management-vars.yaml written to /app/compute-provisioning-iac/ansible/inventory/management-vars.yaml",
        "curl http://<provisioning-host>:8081/health",
    ):
        assert required_token in text, (
            f"provisioning.md is missing deployment detail: {required_token}"
        )


def test_async_provisioning_readme_points_deployed_users_to_standup_runbook() -> None:
    text = ASYNC_README.read_text(encoding="utf-8")

    assert "docs/standup/provisioning.md" in text
    assert "docs/standup/overview.md" in text


def test_registry_makefile_uses_tracked_docker_compose_env_file() -> None:
    text = REGISTRY_MAKEFILE.read_text(encoding="utf-8")

    assert ".env.docker " not in text
    assert ".env.docker-compose" in text


def test_training_readme_uses_current_core_agent_paths() -> None:
    text = TRAINING_README.read_text(encoding="utf-8")

    assert "cd agent" not in text
    assert "Run from `/agent`" not in text
    assert "cd core/agent" in text
    assert "core/agent/.env.sample" in text


def test_markdown_relative_links_resolve() -> None:
    missing: list[str] = []
    pattern = re.compile(r"\[[^\]]+\]\((?!https?://|mailto:|#)([^)]+\.md)\)")

    for path in _iter_markdown_paths():
        text = path.read_text(encoding="utf-8")
        for raw_target in pattern.findall(text):
            target = raw_target.split("#", 1)[0]
            resolved = (path.parent / target).resolve()
            if not resolved.exists():
                missing.append(
                    f"{path.relative_to(ROOT)} -> {raw_target}"
                )

    assert not missing, f"Broken markdown links: {missing}"


def test_subagent_prompt_docs_exist_for_all_deployment_paths() -> None:
    required_paths = [
        SUBAGENT_INDEX_PATH,
        SUBAGENT_LOCAL_STACK_PATH,
        SUBAGENT_REGISTRY_PATH,
        SUBAGENT_PROVISIONING_PATH,
        SUBAGENT_IAC_PATH,
        SUBAGENT_AGENT_SELLER_PATH,
        SUBAGENT_AGENT_BUYER_PATH,
        SUBAGENT_NETWORK_PATH,
        SUBAGENT_CANARY_PATH,
        SUBAGENT_ROLLBACK_PATH,
        SUBAGENT_CLEAN_ROOM_PATH,
        SUBAGENT_SUMMARY_PATH,
    ]

    missing = [str(path.relative_to(ROOT)) for path in required_paths if not path.exists()]
    assert not missing, f"Missing subagent prompt docs: {missing}"


@pytest.mark.parametrize(
    "path",
    [
        SUBAGENT_LOCAL_STACK_PATH,
        SUBAGENT_REGISTRY_PATH,
        SUBAGENT_PROVISIONING_PATH,
        SUBAGENT_IAC_PATH,
        SUBAGENT_AGENT_SELLER_PATH,
        SUBAGENT_AGENT_BUYER_PATH,
        SUBAGENT_NETWORK_PATH,
        SUBAGENT_CANARY_PATH,
        SUBAGENT_ROLLBACK_PATH,
        SUBAGENT_CLEAN_ROOM_PATH,
    ],
)
def test_subagent_prompt_docs_define_audit_contract(path: Path) -> None:
    text = path.read_text(encoding="utf-8")

    for required_heading in (
        "# ",
        "## Goal",
        "## Inputs",
        "## Procedure",
        "## Output Contract",
    ):
        assert required_heading in text, (
            f"{path.name} is missing subagent prompt section: {required_heading}"
        )

    for required_token in (
        "file/line references",
        "Do not assume prior chat context",
        "blockers",
    ):
        assert required_token in text, (
            f"{path.name} is missing subagent prompt requirement: {required_token}"
        )


def test_subagent_audit_summary_covers_all_prompt_paths() -> None:
    text = SUBAGENT_SUMMARY_PATH.read_text(encoding="utf-8")

    for required_token in (
        "local-stack",
        "registry-deploy",
        "provisioning-deploy",
        "iac-host-kit",
        "agent-seller",
        "agent-buyer",
        "network-overlay",
        "canary-e2e",
        "rollback",
        "clean-room",
        "clean-room verdict",
    ):
        assert required_token in text, (
            f"Audit summary is missing path result: {required_token}"
        )


def test_resource_seeding_doc_uses_deployed_seller_paths() -> None:
    text = STANDUP_RESOURCE_SEEDING_PATH.read_text(encoding="utf-8")

    for required_token in (
        "/etc/simple-market-service/seller-agent.env",
        "/var/lib/market/agent.db",
        "make import-resources",
        "market portfolio import-csv",
        "/resources/portfolio",
        "quarantined canary resource",
    ):
        assert required_token in text, (
            "resource-seeding.md is missing deployed seller coverage: "
            f"{required_token}"
        )


def test_standup_canary_doc_covers_prerequisite_sequence() -> None:
    text = STANDUP_CANARY_PATH.read_text(encoding="utf-8")

    for required_heading in (
        "## Required Inputs",
        "## Prerequisites",
        "## Gate Sequence",
        "## Live Verification",
        "## Smoke Run",
        "## Success Criteria",
        "## Failure Handling",
    ):
        assert required_heading in text, (
            f"canary.md is missing section: {required_heading}"
        )

    for required_token in (
        "python scripts/run_deployment_gate_checks.py --skip-smoke-help",
        "python scripts/validate_deployment_bundle.py",
        ". /etc/simple-market-service/prod-canary.env",
        "set -a",
        "set +a",
        "curl http://<registry-host>:<registry-port>/health",
        "curl http://<seller-host>:<seller-port>/resources/portfolio",
        "--vm-host",
        "CANARY_VM_HOSTS",
        "CANARY_GPU_QUANTITY",
        "CANARY_DURATION_HOURS",
        "CANARY_MATCH_SALT",
        "`--vm-host` flags override `CANARY_VM_HOSTS`",
        "`--frp-dashboard-url` and `--frp-dashboard-password` must be provided together",
        "--ssh-private-key-path",
    ):
        assert required_token in text, (
            "canary.md is missing executable canary prerequisite coverage: "
            f"{required_token}"
        )


def test_standup_canary_doc_points_to_actionable_rollback_runbook() -> None:
    text = STANDUP_CANARY_PATH.read_text(encoding="utf-8")

    assert "../production-canary.md#rollback" in text


def test_production_canary_doc_matches_runner_contract() -> None:
    text = RUNBOOK_PATH.read_text(encoding="utf-8")

    for required_token in (
        "/etc/simple-market-service/prod-canary.env",
        "SELLER_AGENT_URL=",
        "BUYER_AGENT_URL=",
        "SELLER_AGENT_ID=",
        "BUYER_AGENT_ID=",
        "SELLER_PRIVATE_KEY=",
        "BUYER_PRIVATE_KEY=",
        "SSH_PRIVATE_KEY_PATH=",
        "CANARY_VM_HOSTS=",
        "CANARY_GPU_QUANTITY=",
        "CANARY_DURATION_HOURS=",
        "CANARY_MATCH_SALT=",
        "--seller-agent-url",
        "--buyer-agent-url",
        "--seller-agent-id",
        "--buyer-agent-id",
        "--seller-private-key",
        "--buyer-private-key",
        "--ssh-private-key-path",
        "--frp-dashboard-url",
        "--frp-dashboard-password",
        "`--vm-host` flags override `CANARY_VM_HOSTS`",
        "[order] seller order:",
        "[order] buyer order:",
        "[provisioning] succeeded job:",
    ):
        assert required_token in text, (
            f"production-canary.md is missing runner-contract detail: {required_token}"
        )


def test_production_canary_rollback_is_self_contained() -> None:
    text = RUNBOOK_PATH.read_text(encoding="utf-8")

    for required_token in (
        "Preserve the exact runner output, provisioning job ID, and canary order IDs.",
        "/api/v1/jobs/${CANARY_JOB_ID}",
        "/api/v1/jobs/${CANARY_JOB_ID}/cancel",
        "X-Agent-ID: ${SELLER_AGENT_ID}",
        "CANARY_VM_HOST",
        "CANARY_VM_NAME",
        "SELLER_ORDER_ID",
        "BUYER_ORDER_ID",
        "update_order",
        "destroy",
        "undefine",
        "Close any canary orders that remained open.",
        "Verify that the provisioned guest is stopped and reclaimed before retrying.",
        "Re-run the repo gates after any repo-side fix.",
        "stop the guest domains first",
        "libvirt can block shutdown",
    ):
        assert required_token in text, (
            f"production-canary.md is missing rollback detail: {required_token}"
        )


@pytest.mark.parametrize(
    ("path", "forbidden", "required"),
    [
        (
            RUNBOOK_PATH,
            {
                "core/agent/.env.seller.local",
                "core/agent/.env.buyer.local",
                "async-provisioning-service/.env.local",
                "erc-8004-registry-py/.env.local",
            },
            {
                "/etc/simple-market-service/seller-agent.env",
                "/etc/simple-market-service/buyer-agent.env",
                "/etc/simple-market-service/provisioning.env",
                "/etc/simple-market-service/registry.env",
                "/etc/simple-market-service/prod-canary.env",
            },
        ),
        (
            E2E_PLAN_PATH,
            {
                "core/agent/.env.seller.local",
                "core/agent/.env.buyer.local",
                "async-provisioning-service/.env.local",
                "erc-8004-registry-py/.env.local",
            },
            {
                "/etc/simple-market-service/seller-agent.env",
                "/etc/simple-market-service/buyer-agent.env",
                "/etc/simple-market-service/provisioning.env",
                "/etc/simple-market-service/registry.env",
                "/etc/simple-market-service/prod-canary.env",
            },
        ),
        (
            CHECKLIST_PATH,
            set(),
            {
                "/etc/simple-market-service/seller-agent.env",
                "/etc/simple-market-service/buyer-agent.env",
                "/etc/simple-market-service/provisioning.env",
                "/etc/simple-market-service/registry.env",
                "/etc/simple-market-service/prod-canary.env",
            },
        ),
    ],
)
def test_deployment_docs_use_host_local_env_strategy(
    path: Path,
    forbidden: set[str],
    required: set[str],
) -> None:
    text = path.read_text(encoding="utf-8")

    present_forbidden = sorted(token for token in forbidden if token in text)
    missing_required = sorted(token for token in required if token not in text)

    assert not present_forbidden, (
        f"{path.name} still recommends repo-local deployed env paths: {present_forbidden}"
    )
    assert not missing_required, (
        f"{path.name} is missing required host-local env paths: {missing_required}"
    )


def test_compute_provisioning_iac_ignores_generated_frp_credentials() -> None:
    text = PROVISIONING_IAC_GITIGNORE.read_text(encoding="utf-8")
    assert "credentials/" in text or "credentials/*.json" in text

    tasks_text = FRP_SETUP_TASKS.read_text(encoding="utf-8")
    assert "../../credentials/" in tasks_text or "credentials/frp-server-credentials-" in tasks_text


def test_compute_provisioning_iac_documents_actual_frp_credentials_path() -> None:
    readme_text = PROVISIONING_IAC_README.read_text(encoding="utf-8")
    tasks_text = FRP_SETUP_TASKS.read_text(encoding="utf-8")

    assert "ansible/credentials/frp-server-credentials-" not in readme_text
    assert "ansible/credentials/frp-server-credentials-" not in tasks_text

    assert "credentials/frp-server-credentials-" in readme_text
    assert "credentials/frp-server-credentials-" in tasks_text


def test_compute_provisioning_iac_readme_uses_real_inventory_aliases_and_secret_handoff() -> None:
    text = PROVISIONING_IAC_README.read_text(encoding="utf-8")

    assert "proxy1" not in text
    assert "vm1" not in text
    assert "@/inventory/management-vars.yaml" not in text

    for required_token in (
        "proxy-dev",
        "ww1",
        "build-vars.yaml is only required for golden image creation",
        "management-vars.yaml is only required when runtime VM operations use golden images",
        "--extra-vars @inventory/management-vars.yaml",
        "image_setup_type=scratch",
        "image_setup_type=golden",
        "credentials/frp-server-credentials-<host>-<timestamp>.json",
        "FRP_SERVER_ADDR",
        "FRP_DOMAIN",
        "FRP_DASHBOARD_PASSWORD",
    ):
        assert required_token in text, (
            f"compute-provisioning-iac/README.md is missing host-kit detail: {required_token}"
        )


def test_compute_provisioning_iac_readme_uses_authenticated_provisioning_examples() -> None:
    text = PROVISIONING_IAC_README.read_text(encoding="utf-8")
    assert 'ENABLE_AUTH":"false"' not in text
    assert "ADMIN_SECRET" not in text


def test_compute_provisioning_iac_frp_port_allocator_consults_host_config() -> None:
    text = VM_CREATE_TASKS.read_text(encoding="utf-8")

    assert "/etc/frp/frpc.toml" in text
    assert 'remotePort\\s*=\\s*\\K[0-9]+' in text


def test_compute_provisioning_iac_waits_for_frp_proxy_online_before_success() -> None:
    text = VM_CREATE_TASKS.read_text(encoding="utf-8")

    restart_idx = text.index("Restart FRP client to apply new proxy configuration")
    wait_idx = text.index("Wait for FRP proxy to appear online in dashboard")
    success_idx = text.index("Create JSON data structure for VM creation (generated tenant key)")

    assert restart_idx < wait_idx < success_idx
    assert "/api/proxy/tcp" in text
    assert 'proxy.get("status") == "online"' in text


def test_compute_provisioning_iac_handles_compressed_frp_dashboard_responses() -> None:
    text = VM_CREATE_TASKS.read_text(encoding="utf-8")
    frp_dashboard_curls = re.findall(r'curl [^\n]*/api/proxy/tcp[^\n]*', text)

    assert frp_dashboard_curls, "Expected FRP dashboard API curls in vm-create.yml"
    assert all("--compressed" in command for command in frp_dashboard_curls)


def test_compute_provisioning_iac_wait_task_does_not_consume_frp_json_via_python_heredoc_stdin() -> None:
    text = VM_CREATE_TASKS.read_text(encoding="utf-8")

    wait_idx = text.index("Wait for FRP proxy to appear online in dashboard")
    success_idx = text.index("Create JSON data structure for VM creation (generated tenant key)")
    wait_block = text[wait_idx:success_idx]

    assert 'json.load(sys.stdin)' not in wait_block
    assert 'json.loads(os.environ["FRP_DASHBOARD_RESPONSE"])' in wait_block


def test_compute_provisioning_iac_undefine_allows_cleanup_without_vm_ip() -> None:
    text = VM_UNDEFINE_TASKS.read_text(encoding="utf-8")

    assert "Fail if VM IP cannot be determined" not in text
    assert "Warn if VM IP cannot be determined before cleanup" in text
    assert "Continuing with best-effort cleanup and undefine" in text


def test_agent_production_sample_uses_supported_chain_name() -> None:
    env = _parse_env_file(AGENT_PROD_ENV)
    assert env["CHAIN_NAME"] == "base_sepolia"


def test_agent_production_sample_uses_websocket_rpc_for_alkahest() -> None:
    env = _parse_env_file(AGENT_PROD_ENV)
    assert env["CHAIN_RPC_URL"].startswith("wss://")


def test_agent_production_sample_token_registry_path_points_to_existing_file() -> None:
    env = _parse_env_file(AGENT_PROD_ENV)
    registry_path = Path(env["TOKEN_REGISTRY_PATH"])
    expected_file = AGENT_DATA_DIR / registry_path.name
    assert expected_file.exists(), f"Missing token registry file referenced by sample: {expected_file}"


def test_agent_production_sample_disables_event_queue_for_deployed_canaries() -> None:
    env = _parse_env_file(AGENT_PROD_ENV)
    assert env["ENABLE_EVENT_QUEUE"] == "false"


def test_frp_gateway_role_opens_registry_port_for_colocated_registry() -> None:
    tasks_text = FRP_SETUP_TASKS.read_text(encoding="utf-8")
    assert "port: '18080'" in tasks_text

    readme_text = PROVISIONING_IAC_README.read_text(encoding="utf-8").lower()
    assert "18080" in readme_text
    assert "colocat" in readme_text and "registry" in readme_text and "ufw" in readme_text


def test_registry_runtime_does_not_default_to_public_base_sepolia_rpc() -> None:
    text = REGISTRY_CONFIG.read_text(encoding="utf-8")
    assert "https://sepolia.base.org" not in text
    assert 'rpc_url: str = "http://localhost:8545"' in text


def test_registry_readme_uses_authenticated_rpc_examples() -> None:
    text = REGISTRY_README.read_text(encoding="utf-8")
    assert "RPC_URL=https://sepolia.base.org" not in text
    assert "RPC_URL=https://base-sepolia.infura.io/v3/YOUR_API_KEY" in text


def test_registry_dockerfile_uses_runtime_port_configuration() -> None:
    text = REGISTRY_DOCKERFILE.read_text(encoding="utf-8")
    assert "localhost:8080/health" not in text


def test_agent_entrypoint_re_registers_when_onchain_agent_id_is_noncanonical() -> None:
    text = ENTRYPOINT_PATH.read_text(encoding="utf-8")
    assert 'case "${ONCHAIN_AGENT_ID:-}" in' in text
    assert 'eip155:*) ;;' in text
    assert 'needs_registration=true' in text
    assert 'set -a\n  . "${_env_file}"\n  set +a' in text
    assert text.index('. "${_env_file}"') < text.index("needs_registration=false")
    assert '--env-file="${_env_file}"' in text
    assert "--env_file=" not in text
    assert 'CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080"]' not in text
    assert "/app/.venv/bin/uvicorn" in text
    assert "${PORT:-8080}" in text or "os.environ.get('PORT'" in text or 'os.environ.get("PORT"' in text


def test_agent_production_sample_includes_chain_id_for_deployed_registration() -> None:
    env = _parse_env_file(AGENT_PROD_ENV)
    assert env["CHAIN_ID"] == "84532"


def test_async_provisioning_start_script_respects_runtime_host_port_and_materializes_secrets() -> None:
    text = ASYNC_START_SCRIPT.read_text(encoding="utf-8")

    assert 'HOST="${HOST:-0.0.0.0}"' in text
    assert 'PORT="${PORT:-8081}"' in text
    assert "~/.ssh/id_ed25519" in text
    assert "/app/compute-provisioning-iac/ansible/inventory/management-vars.yaml" in text
    assert "async_provisioning_service.worker" in text
    assert 'uv run uvicorn async_provisioning_service.main:app --host "$HOST" --port "$PORT"' in text


def test_async_provisioning_dockerfile_uses_runtime_port_configuration() -> None:
    text = ASYNC_DOCKERFILE.read_text(encoding="utf-8")

    assert "localhost:8081/health" not in text
    assert (
        "os.environ.get('PORT', '8081')" in text
        or 'os.environ.get("PORT", "8081")' in text
        or 'os.environ.get(\\"PORT\\", \\"8081\\")' in text
    )


def test_compute_provisioning_iac_vm_setup_avoids_missing_debian_packages() -> None:
    text = VM_SETUP_SYSTEM_PACKAGES.read_text(encoding="utf-8")
    assert "virt-top" not in text

    readme_text = PROVISIONING_IAC_README.read_text(encoding="utf-8")
    assert "virt-top" not in readme_text


def test_kvm_host_reboot_guidance_requires_guest_shutdown_first() -> None:
    readme_text = PROVISIONING_IAC_README.read_text(encoding="utf-8").lower()
    assert "shut down running vms before rebooting the host" in readme_text
    assert "libvirtd" in readme_text

    checklist_text = CHECKLIST_PATH.read_text(encoding="utf-8").lower()
    assert "shut down running vms before rebooting a kvm host" in checklist_text


@pytest.mark.parametrize("path", [RUNBOOK_PATH, E2E_PLAN_PATH, CHECKLIST_PATH])
def test_deployment_docs_require_a_dedicated_canary_project(path: Path) -> None:
    text = path.read_text(encoding="utf-8").lower()
    assert "dedicated gcp project" in text or "fresh gcp project" in text


def test_deployment_docs_call_out_artifact_registry_auth_on_remote_agent_hosts() -> None:
    runbook_text = RUNBOOK_PATH.read_text(encoding="utf-8").lower()
    checklist_text = CHECKLIST_PATH.read_text(encoding="utf-8").lower()

    combined = runbook_text + "\n" + checklist_text
    assert "artifact registry" in combined
    assert "docker login" in combined or "configure-docker" in combined
    assert "remote agent host" in combined or "buyer agent host" in combined or "seller agent host" in combined


def test_deployment_docs_call_out_vertex_ai_agent_host_permissions() -> None:
    runbook_text = RUNBOOK_PATH.read_text(encoding="utf-8").lower()
    checklist_text = CHECKLIST_PATH.read_text(encoding="utf-8").lower()

    combined = runbook_text + "\n" + checklist_text
    assert "vertex ai" in combined
    assert "cloud-platform" in combined
    assert "storage admin" in combined or "roles/storage.admin" in combined


def test_deployment_docs_call_out_zerotier_agent_firewall_requirements() -> None:
    runbook_text = RUNBOOK_PATH.read_text(encoding="utf-8").lower()
    checklist_text = CHECKLIST_PATH.read_text(encoding="utf-8").lower()
    plan_text = E2E_PLAN_PATH.read_text(encoding="utf-8").lower()

    combined = runbook_text + "\n" + checklist_text + "\n" + plan_text
    assert "8000/tcp" in combined
    assert "ufw" in combined or "firewall" in combined
    assert "zerotier" in combined


def test_deployment_docs_call_out_inline_order_processing_for_canaries() -> None:
    combined = "\n".join(
        path.read_text(encoding="utf-8").lower()
        for path in (RUNBOOK_PATH, CHECKLIST_PATH, E2E_PLAN_PATH)
    )
    assert "enable_event_queue=false" in combined
    assert "inline" in combined or "queued order processing" in combined


def test_deployed_canary_docs_use_port_8000_for_remote_agent_urls() -> None:
    runbook_text = RUNBOOK_PATH.read_text(encoding="utf-8")
    plan_text = E2E_PLAN_PATH.read_text(encoding="utf-8")

    assert "--seller-agent-url http://<seller-zerotier-ip>:8000" in runbook_text
    assert "--seller-agent-url http://<seller-zerotier-ip>:8000" in plan_text
    assert "--buyer-agent-url http://<buyer-zerotier-ip>:8000" in runbook_text
    assert "--buyer-agent-url http://<buyer-zerotier-ip>:8000" in plan_text


def test_base_sepolia_service_addresses_match_alkahest_deployment_when_available() -> None:
    if not ALKAHEST_BASE_DEPLOYMENT.exists():
        pytest.skip("Sibling alkahest repo is not present next to simple-market-service")

    deployment = json.loads(ALKAHEST_BASE_DEPLOYMENT.read_text(encoding="utf-8"))
    required_mapping = {
        ("arbiters_addresses", "trivial_arbiter"): "trivialArbiter",
        ("arbiters_addresses", "trusted_oracle_arbiter"): "trustedOracleArbiter",
        ("string_obligation_addresses", "obligation"): "stringObligation",
        ("erc20_addresses", "barter_utils"): "erc20BarterUtils",
        ("erc20_addresses", "escrow_obligation_nontierable"): "erc20EscrowObligation",
        ("erc20_addresses", "payment_obligation"): "erc20PaymentObligation",
        ("erc721_addresses", "barter_utils"): "erc721BarterUtils",
        ("erc721_addresses", "escrow_obligation_nontierable"): "erc721EscrowObligation",
        ("erc721_addresses", "payment_obligation"): "erc721PaymentObligation",
        ("erc1155_addresses", "barter_utils"): "erc1155BarterUtils",
        ("erc1155_addresses", "escrow_obligation_nontierable"): "erc1155EscrowObligation",
        ("erc1155_addresses", "payment_obligation"): "erc1155PaymentObligation",
        ("token_bundle_addresses", "barter_utils"): "tokenBundleBarterUtils",
        ("token_bundle_addresses", "escrow_obligation_nontierable"): "tokenBundleEscrowObligation",
        ("token_bundle_addresses", "payment_obligation"): "tokenBundlePaymentObligation",
        ("attestation_addresses", "barter_utils"): "attestationBarterUtils",
        ("attestation_addresses", "escrow_obligation_nontierable"): "attestationEscrowObligation",
        ("attestation_addresses", "escrow_obligation_2_nontierable"): "attestationEscrowObligation2",
    }

    mismatches: list[str] = []
    for (section, key), deployment_key in required_mapping.items():
        actual = BASE_SEPOLIA_ADDRESSES[section][key].lower()
        expected = str(deployment[deployment_key]).lower()
        if actual != expected:
            mismatches.append(
                f"{section}.{key}: service={BASE_SEPOLIA_ADDRESSES[section][key]} "
                f"alkahest={deployment[deployment_key]}"
            )

    assert not mismatches, "Base Sepolia Alkahest address drift detected:\n" + "\n".join(
        mismatches
    )
