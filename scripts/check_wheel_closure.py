#!/usr/bin/env python3
"""Verify each internal wheel is importable from its own declared dependencies.

Installing every internal wheel into one environment proves the assembled set is
consistent. It cannot prove any individual wheel is self-describing: a package
whose metadata omits a dependency still imports, because a sibling installed it.

This installs one wheel at a time into a fresh virtual environment, resolving
only what that wheel's own metadata asks for, and imports every module it ships.
An omitted dependency surfaces as ``ModuleNotFoundError`` naming what is missing.

Internal dependencies resolve from ``--find-links`` against the local wheelhouse;
third-party ones come from the index. Run ``make dist`` first.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import re
import tomllib
import zipfile
from pathlib import Path

#: Wheels whose closure is checked. Each is depended on by another package, where
#: an undeclared import is invisible in an aggregate install.
DEFAULT_PROJECTS = (
    "domains/vms/domain",
    "domains/vms/buyer",
    "kit/policy",
    "core",
)

#: Modules a wheel ships that are not importable from its base closure by design.
#: Each needs a stated reason; an unexplained entry is a masked defect.
EXPECTED_ISOLATION_FAILURES: dict[str, dict[str, str]] = {
    "arkhai-vms": {
        "arkhai_vms.storefront_adapter": (
            "satisfies a core-storefront interface and is declared under the "
            "[storefront] extra, so it is absent from the base closure"
        ),
    },
}


def _distribution_name(project: Path) -> str | None:
    pyproject = project / "pyproject.toml"
    if not pyproject.is_file():
        return None
    with pyproject.open("rb") as handle:
        return tomllib.load(handle).get("project", {}).get("name")


def _wheel_for(project: Path, dist_dir: Path) -> Path | None:
    name = _distribution_name(project)
    if name is None:
        return None
    matches = sorted(dist_dir.glob(f"{name.replace('-', '_')}-*.whl"))
    return matches[-1] if matches else None


def _shipped_modules(wheel: Path) -> list[str]:
    """Every importable module in the wheel, excluding test paths."""
    modules: set[str] = set()
    with zipfile.ZipFile(wheel) as archive:
        for entry in archive.namelist():
            if not entry.endswith(".py") or ".dist-info/" in entry:
                continue
            parts = Path(entry).with_suffix("").parts
            if any(p in {"tests", "test"} for p in parts):
                continue
            if parts[-1] == "__init__":
                parts = parts[:-1]
            if parts:
                modules.add(".".join(parts))
    return sorted(modules)


def _requires(wheel: Path) -> list[str]:
    """Distribution names this wheel declares, base requirements only."""
    names = []
    with zipfile.ZipFile(wheel) as archive:
        meta = next(
            (n for n in archive.namelist() if n.endswith(".dist-info/METADATA")), None
        )
        if meta is None:
            return names
        for line in archive.read(meta).decode().splitlines():
            if not line.startswith("Requires-Dist:"):
                continue
            spec = line.split(":", 1)[1].strip()
            if "; extra ==" in spec:
                continue
            names.append(re.split(r"[\s<>=!~;\[]", spec, 1)[0])
    return names


def _internal_closure(wheel: Path, dist_dir: Path) -> list[Path]:
    """Every wheelhouse wheel reachable from ``wheel``'s declared requirements.

    Resolved to local file paths and passed explicitly, because several internal
    distributions are also published publicly at the same version numbers. Given
    only ``--find-links`` plus an index, pip resolves those from the index and
    installs pre-change contents — which would make this check report a defect
    that is really a stale artifact, or hide one behind a fresher published copy.
    """
    by_name = {
        path.name.split("-")[0].replace("_", "-").lower(): path
        for path in dist_dir.glob("*.whl")
    }
    seen: set[Path] = set()
    queue = [wheel]
    while queue:
        current = queue.pop()
        for name in _requires(current):
            local = by_name.get(name.lower())
            if local is None or local in seen or local == wheel:
                continue
            seen.add(local)
            queue.append(local)
    return sorted(seen)


def check(project: Path, dist_dir: Path) -> list[str]:
    name = _distribution_name(project)
    wheel = _wheel_for(project, dist_dir)
    if wheel is None:
        return [f"{project.name}: no built wheel in {dist_dir}; run make dist first"]

    modules = _shipped_modules(wheel)
    expected = EXPECTED_ISOLATION_FAILURES.get(name or "", {})

    with tempfile.TemporaryDirectory() as tmp:
        venv = Path(tmp) / "venv"
        subprocess.run(
            [sys.executable, "-m", "venv", str(venv)], check=True, capture_output=True
        )
        python = venv / "bin" / "python"
        install = subprocess.run(
            [
                str(python), "-m", "pip", "install", "--quiet",
                "--disable-pip-version-check",
                "--no-cache-dir",
                "--find-links", str(dist_dir),
                *[str(p) for p in _internal_closure(wheel, dist_dir)],
                str(wheel),
            ],
            capture_output=True, text=True,
        )
        if install.returncode != 0:
            tail = (install.stderr or install.stdout).strip().splitlines()[-2:]
            return [f"{name}: install from own metadata failed: " + " / ".join(tail)]

        probe = (
            "import importlib, json\n"
            f"mods = {json.dumps(modules)}\n"
            "bad = {}\n"
            "for m in mods:\n"
            "    try: importlib.import_module(m)\n"
            "    except Exception as exc: bad[m] = f'{type(exc).__name__}: {exc}'\n"
            "print(json.dumps(bad))\n"
        )
        result = subprocess.run(
            [str(python), "-c", probe], capture_output=True, text=True, cwd=tmp
        )
        if result.returncode != 0:
            return [f"{name}: probe failed: {result.stderr.strip()[-200:]}"]
        failures: dict[str, str] = json.loads(result.stdout.strip().splitlines()[-1])

    findings = []
    for module, error in sorted(failures.items()):
        if module in expected:
            continue
        findings.append(
            f"{name}: {module} does not import from this wheel's own declared "
            f"dependencies ({error}) -- the distribution supplying it is missing "
            "from [project.dependencies]"
        )
    for module, reason in expected.items():
        if module not in failures:
            findings.append(
                f"{name}: {module} was expected to fail in isolation ({reason}) "
                "but imported; remove the exemption"
            )
    return findings


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", default=str(root / ".dist"))
    parser.add_argument("projects", nargs="*")
    args = parser.parse_args()

    dist_dir = Path(args.dist_dir).resolve()
    findings: list[str] = []
    for rel in args.projects or DEFAULT_PROJECTS:
        print(f"  checking {rel} ...")
        findings.extend(check((root / rel).resolve(), dist_dir))

    if findings:
        print("\nWheels that do not stand on their own dependency metadata:\n")
        for finding in findings:
            print(f"  {finding}")
        return 1
    print("\nOK: every checked wheel imports from its own declared dependencies.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
