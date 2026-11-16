#!/usr/bin/env python3
"""Refuse a component version that an earlier marketplace release recorded with
other contents.

A published version is permanent, so a version whose contents changed must be a
new version. Every marketplace release records its components' content
identities in the bill of materials its tag carries
(`manifests/release-bom.cdx.json`, read by `scripts/release_bom.py`). This check
reads the record at every `marketplace-v*` tag that carries one, except the tag
being checked, and refuses a wheel whose distribution and version a record names
with another SHA-256, or a chart whose version a record names with another
content digest, naming the component and the release that recorded it. A refusal
means "bump the version"; the check never chooses one.

Every earlier record is read, not only the newest, so that a version lowered back
to one released two releases ago is refused too, and so that no rule about
version order is needed.

Its subject is either of two:

- with no tag, the declared wheels in the wheelhouse (`.dist`, built by
  `make dist`) and the chart packaged with the pinned Helm, as a load checks the
  candidate it has just built;
- given `--tag`, that tag's own committed bill of materials, with no build, as
  the cut checks the record about to be pushed.

It reads git and nothing else: no package registry. It therefore guards the
versions recorded releases name, and not a version a registry received by other
means.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from release_bom import PATH, Bom, BomError, ChartPackage, package_chart, parse
from release_components import (
    DECLARATION_PATH,
    REPO_ROOT,
    DeclarationError,
    declared_wheels,
    load,
    normalise_distribution,
    project_version,
)

TAG_PREFIX = "marketplace-v"


@dataclass(frozen=True)
class Identity:
    """One component of the subject: its bom-ref, version and content identity."""

    bom_ref: str
    version: str
    identity: str


@dataclass(frozen=True)
class Record:
    tag: str
    bom: Bom


def git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    """Run git in the repository at `root`, returning the completed process."""
    return subprocess.run(["git", *args], cwd=root, capture_output=True)


def _git_out(root: Path, *args: str) -> bytes:
    result = git(root, *args)
    if result.returncode != 0:
        raise BomError(f"git {' '.join(args)} failed: "
                       f"{result.stderr.decode('utf-8', 'replace').strip()}")
    return result.stdout


def tag_name(tag: str) -> str:
    return tag.removeprefix("refs/tags/")


def committed_bom(root: Path, revision: str) -> bytes | None:
    """The bill of materials committed at `revision`, or None where it has none."""
    if git(root, "cat-file", "-e", f"{revision}:{PATH}").returncode != 0:
        return None
    return _git_out(root, "show", f"{revision}:{PATH}")


def recorded_releases(root: Path, exclude: str | None = None) -> list[Record]:
    """The record of every marketplace release tag carrying one, but `exclude`.

    A record in a layout this reader does not know is refused, not skipped: a
    record skipped would leave its versions unguarded.
    """
    # `lstrip=2` drops exactly `refs/tags/`, where `short` would keep `tags/`
    # for a tag a branch of the same name shadows, and the record be missed.
    listing = _git_out(root, "for-each-ref", "--format=%(refname:lstrip=2)",
                       f"refs/tags/{TAG_PREFIX}*").decode("utf-8")
    excluded = tag_name(exclude) if exclude else None
    records = []
    for tag in listing.split():
        if tag == excluded:
            continue
        data = committed_bom(root, f"refs/tags/{tag}")
        if data is not None:
            records.append(Record(tag=tag, bom=parse(data, f"{tag}:{PATH}")))
    return records


def subject_of(bom: Bom) -> list[Identity]:
    """The versioned components of a bill of materials: its wheels and its chart."""
    return [Identity(component.bom_ref, component.version, component.identity)
            for component in bom.components
            if component.kind in ("wheel", "chart") and component.version is not None]


def built_subject(root: Path, dist_dir: Path,
                  chart: Callable[[Path], ChartPackage] | None = None) -> list[Identity]:
    """The declared wheels in `dist_dir` and the chart packaged with the pinned Helm
    (`release_bom.package_chart` with `root`'s pin, unless `chart` replaces it)."""
    if chart is None:
        def chart(chart_dir: Path) -> ChartPackage:
            return package_chart(chart_dir, root)
    components = load(root / DECLARATION_PATH)
    wheels = declared_wheels(components, root, dist_dir)
    missing = [wheel.name for wheel in wheels if not wheel.is_file()]
    if missing:
        raise BomError(f"{dist_dir} holds no wheel for {len(missing)} declared "
                       "distribution(s); build the wheelhouse with `make dist`: "
                       + ", ".join(missing))
    subject = []
    for entry, wheel in zip(components.distributions, wheels):
        subject.append(Identity(f"wheel/{entry.dist}", project_version(root, entry),
                                hashlib.sha256(wheel.read_bytes()).hexdigest()))
    package = chart(root / components.chart.path)
    subject.append(Identity(f"chart/{package.name}", package.version, package.content_digest))
    return subject


def _key(component: Identity) -> tuple[str, str]:
    """What a published version is keyed by. A wheel's distribution is compared as
    PyPI compares project names, so a respelling of it is still the same project."""
    kind, _, name = component.bom_ref.partition("/")
    if kind == "wheel":
        name = normalise_distribution(name)
    return f"{kind}/{name}", component.version


def violations(subject: list[Identity], records: list[Record]) -> list[str]:
    """Each subject component whose version a record names with other contents."""
    recorded: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for record in records:
        for component in subject_of(record.bom):
            recorded.setdefault(_key(component), []).append((component.identity, record.tag))
    problems = []
    for component in subject:
        for identity, tag in recorded.get(_key(component), []):
            if identity != component.identity:
                kind = "SHA-256" if component.bom_ref.startswith("wheel/") else "content digest"
                problems.append(f"{component.bom_ref} {component.version}: its {kind} is "
                                f"{component.identity}, but {tag} recorded that version as "
                                f"{identity}; bump its version")
    return problems


def check(root: Path = REPO_ROOT, tag: str | None = None, dist_dir: Path | None = None,
          chart: Callable[[Path], ChartPackage] | None = None) -> tuple[list[str], str]:
    """The refusals for the subject `tag` names, or the built one, and a summary."""
    if tag:
        data = committed_bom(root, f"refs/tags/{tag_name(tag)}")
        if data is None:
            raise BomError(f"{tag_name(tag)} carries no {PATH}")
        subject = subject_of(parse(data, f"{tag_name(tag)}:{PATH}"))
        described = f"{tag_name(tag)}'s record"
    else:
        subject = built_subject(root, dist_dir or root / ".dist", chart)
        described = "the wheelhouse and the packaged chart"
    records = recorded_releases(root, exclude=tag)
    if not records:
        return [], (f"no earlier marketplace release carries a bill of materials, so there "
                    f"is nothing to compare {described} with")
    tags = ", ".join(record.tag for record in records)
    return violations(subject, records), (
        f"{len(subject)} versioned components of {described} match every earlier "
        f"record ({tags})")


def main(argv: list[str] | None = None, root: Path = REPO_ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tag", help="check this marketplace-v<semver> tag's own record, "
                                      "with no build")
    arguments = parser.parse_args(argv)
    try:
        problems, summary = check(root, tag=arguments.tag)
    except (BomError, DeclarationError) as error:
        print(f"check-release-versions: {error}", file=sys.stderr)
        return 1
    if problems:
        print("check-release-versions:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print(f"OK: {summary}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
