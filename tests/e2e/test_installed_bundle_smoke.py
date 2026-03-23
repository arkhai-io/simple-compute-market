from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def _require_installer_tools() -> None:
    for command in ("bash", "tar", "rsync", "git", "uv"):
        if shutil.which(command) is None:
            pytest.skip(f"{command} is not installed")


def test_installed_bundle_smoke(tmp_path: Path) -> None:
    _require_installer_tools()

    tarball_path = tmp_path / "market-cli.tar.gz"
    subprocess.run(
        ["python", "scripts/build_package_tarball.py", "--output", str(tarball_path)],
        cwd=ROOT,
        check=True,
        timeout=1800,
    )

    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()
    with tarfile.open(tarball_path, "r:gz") as archive:
        archive.extractall(extract_dir, filter="data")

    repo_payload = extract_dir / "market-cli"
    assert (repo_payload / "install.sh").exists()

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    shim_dir = tmp_path / "shims"
    shim_dir.mkdir()
    python312_shim = shim_dir / "python3.12"
    python312_shim.symlink_to(Path(sys.executable))

    install_env = os.environ.copy()
    install_env["HOME"] = str(fake_home)
    install_env["MARKET_INSTALL_DIR"] = str(fake_home / ".market")
    install_env["PATH"] = f"{shim_dir}:{install_env['PATH']}"

    subprocess.run(
        ["bash", "install.sh"],
        cwd=repo_payload,
        env=install_env,
        check=True,
        timeout=1800,
    )

    installed_market = fake_home / ".local/bin/market"
    installed_runtime_market = fake_home / ".market/core/.venv/bin/market"
    assert installed_market.exists()
    assert installed_runtime_market.exists()

    subprocess.run(
        [str(installed_market), "--help"],
        cwd=repo_payload,
        env=install_env,
        check=True,
        timeout=120,
    )
    subprocess.run(
        [str(installed_market), "install", "--help"],
        cwd=repo_payload,
        env=install_env,
        check=True,
        timeout=120,
    )
