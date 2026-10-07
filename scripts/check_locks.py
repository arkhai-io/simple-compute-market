"""Fail if a committed lock is not current, without contacting any index.

Run after `make dist`: it reads the committed tree and the built wheelhouse.
Each lock is checked on three axes.

1. Against its project: `uv lock --check --offline`.
2. Against the wheels. For each package the lock resolves from the wheelhouse,
   the locked version is the one the tree builds, and that wheel's metadata
   agrees with the lock's record of it: the names of its unconditional
   requirements equal the lock's recorded dependencies, and the names under
   each extra in use equal that extra's recorded dependencies. uv records no
   section for an empty extra, and no extra on the consumer's dependency edge
   either, so the extras in use are derived from everything that can request
   one: extras on the lock's dependency edges, each locked project's
   `requires-dist`, and the `Requires-Dist` lines of the wheels the lock
   installs. Each locked dependency version must satisfy the wheel's specifier
   for it, using the version uv records on the dependency edge when the
   resolution forks. A rebuilt wheel keeps its version, so this is the only way
   to notice that a consumer was locked before the wheel's requirements
   changed.
3. Against the repository. A distribution some project declares must resolve
   from the wheelhouse, never from an index or another local registry.

What the check cannot evaluate — a specifier or version it does not parse, or
a dependency locked at several versions with none recorded on the edge — is
reported as a problem, never passed.

Environment markers are compared only to decide which extra a requirement
belongs to. uv simplifies markers against `requires-python` when it locks, so
a requirement that carries an environment marker may be absent from the lock
without the lock being stale; such requirements are checked in the "removed"
direction only. A same-version wheel that changes only a marker is not seen
here; `make lock` followed by an unchanged tree covers it.

Conventions: docs/development/BUILD_AND_PACKAGING.md.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
import zipfile
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_SPEC = importlib.util.spec_from_file_location(
    "uv_project", Path(__file__).resolve().parent / "uv_project.py"
)
assert _SPEC and _SPEC.loader
uv_project = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(uv_project)

SKIPPED_DIRS = {".venv", "node_modules", "openspec", ".git"}
LockCheck = Callable[[Path, str], str | None]

_REQUIREMENT = re.compile(
    r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[([^\]]*)\])?\s*\(?([^;)]*)\)?\s*(?:;\s*(.*))?$"
)
_EXTRA = re.compile(r"""extra\s*==\s*["']([^"']+)["']""")
_CLAUSE = re.compile(r"^\s*(===|~=|==|!=|<=|>=|<|>)\s*(\S+)\s*$")


def _uv_lock_check(project: Path, wheelhouse: str) -> str | None:
    result = subprocess.run(
        ["uv", "lock", "--check", "--offline", "--find-links", wheelhouse],
        cwd=project, capture_output=True, text=True,
    )
    if result.returncode == 0:
        return None
    lines = [l for l in (result.stderr or result.stdout).splitlines() if l.strip()]
    return lines[-1].strip() if lines else f"exit status {result.returncode}"


Requirement = tuple[str, str, str | None, bool, frozenset[str]]


def wheel_requirements(wheel: Path) -> list[Requirement]:
    """(name, specifier, extra, has other markers, extras requested) per Requires-Dist."""
    with zipfile.ZipFile(wheel) as archive:
        metadata = next(n for n in archive.namelist() if n.endswith(".dist-info/METADATA"))
        text = archive.read(metadata).decode("utf-8")
    requirements = []
    for line in text.splitlines():
        if not line.startswith("Requires-Dist:"):
            continue
        match = _REQUIREMENT.match(line.split(":", 1)[1])
        if not match:
            continue
        name, requested = match.group(1), match.group(2) or ""
        specifier, marker = match.group(3).strip(), match.group(4) or ""
        extra = _EXTRA.search(marker)
        remainder = _EXTRA.sub("", marker)
        remainder = re.sub(r"\b(and|or)\b|[()\s]", "", remainder)
        requirements.append((uv_project.normalise(name), specifier,
                             extra.group(1) if extra else None, bool(remainder),
                             frozenset(e.strip() for e in requested.split(",") if e.strip())))
    return requirements


def _release(version: str) -> tuple[int, ...] | None:
    match = re.fullmatch(r"v?(\d+(?:\.\d+)*)(?:\+[A-Za-z0-9.]+)?", version.strip())
    return tuple(int(part) for part in match.group(1).split(".")) if match else None


def _padded(a: tuple[int, ...], b: tuple[int, ...]) -> tuple[tuple[int, ...], tuple[int, ...]]:
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)), b + (0,) * (width - len(b))


def satisfies(version: str, specifier: str) -> bool | None:
    """Whether ``version`` meets ``specifier``; None when either cannot be read."""
    have = _release(version)
    if have is None:
        return None
    for clause in filter(None, (c.strip() for c in specifier.split(","))):
        match = _CLAUSE.match(clause)
        if not match or match.group(1) == "===":
            return None
        operator, wanted = match.groups()
        if wanted.endswith(".*") and operator in ("==", "!="):
            prefix = _release(wanted[:-2])
            if prefix is None:
                return None
            matches = have[: len(prefix)] == prefix
            if matches != (operator == "=="):
                return False
            continue
        target = _release(wanted)
        if target is None:
            return None
        a, b = _padded(have, target)
        if operator == "~=":
            ok = a >= b and have[: len(target) - 1] == target[: len(target) - 1]
        else:
            ok = {"==": a == b, "!=": a != b, "<=": a <= b, ">=": a >= b,
                  "<": a < b, ">": a > b}[operator]
        if not ok:
            return False
    return True


def _wheel(wheelhouse: Path, name: str, version: str) -> Path | None:
    stem = re.sub(r"[-_.]+", "_", name)
    matches = sorted(wheelhouse.glob(f"{stem}-{version}-*.whl"))
    return matches[0] if matches else None


def _recorded(entries: list[dict]) -> set[str]:
    return {uv_project.normalise(entry["name"]) for entry in entries}


def _extras_in_use(packages: list[dict], wheels: dict[str, list[Requirement]]) -> dict[str, set[str]]:
    """Extras requested of each package anywhere the lock or its wheels can request one."""
    in_use: dict[str, set[str]] = {}

    def request(name: str, extras) -> bool:
        wanted = set(extras) - in_use.setdefault(uv_project.normalise(name), set())
        in_use[uv_project.normalise(name)] |= wanted
        return bool(wanted)

    for package in packages:
        sections = [package.get("dependencies", [])]
        sections += list((package.get("optional-dependencies") or {}).values())
        sections += list((package.get("dev-dependencies") or {}).values())
        for entries in sections:
            for entry in entries:
                request(entry["name"], entry.get("extra", []))
        metadata = package.get("metadata") or {}
        declared = list(metadata.get("requires-dist", []))
        for group in (metadata.get("requires-dev") or {}).values():
            declared += group
        for entry in declared:
            request(entry["name"], entry.get("extras", []))
    changed = True
    while changed:
        changed = False
        for name, requirements in wheels.items():
            active = in_use.get(name, set())
            for dependency, _, extra, _, requested in requirements:
                if requested and (extra is None or extra in active):
                    changed |= request(dependency, requested)
    return in_use


def lock_problems(project: Path, root: Path, versions: dict[str, str],
                  lock_check: LockCheck = _uv_lock_check) -> list[str]:
    where = project.relative_to(root)
    wheelhouse = (root / uv_project.WHEELHOUSE_NAME).resolve()
    problems = []
    failure = lock_check(project, uv_project.relative_wheelhouse(project, wheelhouse))
    if failure:
        problems.append(f"{where}: lock does not match the project ({failure}); run `make lock`")
    packages = uv_project._read_toml(project / "uv.lock").get("package", [])
    locked: dict[str, set[str]] = {}
    for package in packages:
        locked.setdefault(uv_project.normalise(package["name"]), set()).add(package["version"])
    internal = []
    for package in packages:
        name = uv_project.normalise(package["name"])
        registry = (package.get("source") or {}).get("registry")
        if not isinstance(registry, str):
            continue
        if "://" in registry:
            if name in versions:
                problems.append(f"{where}: resolves repository distribution {name} from {registry}")
            continue
        if (project / registry).resolve() != wheelhouse:
            problems.append(f"{where}: resolves {name} from {registry}, not the repository wheelhouse")
            continue
        version = package["version"]
        if name in versions and versions[name] != version:
            problems.append(f"{where}: pins {name}=={version}; the tree builds {versions[name]}")
            continue
        wheel = _wheel(wheelhouse, name, version)
        if wheel is None:
            problems.append(f"{where}: the wheelhouse holds no {name}=={version}; run `make dist`")
            continue
        internal.append((name, package, wheel_requirements(wheel)))
    in_use = _extras_in_use(packages, {name: requirements for name, _, requirements in internal})
    for name, package, requirements in internal:
        problems += _metadata_problems(where, name, package, requirements,
                                       in_use.get(name, set()), locked)
    return problems


def _metadata_problems(where, name, package, requirements, in_use, locked) -> list[str]:
    recorded_sections = {None: package.get("dependencies", [])}
    optional = package.get("optional-dependencies") or {}
    for extra in set(optional) | in_use:
        recorded_sections[extra] = optional.get(extra, [])
    problems = []
    for extra, entries in recorded_sections.items():
        label = f"{name}[{extra}]" if extra else name
        recorded = _recorded(entries)
        edges = {uv_project.normalise(e["name"]): e for e in entries}
        wanted = [r for r in requirements if r[2] == extra]
        every = {r[0] for r in wanted}
        unmarked = {r[0] for r in wanted if not r[3]}
        for added in sorted(unmarked - recorded):
            problems.append(f"{where}: {label}'s wheel requires {added}, which the lock does not record; run `make lock`")
        for removed in sorted(recorded - every):
            problems.append(f"{where}: the lock records {removed} for {label}, which its wheel no longer requires; run `make lock`")
        for dependency, specifier, _, _, _ in wanted:
            if dependency not in recorded or not specifier:
                continue
            pinned = locked.get(dependency, set())
            version = edges[dependency].get("version") or (next(iter(pinned)) if len(pinned) == 1 else None)
            verdict = satisfies(version, specifier) if version else None
            if verdict is False:
                problems.append(f"{where}: {label} requires {dependency}{specifier}, but the lock pins {version}; run `make lock`")
            elif verdict is None:
                problems.append(f"{where}: cannot verify that the lock's {dependency} "
                                f"({', '.join(sorted(pinned)) or 'unlocked'}) meets {label}'s requirement {specifier}")
    return problems


def problems(root: Path = ROOT, lock_check: LockCheck = _uv_lock_check) -> list[str]:
    versions = uv_project.repository_versions(root)
    found = []
    for project in uv_project.locked_projects(root):
        try:
            found += lock_problems(project, root, versions, lock_check)
        except uv_project.DerivationError as exc:
            found.append(str(exc))
    return found


def main() -> int:
    found = problems()
    for problem in found:
        print(problem)
    if found:
        print(f"\n{len(found)} lock problem(s). See docs/development/BUILD_AND_PACKAGING.md.")
        return 1
    print("OK: every lock matches its project, the wheels this tree builds, and the wheelhouse.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
