"""The frps and frpc binaries the real-frp tests run, verified against `frp-pins.toml`.

The pins file names the frp release the plugin is tested against and, for each
platform, the official release archive's URL and SHA-256. An archive is verified
against its pin before anything is extracted from it, whether it was just downloaded
or found in the cache, so a cached binary is used only while its archive verifies.
The release's own checksums file is never read: a checksum served from the same place
as the archive proves nothing about it.

`FRPS_BIN` and `FRPC_BIN` name binaries to use instead, as a platform with no pin
needs; they are also the only way the default suite runs the real-frp tests. This
module is test tooling and does not ship in the wheel.
"""

from __future__ import annotations

import hashlib
import http.client
import os
import platform
import re
import shutil
import stat
import tarfile
import tempfile
import tomllib
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO
from urllib.parse import urlsplit

TOOL_DIR = Path(__file__).resolve().parents[1]
PINS_PATH = TOOL_DIR / "frp-pins.toml"
CACHE_DIR = TOOL_DIR / ".frp-cache"
BINARY_NAMES = ("frps", "frpc")
DOWNLOAD_TIMEOUT_SECONDS = 120

_SHA256 = re.compile(r"[0-9a-f]{64}")
_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
# frp names its archives `<os>_<arch>`, with Go's architecture names.
_ARCHITECTURES = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}


class FetchError(Exception):
    """Binaries could not be provided as the pins require: never a reason to skip."""


class NoBinaries(Exception):
    """No binaries are available without fetching, or none can be fetched here."""


@dataclass(frozen=True)
class Archive:
    url: str
    sha256: str

    @property
    def filename(self) -> str:
        return PurePosixPath(urlsplit(self.url).path).name


@dataclass(frozen=True)
class Pins:
    version: str
    archives: Mapping[str, Archive]


@dataclass(frozen=True)
class Binaries:
    """The binaries, and where they came from: the gate prints `provenance`, since a
    run on overrides passes exactly as a run on a verified archive does."""

    frps: Path
    frpc: Path
    provenance: str


def load_pins(path: Path = PINS_PATH) -> Pins:
    """Read the pins file, refusing any member the format does not define."""
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    _only(document, {"version", "archives"}, str(path))
    version = document.get("version")
    archives = document.get("archives")
    if not isinstance(version, str) or not _VERSION.fullmatch(version):
        raise FetchError(f"{path}: version must be a release such as 0.61.1")
    if not isinstance(archives, dict) or not archives:
        raise FetchError(f"{path}: archives must be a table of platforms")
    pinned: dict[str, Archive] = {}
    for name, entry in archives.items():
        where = f"{path}: archives.{name}"
        if not isinstance(entry, dict):
            raise FetchError(f"{where} must be a table")
        _only(entry, {"url", "sha256"}, where)
        url, sha256 = entry.get("url"), entry.get("sha256")
        if (
            not isinstance(url, str)
            or not url.startswith("https://")
            or not Archive(url, "").filename.endswith(".tar.gz")
        ):
            raise FetchError(f"{where}.url must be an https URL of a .tar.gz archive")
        if not isinstance(sha256, str) or not _SHA256.fullmatch(sha256):
            raise FetchError(f"{where}.sha256 must be 64 lowercase hex digits")
        pinned[name] = Archive(url, sha256)
    return Pins(version, pinned)


def _only(table: Mapping[str, object], allowed: set[str], where: str) -> None:
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise FetchError(f"{where}: unknown member(s) {', '.join(unknown)}")


def running_platform() -> str:
    """This machine's platform as frp names its archives, such as `linux_amd64`."""
    machine = platform.machine().lower()
    return f"{platform.system().lower()}_{_ARCHITECTURES.get(machine, machine)}"


def _verify_open(file: BinaryIO, name: str, expected: str) -> None:
    digest = hashlib.sha256()
    for block in iter(lambda: file.read(1 << 20), b""):
        digest.update(block)
    actual = digest.hexdigest()
    if actual != expected:
        raise FetchError(f"{name} has SHA-256 {actual}, but its pin is {expected}")


def verify(path: Path, expected: str) -> None:
    """Refuse `path` unless its SHA-256 is `expected`, naming both digests."""
    with path.open("rb") as file:
        _verify_open(file, path.name, expected)


