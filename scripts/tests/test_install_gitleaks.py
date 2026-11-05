"""The pinned gitleaks installs only from an archive matching its pinned sha256, and
a missing or other release is reported with how to install the pinned one."""

from __future__ import annotations

import hashlib
import io
import os
import subprocess
import tarfile
from pathlib import Path

import pytest

import install_gitleaks as installer

ROOT = Path(__file__).resolve().parents[2]


def _archive(content: bytes = b"#!/bin/sh\necho 8.30.1\n", name: str = "gitleaks") -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for member_name, data in ((name, content), ("README.md", b"readme")):
            info = tarfile.TarInfo(member_name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _pins(archive: bytes, sha256: str | None = None) -> installer.Pins:
    return installer.Pins("8.30.1", {"linux_x64": (
        "https://example.invalid/gitleaks.tar.gz",
        sha256 or hashlib.sha256(archive).hexdigest())})


class _Fetch:
    def __init__(self, archive: bytes) -> None:
        self.archive, self.urls = archive, []

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        return self.archive


def test_the_repository_pins_one_release_with_an_archive_for_each_common_platform() -> None:
    pins = installer.read_pins()

    assert pins.version == "8.30.1"
    assert {"linux_x64", "linux_arm64", "darwin_x64", "darwin_arm64"} <= set(pins.archives)
    for name, (url, sha256) in pins.archives.items():
        assert url.endswith(f"/v{pins.version}/gitleaks_{pins.version}_{name}.tar.gz")
        assert len(sha256) == 64 and int(sha256, 16) >= 0


@pytest.mark.parametrize(("system", "machine", "name"), [
    ("Linux", "x86_64", "linux_x64"), ("Linux", "aarch64", "linux_arm64"),
    ("Darwin", "arm64", "darwin_arm64"), ("Darwin", "x86_64", "darwin_x64"),
])
def test_the_platform_is_named_as_gitleaks_names_its_archives(
        system: str, machine: str, name: str) -> None:
    assert installer.platform_name(system, machine) == name


def test_a_matching_archive_installs_an_executable_binary(tmp_path: Path) -> None:
    archive = _archive()

    target = installer.install(tmp_path / "bin", pins=_pins(archive), fetch=_Fetch(archive),
                               platform_="linux_x64")

    assert target == tmp_path / "bin" / "gitleaks"
    assert target.read_bytes() == b"#!/bin/sh\necho 8.30.1\n"
    assert os.access(target, os.X_OK)
    assert sorted(p.name for p in target.parent.iterdir()) == ["gitleaks"]


def test_an_archive_with_another_checksum_is_refused_and_nothing_installed(
        tmp_path: Path) -> None:
    archive = _archive()

    with pytest.raises(installer.InstallError, match="not the pinned"):
        installer.install(tmp_path / "bin", pins=_pins(archive, "0" * 64),
                          fetch=_Fetch(archive), platform_="linux_x64")

    assert not (tmp_path / "bin").exists()


def test_a_platform_with_no_pinned_archive_is_refused_before_any_download(
        tmp_path: Path) -> None:
    fetch = _Fetch(_archive())

    with pytest.raises(installer.InstallError, match="no gitleaks archive for windows_x64"):
        installer.install(tmp_path, pins=_pins(fetch.archive), fetch=fetch,
                          platform_="windows_x64")

    assert fetch.urls == []


@pytest.mark.parametrize(("printed", "expected"), [
    (None, "no gitleaks is on PATH"), ("8.29.0\n", "gitleaks 8.29.0 is on PATH")])
def test_a_missing_or_other_release_is_reported_with_how_to_install_it(
        printed: str | None, expected: str) -> None:
    found = installer.problem(lambda: printed, _pins(b""))

    assert found is not None
    assert "gitleaks 8.30.1 is required" in found and expected in found
    assert "run `make install-gitleaks`" in found


def test_the_pinned_release_on_path_is_no_problem_and_is_not_reinstalled(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fetch = _Fetch(_archive())

    assert installer.problem(lambda: "8.30.1\n", _pins(b"")) is None
    assert installer.main(["--dir", str(tmp_path)], run=lambda: "8.30.1\n", fetch=fetch) == 0
    assert fetch.urls == []
    assert "already installed" in capsys.readouterr().out


def test_an_archive_without_the_binary_is_refused(tmp_path: Path) -> None:
    archive = _archive(name="other")

    with pytest.raises(installer.InstallError, match="holds no gitleaks file"):
        installer.install(tmp_path, pins=_pins(archive), fetch=_Fetch(archive),
                          platform_="linux_x64")


def test_the_command_installs_and_confirms_the_binary_is_the_one_on_path(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    archive = _archive()
    monkeypatch.setattr(installer, "read_pins", lambda: _pins(archive))
    monkeypatch.setattr(installer, "platform_name", lambda: "linux_x64")
    target = tmp_path / "gitleaks"

    assert installer.main(["--dir", str(tmp_path)], run=lambda: None, fetch=_Fetch(archive),
                          which=lambda _: str(target)) == 0
    assert "is the gitleaks on PATH" in capsys.readouterr().out


@pytest.mark.parametrize("shadow", [None, "/usr/local/bin/gitleaks"])
def test_the_command_fails_when_another_gitleaks_or_none_is_on_path(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str], shadow: str | None) -> None:
    archive = _archive()
    monkeypatch.setattr(installer, "read_pins", lambda: _pins(archive))
    monkeypatch.setattr(installer, "platform_name", lambda: "linux_x64")

    assert installer.main(["--dir", str(tmp_path)], run=lambda: None, fetch=_Fetch(archive),
                          which=lambda _: shadow) == 1
    err = capsys.readouterr().err
    assert f"put {tmp_path} first on PATH" in err
    assert (shadow or "no gitleaks") in err


def test_the_command_reports_a_refused_archive_and_fails(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert installer.main(["--dir", str(tmp_path)], run=lambda: None,
                          fetch=_Fetch(b"not the pinned archive")) == 1
    assert "not the pinned" in capsys.readouterr().err
    assert not (tmp_path / "gitleaks").exists()


def test_make_install_gitleaks_runs_the_installer_into_the_named_directory() -> None:
    shown = subprocess.run(
        ["make", "-n", "--no-print-directory", "install-gitleaks",
         "GITLEAKS_INSTALL_DIR=/opt/tools"], cwd=ROOT, capture_output=True, text=True,
        check=True, env={**os.environ, "MAKEFLAGS": ""}).stdout

    assert shown.strip() == 'python3 scripts/install_gitleaks.py --dir "/opt/tools"'
