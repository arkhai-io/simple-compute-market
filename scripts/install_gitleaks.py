#!/usr/bin/env python3
"""Install the gitleaks release the repository pins, verified before it is used.

The public-content checks run gitleaks at one pinned release, named with each
platform's archive and its sha256 in `scripts/gitleaks-pins.toml`. This script
downloads the archive for the running platform, refuses it unless its sha256 is
the pinned one, and installs its `gitleaks` binary into a directory, `~/.local/bin`
unless `--dir` names another; it needs no root, and CI runs it the same way. When
the pinned release is already the `gitleaks` on PATH, it does nothing; and it
fails, naming the cause, when what it installed is not the `gitleaks` PATH finds,
since a check would then still run another one.

`problem()` is how a check that runs gitleaks finds it missing or at another
release; its message names `make install-gitleaks`, so nobody is left guessing.

Usage: `make install-gitleaks [GITLEAKS_INSTALL_DIR=<dir>]`.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import io
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

PINS_PATH = Path(__file__).resolve().with_name("gitleaks-pins.toml")
DEFAULT_DIR = Path.home() / ".local" / "bin"
INSTALL_COMMAND = "make install-gitleaks"
DOWNLOAD_TIMEOUT_SECONDS = 120
_SYSTEMS = {"Linux": "linux", "Darwin": "darwin"}
_MACHINES = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}
_VERSION = re.compile(r"(\d+\.\d+\.\d+)")

# Downloads a URL and returns its bytes.
Fetch = Callable[[str], bytes]
# Runs `gitleaks version` and returns what it prints, or None when there is none.
VersionRun = Callable[[], str | None]


class InstallError(Exception):
    """The pinned gitleaks could not be installed."""


@dataclass(frozen=True)
class Pins:
    version: str
    archives: dict[str, tuple[str, str]]


def read_pins(path: Path = PINS_PATH) -> Pins:
    """The pinned release and each platform's archive URL and sha256."""
    data = tomllib.loads(path.read_text("utf-8"))
    archives = {name: (entry["url"], entry["sha256"])
                for name, entry in data.get("archives", {}).items()}
    return Pins(data["version"], archives)


def platform_name(system: str | None = None, machine: str | None = None) -> str:
    """The running platform as gitleaks names its archives, such as `linux_x64`."""
    system, machine = system or platform.system(), (machine or platform.machine()).lower()
    return f"{_SYSTEMS.get(system, system.lower())}_{_MACHINES.get(machine, machine)}"


def _gitleaks_version() -> str | None:
    try:
        done = subprocess.run(["gitleaks", "version"], capture_output=True, text=True)
    except OSError:
        return None
    return done.stdout if done.returncode == 0 else None


def installed_version(run: VersionRun = _gitleaks_version) -> str | None:
    """The release of the `gitleaks` on PATH, or None when there is none."""
    printed = run()
    match = _VERSION.search(printed or "")
    return match.group(1) if match else None


def problem(run: VersionRun = _gitleaks_version, pins: Pins | None = None) -> str | None:
    """Why the pinned gitleaks cannot be run, naming how to install it, or None."""
    pinned = (pins or read_pins()).version
    found = installed_version(run)
    if found == pinned:
        return None
    where = "no gitleaks is on PATH" if found is None else f"gitleaks {found} is on PATH"
    return (f"gitleaks {pinned} is required and {where}; run `{INSTALL_COMMAND}` to install "
            f"the pinned release (scripts/gitleaks-pins.toml)")


def _download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
        return response.read()


def install(directory: Path, *, pins: Pins | None = None, fetch: Fetch = _download,
            platform_: str | None = None) -> Path:
    """Download, verify and install the pinned binary; the installed path."""
    pins = pins or read_pins()
    name = platform_ or platform_name()
    if name not in pins.archives:
        raise InstallError(
            f"scripts/gitleaks-pins.toml pins no gitleaks archive for {name}; it pins "
            f"{', '.join(sorted(pins.archives))}")
    url, sha256 = pins.archives[name]
    archive = fetch(url)
    digest = hashlib.sha256(archive).hexdigest()
    if digest != sha256:
        raise InstallError(f"{url} has sha256 {digest}, not the pinned {sha256}; "
                           "nothing was installed")
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        member = next((m for m in tar.getmembers() if m.name == "gitleaks" and m.isfile()),
                      None)
        binary = tar.extractfile(member) if member is not None else None
        if binary is None:
            raise InstallError(f"{url} holds no gitleaks file")
        content = binary.read()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "gitleaks"
    # Written beside the target and renamed over it, so an interrupted install
    # never leaves a partial binary where a check would run it.
    with tempfile.NamedTemporaryFile(dir=directory, delete=False) as partial:
        partial.write(content)
    os.chmod(partial.name, 0o755)
    os.replace(partial.name, target)
    return target


def main(argv: list[str] | None = None, *, run: VersionRun = _gitleaks_version,
         fetch: Fetch = _download,
         which: Callable[[str], str | None] = shutil.which) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR,
                        help="where to install the binary (default: %(default)s)")
    args = parser.parse_args(argv)
    pins = read_pins()
    if problem(run, pins) is None:
        print(f"OK: gitleaks {pins.version} is already installed.")
        return 0
    try:
        target = install(args.dir.expanduser(), pins=pins, fetch=fetch)
    except (InstallError, OSError, http.client.HTTPException, tarfile.TarError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Installed gitleaks {pins.version} at {target}.")
    if (shadow := which("gitleaks")) is None or Path(shadow).resolve() != target.resolve():
        found = "no gitleaks" if shadow is None else f"`gitleaks` resolves to {shadow}"
        print(f"ERROR: on PATH, {found}; put {target.parent} first on PATH, or rerun with "
              "GITLEAKS_INSTALL_DIR=<a directory earlier on PATH>.", file=sys.stderr)
        return 1
    print(f"OK: gitleaks {pins.version} is the gitleaks on PATH.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
