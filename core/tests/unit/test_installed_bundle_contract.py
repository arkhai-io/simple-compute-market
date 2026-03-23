from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
INSTALL_SH = ROOT / "install.sh"
INSTALLER_DOC = ROOT / "cli/INSTALLER.md"
RELEASE_WORKFLOW = ROOT / ".github/workflows/release-cli.yml"
BUILD_INSTALLER_SCRIPT = ROOT / "scripts/build-installer.sh"
UPLOAD_GCS_SCRIPT = ROOT / "scripts/upload-gcs.sh"
MARKET_CLI = ROOT / "cli/market/cli.py"


def test_installed_bundle_docs_match_canonical_runtime_contract() -> None:
    text = INSTALLER_DOC.read_text(encoding="utf-8")

    assert "core/.venv" in text
    assert "~/.local/bin/market" in text
    assert "cli/.venv" not in text
    assert "~/.market/scripts/" not in text
    assert "Dockerfile.installer-test" not in text


def test_install_script_stops_at_cli_installation_contract() -> None:
    text = INSTALL_SH.read_text(encoding="utf-8")

    assert 'local market_bin="$INSTALL_DIR/core/.venv/bin/market"' in text
    assert "check_docker_running" not in text
    assert '\n        market install\n' not in text
    assert "market install --with-zerotier" not in text
    assert "docker pull" not in text
    assert "gcloud auth activate-service-account" not in text


def test_release_packaging_surfaces_delegate_to_canonical_tarball_builder() -> None:
    expected = "python scripts/build_package_tarball.py"

    for path in (RELEASE_WORKFLOW, BUILD_INSTALLER_SCRIPT, UPLOAD_GCS_SCRIPT):
        text = path.read_text(encoding="utf-8")
        assert expected in text, f"{path} must use the canonical tarball builder"


def test_market_install_uses_canonical_contract_dependency_install() -> None:
    text = MARKET_CLI.read_text(encoding="utf-8")

    assert '["npm", "ci", "--legacy-peer-deps"]' in text
    assert '["npm", "install"]' not in text
