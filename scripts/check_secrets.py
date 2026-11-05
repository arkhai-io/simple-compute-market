#!/usr/bin/env python3
"""Refuse a private key or a provider credential about to be published, through the pinned gitleaks.

Runs the gitleaks release `scripts/gitleaks-pins.toml` pins beside
`check_public_content.py`, wherever that runs: over the staged additions, or over
every commit of a range. That gate's configuration is `.gitleaks.toml`: gitleaks'
default rules but four, with the repository's key rule in place of the default one.
A range is read with merges compared with each of their parents
(`--diff-merges=separate`): gitleaks reads commits through `git log -p`, which
prints no patch for a merge otherwise, so a key written only while resolving a merge
would reach nothing it inspects.

`--audit` runs every default rule but the key rule the repository replaces,
`scripts/gitleaks-audit.toml`, over `HEAD`'s tracked tree, and reports what it finds
without refusing anything: it is read by hand before an official build ships, and
fails only when gitleaks could not run.

gitleaks redacts what it matched, and a finding is reported by rule, file, line and
commit only, never with its content. A `gitleaks:allow` comment silences nothing:
the repository keeps no exception markers, and a fixture passes because no rule of
the gate matches it, not because it is marked.

See openspec/specs/market-change-workflow/README.md, "Secret scanning".
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, Sequence

from install_gitleaks import problem as gitleaks_problem

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / ".gitleaks.toml"
AUDIT = ROOT / "scripts" / "gitleaks-audit.toml"
MERGE_PATCHES = "--diff-merges=separate"
NO_COMMIT = "0" * 40
# The tree commit's identity, so the audit commits nothing as whoever runs it and
# needs no Git identity configured.
TREE_IDENTITY = {"GIT_AUTHOR_NAME": "secret audit", "GIT_COMMITTER_NAME": "secret audit",
                 "GIT_AUTHOR_EMAIL": "audit@example.invalid",
                 "GIT_COMMITTER_EMAIL": "audit@example.invalid"}

# Runs a command in a directory and returns the finished process.
Run = Callable[[Sequence[str], Path], "subprocess.CompletedProcess[str]"]
# Why the pinned gitleaks cannot be run, or None.
VersionProblem = Callable[[], "str | None"]


class SecretsError(Exception):
    """The scan could not be run, so nothing it would refuse is known to be absent."""


def _run(command: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(command), cwd=cwd, capture_output=True, text=True)


def staged_source() -> list[str]:
    """gitleaks' arguments for the staged additions."""
    return ["git", "--staged"]


def range_source(revisions: Sequence[str]) -> list[str]:
    """gitleaks' arguments for every commit `revisions` selects, merges included.

    gitleaks splits `--log-opts` on spaces, so each revision is one word: a commit
    id, or `^<commit id>` to exclude what it reaches.
    """
    return ["git", "--log-opts=" + " ".join([*revisions, MERGE_PATCHES])]


def tree_source(commit: str) -> list[str]:
    """gitleaks' arguments for a parentless commit, whose patch adds its whole tree."""
    return range_source([commit, "--root"])


def command(source: Sequence[str], root: Path, report: Path,
            config: Path = GATE) -> list[str]:
    """The gitleaks command scanning `source` in the repository at `root`."""
    return ["gitleaks", *source, "--config", str(config), "--redact",
            "--ignore-gitleaks-allow", "--no-banner", "--no-color", "--log-level", "error",
            "--report-format", "json", "--report-path", str(report), "--exit-code", "1",
            str(root)]


def _where(finding: dict) -> str:
    return f"{finding.get('File') or '<file>'}:{finding.get('StartLine', 0)}"


def _location(finding: dict) -> str:
    commit = finding.get("Commit") or ""
    return f"{commit[:12]}:{_where(finding)}" if commit else _where(finding)


def _rule(finding: dict) -> str:
    return finding.get("RuleID") or "secret"


def _findings(root: Path, source: Sequence[str], config: Path, run: Run) -> list[dict]:
    with tempfile.TemporaryDirectory() as scratch:
        report = Path(scratch) / "report.json"
        # The gate's configuration extends the audit's by a path relative to the
        # repository root, which gitleaks resolves from its working directory.
        done = run(command(source, root, report, config), ROOT)
        try:
            findings = json.loads(report.read_text("utf-8")) if report.exists() else None
        except (OSError, ValueError):
            findings = None
    if done.returncode not in (0, 1) or findings is None or (
            done.returncode == 1 and not findings):
        detail = (done.stderr or done.stdout or "").strip().splitlines()
        raise SecretsError("gitleaks could not complete the scan"
                           + (f": {detail[-1]}" if detail else ""))
    return findings


def scan_source(root: Path, source: Sequence[str], *, config: Path = GATE,
                run: Run = _run) -> list[str]:
    """Each finding of one gitleaks scan, as `[<commit>:]<file>:<line>: <rule>`."""
    findings = _findings(root, source, config, run)
    return list(dict.fromkeys(f"{_location(f)}: {_rule(f)}" for f in findings))