def extract(archive_path: Path, expected: str, destination: Path) -> Binaries:
    """Verify the archive, then write its `frps` and `frpc` into `destination`.

    The bytes verified are the bytes extracted: one open file is hashed, rewound, and
    read as the archive. Nothing is extracted from an archive that does not verify.
    Each binary is read from its member and written under its own name, so no path
    inside the archive decides where anything is written.
    """
    with archive_path.open("rb") as file:
        _verify_open(file, archive_path.name, expected)
        file.seek(0)
        with tarfile.open(fileobj=file, mode="r:gz") as archive:
            members = {name: _member(archive, name, archive_path) for name in BINARY_NAMES}
            destination.mkdir(parents=True, exist_ok=True)
            for name, member in members.items():
                source = archive.extractfile(member)
                assert source is not None
                with tempfile.NamedTemporaryFile(dir=destination, delete=False) as target:
                    shutil.copyfileobj(source, target)
                written = Path(target.name)
                written.chmod(written.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
                written.replace(destination / name)
    return Binaries(
        destination / "frps",
        destination / "frpc",
        f"{archive_path.name}, verified against its pin: SHA-256 {expected}",
    )


def _member(archive: tarfile.TarFile, name: str, archive_path: Path) -> tarfile.TarInfo:
    found = [
        member
        for member in archive.getmembers()
        if member.isfile() and PurePosixPath(member.name).name == name
    ]
    if len(found) != 1:
        raise FetchError(f"{archive_path.name} holds {len(found)} files named {name}, not one")
    return found[0]


def _download(url: str, target: Path) -> None:
    with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
        with target.open("wb") as file:
            shutil.copyfileobj(response, file)


def cached(archive: Archive, version: str, platform_name: str, cache_dir: Path) -> Binaries | None:
    """The binaries from a cached archive that verifies, or None; never downloads."""
    path = cache_dir / archive.filename
    if not path.is_file():
        return None
    try:
        verify(path, archive.sha256)
    except FetchError:
        return None
    return extract(path, archive.sha256, _binaries_dir(cache_dir, version, platform_name))


def fetch(
    archive: Archive,
    version: str,
    platform_name: str,
    cache_dir: Path,
    download: Callable[[str, Path], None] = _download,
) -> Binaries:
    """The binaries from the cache, or from a fresh download that verifies.

    A download is written beside the cache under a temporary name and takes the
    archive's name only once it verifies, so a mismatching download leaves nothing
    behind and extracts nothing.
    """
    found = cached(archive, version, platform_name, cache_dir)
    if found is not None:
        return found
    cache_dir.mkdir(parents=True, exist_ok=True)
    partial = cache_dir / f"{archive.filename}.part"
    try:
        try:
            download(archive.url, partial)
        except (OSError, http.client.HTTPException) as error:
            raise FetchError(f"cannot download {archive.url}: {error!r}") from error
        verify(partial, archive.sha256)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    path = partial.replace(cache_dir / archive.filename)
    return extract(path, archive.sha256, _binaries_dir(cache_dir, version, platform_name))


def _binaries_dir(cache_dir: Path, version: str, platform_name: str) -> Path:
    return cache_dir / f"frp_{version}_{platform_name}"


def resolve(
    *,
    fetching: bool,
    environ: Mapping[str, str] = os.environ,
    pins_path: Path = PINS_PATH,
    cache_dir: Path = CACHE_DIR,
    platform_name: str | None = None,
) -> Binaries:
    """The binaries to test: the overrides, else, when `fetching`, the pinned archive's.

    The default suite does not fetch, so it never touches the network and, without
    the overrides, has no binaries even where the gate has cached them: the real-frp
    tests belong to the gate. `NoBinaries` says why there are none.
    """
    frps, frpc = environ.get("FRPS_BIN"), environ.get("FRPC_BIN")
    if frps or frpc:
        if not (frps and frpc):
            raise FetchError("FRPS_BIN and FRPC_BIN must be set together")
        return Binaries(
            Path(frps), Path(frpc), "FRPS_BIN and FRPC_BIN, not verified against frp-pins.toml"
        )
    if not fetching:
        raise NoBinaries("the real-frp tests run under `make test-frp`, or with FRPS_BIN and FRPC_BIN")
    pins = load_pins(pins_path)
    platform_name = platform_name or running_platform()
    archive = pins.archives.get(platform_name)
    if archive is None:
        raise NoBinaries(
            f"frp-pins.toml pins no archive for {platform_name}; set FRPS_BIN and FRPC_BIN"
        )
    return fetch(archive, pins.version, platform_name, cache_dir)
