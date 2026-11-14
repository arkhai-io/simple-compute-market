#!/usr/bin/env python3
"""Refuse a marketplace release record of any shape but the one the cut makes.

A marketplace release is recorded last, once production runs it:
`releases/<semver>` is cut at the default-branch commit the release was built
from, one commit on it adds the bill of materials the deployment built
(`manifests/release-bom.cdx.json`), and that commit is tagged
`marketplace-v<semver>`. The operator runs this check on the tag before pushing
it, because a pushed tag is public and permanent. It refuses unless:

1. the tag's commit is the tip of `releases/<semver>`, locally and as every
   remote-tracking branch of that name (as of the last fetch), and its one
   parent is reachable from the default branch;
2. the commit changes exactly one path, adding the bill of materials;
3. the bill of materials is layout 1, with only layout 1's fields and no URL but
   the public vcs link (`scripts/release_bom.py`);
4. its source revision is the parent commit, and its version is the tag's semver;
5. its components, by bom-ref, are each named once and are exactly the release
   components the declaration at the parent commit declares, no development
   image among them;
6. `scripts/check_release_versions.py` passes with the record as its subject.

It reads git alone: the cut runs in a fresh worktree, and the bytes about to be
published are the ones the record names, so it needs no wheelhouse and no Helm.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

from check_release_versions import (
    committed_bom,
    git,
    recorded_releases,
    subject_of,
    violations,
)
from release_bom import PATH, SEMVER, BomError, parse
from release_components import DECLARATION_PATH as DECLARATION
from release_components import REPO_ROOT, DeclarationError, chart_field
from release_components import parse as parse_declaration

DEFAULT_BRANCH = "main"
_TAG = re.compile(rf"^marketplace-v(?P<semver>{SEMVER})$")


def _out(root: Path, *args: str) -> str | None:
    result = git(root, *args)
    return result.stdout.decode("utf-8", "replace") if result.returncode == 0 else None


def _branch_refs(root: Path, branch: str) -> list[str]:
    """The local branch named `branch` and every remote's branch of that name."""
    listing = _out(root, "for-each-ref", "--format=%(refname)", "refs/heads", "refs/remotes")
    return [ref for ref in (listing or "").split()
            if ref == f"refs/heads/{branch}"
            or re.fullmatch(rf"refs/remotes/[^/]+/{re.escape(branch)}", ref)]


def _reachable(root: Path, commit: str, refs: list[str]) -> bool:
    return any(git(root, "merge-base", "--is-ancestor", commit, ref).returncode == 0
               for ref in refs)