def _git(root: Path, *args: str, failure: str = "Git inspection failed; fetch the "
         "required base before retrying", env: dict[str, str] | None = None) -> str:
    done = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                          env=None if env is None else {**os.environ, **env})
    if done.returncode:
        raise SecretsError(failure)
    return done.stdout


def _commit(root: Path, revision: str) -> str:
    return _git(root, "rev-parse", "--verify", "--end-of-options",
                revision + "^{commit}").strip()


@contextmanager
def tree_commit(root: Path) -> Iterator[tuple[Path, str]]:
    """A temporary shared clone of `root` and, in it, one parentless commit of
    `HEAD`'s tree: scanned as a commit, its patch adds every tracked file, so the
    scan reads the whole tree and nothing untracked or ignored."""
    with tempfile.TemporaryDirectory() as scratch:
        clone = Path(scratch) / "tree"
        failure = "Git could not read HEAD's tree"
        _git(root, "clone", "-q", "--shared", "--no-checkout", str(root), str(clone),
             failure=failure)
        whole = _git(clone, "commit-tree", "--no-gpg-sign", "-m", "HEAD's tree",
                     "HEAD^{tree}", failure=failure, env=TREE_IDENTITY).strip()
        yield clone, whole


def outgoing_revisions(root: Path, remote: str, tip: str = "HEAD") -> list[str]:
    """The revisions selecting what `tip` holds that no ref of `remote` reaches."""
    if not remote or remote.startswith("-"):
        raise SecretsError("A target remote is required")
    refs = _git(root, "for-each-ref", "--format=%(objectname)",
                "refs/remotes/" + remote + "/").split()
    if not refs:
        raise SecretsError("No target-remote refs available; fetch before publishing")
    return [_commit(root, tip), *("^" + ref for ref in refs)]


def scan(root: Path, *, staged: bool = False, base: str | None = None,
         remote: str | None = None, tip: str = "HEAD", run: Run = _run,
         version_problem: VersionProblem = gitleaks_problem) -> list[str]:
    """Every secret the gate finds in the staged additions, or in the commits after
    `base` or not on `remote`; refuses to scan with any gitleaks but the pinned
    release."""
    if (reason := version_problem()) is not None:
        raise SecretsError(reason)
    if staged:
        return scan_source(root, staged_source(), run=run)
    if base:
        revisions = [_commit(root, tip), "^" + _commit(root, base)]
    else:
        revisions = outgoing_revisions(root, remote or "", tip)
    return scan_source(root, range_source(revisions), run=run)


def pre_push(root: Path, remote: str, updates: Sequence[str], *, run: Run = _run,
             version_problem: VersionProblem = gitleaks_problem) -> list[str]:
    """Every secret the gate finds in the commits of a pre-push hook's ref updates."""
    findings: list[str] = []
    for line in updates:
        fields = line.split()
        if len(fields) != 4:
            raise SecretsError("Malformed pre-push update")
        _, local_oid, _, remote_oid = fields
        if local_oid == NO_COMMIT:
            continue
        findings.extend(scan(root, tip=local_oid,
                             base=remote_oid if remote_oid != NO_COMMIT else None,
                             remote=remote, run=run, version_problem=version_problem))
    return list(dict.fromkeys(findings))


def audit(root: Path, *, run: Run = _run,
          version_problem: VersionProblem = gitleaks_problem) -> list[str]:
    """What every rule of the audit finds in `HEAD`'s tracked tree, as
    `<file>:<line>: <rule>`."""
    if (reason := version_problem()) is not None:
        raise SecretsError(reason)
    with tree_commit(root) as (clone, whole):
        findings = _findings(clone, tree_source(whole), AUDIT, run)
    return list(dict.fromkeys(f"{_where(f)}: {_rule(f)}" for f in findings))


def main(argv: Sequence[str] | None = None, root: Path = ROOT, *, run: Run = _run,
         version_problem: VersionProblem = gitleaks_problem) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--staged", action="store_true")
    modes.add_argument("--base")
    modes.add_argument("--outgoing", metavar="REMOTE")
    modes.add_argument("--pre-push", metavar="REMOTE")
    modes.add_argument("--audit", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.audit:
            findings = audit(root, run=run, version_problem=version_problem)
        elif args.pre_push:
            findings = pre_push(root, args.pre_push, sys.stdin.read().splitlines(), run=run,
                                version_problem=version_problem)
        else:
            findings = scan(root, staged=args.staged, base=args.base, remote=args.outgoing,
                            run=run, version_problem=version_problem)
    except SecretsError as exc:
        print(("ERROR: " if args.audit else "REFUSED: ") + str(exc), file=sys.stderr)
        return 1
    if args.audit:
        print("\n".join([*findings, f"The audit of HEAD's tracked tree reported "
                         f"{len(findings)} finding(s); read each before an official "
                         "build ships."]))
        return 0
    if findings:
        print("\n".join("REFUSED: " + f for f in findings), file=sys.stderr)
        return 1
    print("OK: gitleaks found no secret in the inspected additions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
