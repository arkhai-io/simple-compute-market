import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALLER = REPO_ROOT / "scripts" / "install-remote.sh"


def _installer_text() -> str:
    return INSTALLER.read_text(encoding="utf-8")


def test_remote_installer_uses_github_release_assets():
    text = _installer_text()

    assert "downloadMarketCli" not in text
    assert "cloudfunctions.net" not in text
    assert (
        'GITHUB_RELEASES_BASE="https://github.com/arkhai-io/simple-compute-market/releases"'
        in text
    )
    assert 'TARBALL_NAME="market-cli.tar.gz"' in text
    assert '${GITHUB_RELEASES_BASE}/latest/download' in text
    assert '${GITHUB_RELEASES_BASE}/download/${version}' in text
    assert '${TARBALL_NAME}.sha256' in text


def test_remote_installer_latest_and_pinned_url_shape():
    text = _installer_text()
    base = re.search(r'^GITHUB_RELEASES_BASE="([^"]+)"$', text, re.MULTILINE)
    tarball = re.search(r'^TARBALL_NAME="([^"]+)"$', text, re.MULTILINE)

    assert base is not None
    assert tarball is not None

    releases_base = base.group(1)
    tarball_name = tarball.group(1)

    assert f"{releases_base}/latest/download/{tarball_name}" == (
        "https://github.com/arkhai-io/simple-compute-market/releases/latest/download/"
        "market-cli.tar.gz"
    )
    assert f"{releases_base}/download/market-cli-v0.5.1/{tarball_name}" == (
        "https://github.com/arkhai-io/simple-compute-market/releases/download/"
        "market-cli-v0.5.1/market-cli.tar.gz"
    )
