from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
ROOT_README = ROOT / "README.md"
GET_STARTED = ROOT / "docs/get-started.md"
ROLE_ENTRYPOINTS = ROOT / "docs/role-entrypoints.md"
ROOT_MAKEFILE = ROOT / "Makefile"
DOCKER_COMPOSE = ROOT / "docker-compose.yml"
DEPLOY_LOCAL_SH = ROOT / "market-contract-deployer/deploy-local.sh"


def test_newcomer_docs_stop_advertising_compose_local() -> None:
    readme = ROOT_README.read_text(encoding="utf-8")
    get_started = GET_STARTED.read_text(encoding="utf-8")
    role_entrypoints = ROLE_ENTRYPOINTS.read_text(encoding="utf-8")

    assert "Docker Compose local stack is deprecated" in readme
    assert "## Full Local Stack (Docker Compose)" not in readme
    assert "make deploy-local" not in readme

    assert "local compose" not in get_started
    assert "local compose" not in role_entrypoints


def test_root_makefile_deprecates_compose_targets() -> None:
    text = ROOT_MAKEFILE.read_text(encoding="utf-8")

    assert "build: build-cli build-registry build-core" in text
    assert "compose_local is deprecated" in text
    assert "deploy-local:\n\tdocker compose up" not in text


def test_checked_in_compose_surfaces_fail_fast_with_deprecation_notice() -> None:
    compose_text = DOCKER_COMPOSE.read_text(encoding="utf-8")
    deploy_text = DEPLOY_LOCAL_SH.read_text(encoding="utf-8")

    assert "compose_local is deprecated" in compose_text
    assert "compose_local is deprecated" in deploy_text
    assert "exit 1" in deploy_text