def _tip(root: Path, ref: str) -> str:
    return (_out(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}") or "").strip()


def _changes(root: Path, parent: str, commit: str) -> list[tuple[str, str]]:
    listing = _out(root, "diff-tree", "-r", "-z", "--no-renames", "--no-commit-id",
                   "--name-status", parent, commit) or ""
    fields = listing.split("\0")
    return [(fields[index], fields[index + 1]) for index in range(0, len(fields) - 1, 2)]


def _show(root: Path, revision: str, path: str) -> str | None:
    return _out(root, "show", f"{revision}:{path}")


def _declared_refs(root: Path, parent: str, problems: list[str]) -> tuple[set[str], set[str]]:
    """The bom-refs of the release components, and of the development images,
    that the declaration at `parent` declares."""
    text = _show(root, parent, DECLARATION)
    if text is None:
        problems.append(f"the parent commit has no {DECLARATION}")
        return set(), set()
    try:
        components = parse_declaration(json.loads(text), f"{parent[:9]}:{DECLARATION}")
    except (json.JSONDecodeError, DeclarationError) as error:
        problems.append(f"the declaration at the parent commit cannot be read: {error}")
        return set(), set()
    refs = {f"wheel/{entry.dist}" for entry in components.distributions}
    refs |= {f"image/{entry.name}" for entry in components.images}
    refs |= {f"binary/{entry.name}" for entry in components.binaries}
    chart_yaml = _show(root, parent, f"{components.chart.path}/Chart.yaml") or ""
    chart_name = chart_field(chart_yaml, "name")
    if chart_name is None:
        problems.append(f"the parent commit's {components.chart.path}/Chart.yaml names no chart")
    else:
        refs.add(f"chart/{chart_name}")
    for entry in components.npm or ():
        try:
            package = json.loads(_show(root, parent, f"{entry.path}/package.json") or "{}")
        except json.JSONDecodeError:
            package = {}
        name = package.get("name") if isinstance(package, dict) else None
        if not isinstance(name, str) or not name:
            problems.append(f"the parent commit's {entry.path}/package.json cannot be read "
                            "or names no package")
        else:
            refs.add(f"npm/{name.removeprefix('@arkhai/')}")
    return refs, {f"image/{entry.name}" for entry in components.development_images}


def check(tag: str, root: Path = REPO_ROOT, default_branch: str = DEFAULT_BRANCH) -> list[str]:
    """Every refusal for the release record `tag` names."""
    tag = tag.removeprefix("refs/tags/")
    match = _TAG.match(tag)
    if not match:
        return [f"{tag} is not a marketplace-v<semver> tag"]
    semver = match.group("semver")
    commit = (_out(root, "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}^{{commit}}")
              or "").strip()
    if not commit:
        return [f"no tag {tag} exists"]
    parents = (_out(root, "rev-list", "--parents", "-n", "1", commit) or "").split()[1:]
    if len(parents) != 1:
        return [f"{tag}'s commit has {len(parents)} parents; a release commit has exactly one"]
    parent = parents[0]
    problems: list[str] = []

    # 1. The commit is the tip of its release branch, cut from the default branch.
    # Every ref of the branch's name is held to it, a remote-tracking one too: a
    # release branch never grows past its record, so a ref anywhere else is a branch
    # of another shape.
    branch = f"releases/{semver}"
    branches = _branch_refs(root, branch)
    if not branches:
        problems.append(f"no branch {branch} exists")
    for ref in branches:
        tip = _tip(root, ref)
        if tip != commit:
            problems.append(f"{ref.removeprefix('refs/heads/').removeprefix('refs/')} is at "
                            f"{tip[:9]}, not {tag}'s commit {commit[:9]}; a release branch "
                            "holds only its record")
    defaults = _branch_refs(root, default_branch)
    if not defaults:
        problems.append(f"no {default_branch} branch exists to reach the parent from")
    elif not _reachable(root, parent, defaults):
        problems.append(f"the release branch's point {parent[:9]} is not reachable from "
                        f"{default_branch}")

    # 2. The commit adds the bill of materials and changes nothing else.
    changes = _changes(root, parent, commit)
    for status, path in changes:
        if (status, path) != ("A", PATH):
            problems.append(f"the release commit changes {path} ({status}); it may only add {PATH}")
    if ("A", PATH) not in changes:
        problems.append(f"the release commit does not add {PATH}")
        return problems

    # 3. The bill of materials is layout 1, holding content identities only. It is
    # read as committed bytes, which are what its digest is taken of.
    try:
        bom = parse(committed_bom(root, commit) or b"", f"{tag}:{PATH}")
    except BomError as error:
        problems.append(str(error))
        return problems

    # 4. It names the branch point and the tag's version.
    if bom.source_revision != parent:
        problems.append(f"its arkhai:source-revision is {bom.source_revision}, not the "
                        f"branch point {parent}")
    if bom.version != semver:
        problems.append(f"its version is {bom.version}, not the tag's {semver}")

    # 5. Its components are exactly the declared release components, each once.
    declared, development = _declared_refs(root, parent, problems)
    named = Counter(component.bom_ref for component in bom.components)
    for ref, count in sorted(named.items()):
        if count > 1:
            problems.append(f"it names {ref} {count} times")
        if ref in development:
            problems.append(f"it names {ref}, a development image, which is not a release "
                            "component")
        elif declared and ref not in declared:
            problems.append(f"it names {ref}, which the declaration at the branch point does "
                            "not declare")
    for ref in sorted(declared - set(named)):
        problems.append(f"it does not name {ref}, which the declaration at the branch point "
                        "declares")

    # 6. No version it names was recorded by an earlier release with other contents.
    try:
        problems += violations(subject_of(bom), recorded_releases(root, exclude=tag))
    except BomError as error:
        problems.append(str(error))
    return problems


def main(argv: list[str] | None = None, root: Path = REPO_ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("tag", help="the marketplace-v<semver> tag to check")
    parser.add_argument("--default-branch", default=DEFAULT_BRANCH,
                        help=f"the branch a release is cut from (default: {DEFAULT_BRANCH})")
    arguments = parser.parse_args(argv)
    problems = check(arguments.tag, root=root, default_branch=arguments.default_branch)
    if problems:
        print(f"check-release-record: {arguments.tag}:", file=sys.stderr)
        for problem in problems:
            for line in problem.splitlines():
                print(f"  {line}", file=sys.stderr)
        return 1
    print(f"OK: {arguments.tag} records a marketplace release in the shape the cut makes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
