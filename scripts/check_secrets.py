#!/usr/bin/env python3
"""Refuse a private key in content about to be published, through the pinned gitleaks.

Runs the gitleaks release `scripts/gitleaks-pins.toml` pins with the repository's
`.gitleaks.toml` beside `check_public_content.py`, wherever that runs: over the
staged additions, or over every commit of a range. A range is read with merges
compared with each of their parents (`--diff-merges=separate`): gitleaks reads
commits through `git log -p`, which prints no patch for a merge otherwise, so a key
written only while resolving a merge would reach nothing it inspects.

gitleaks redacts what it matched, and a finding is reported by rule, file, line and
commit only, never with its content. A `gitleaks:allow` comment silences nothing:
the repository keeps no exception markers, and a fixture passes because its body
holds no key material, not because it is marked.

See docs/development/ARCHITECTURE.md, "Public repository content checks".
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, Sequence

from install_gitleaks import problem as gitleaks_problem

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".gitleaks.toml"
MERGE_PATCHES = "--diff-merges=separate"
NO_COMMIT = "0" * 40

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


def command(source: Sequence[str], root: Path, report: Path) -> list[str]:
    """The gitleaks command scanning `source` in the repository at `root`."""
    return ["gitleaks", *source, "--config", str(CONFIG), "--redact",
            "--ignore-gitleaks-allow", "--no-banner", "--no-color", "--log-level", "error",
            "--report-format", "json", "--report-path", str(report), "--exit-code", "1",
            str(root)]


def _location(finding: dict) -> str:
    where = f"{finding.get('File') or '<file>'}:{finding.get('StartLine', 0)}"
    commit = finding.get("Commit") or ""
    return f"{commit[:12]}:{where}" if commit else where


def scan_source(root: Path, source: Sequence[str], *, run: Run = _run) -> list[str]:
    """Each finding of one gitleaks scan, as `[<commit>:]<file>:<line>: <rule>`."""
    with tempfile.TemporaryDirectory() as scratch:
        report = Path(scratch) / "report.json"
        done = run(command(source, root, report), root)
        try:
            findings = json.loads(report.read_text("utf-8")) if report.exists() else None
        except (OSError, ValueError):
            findings = None
    if done.returncode not in (0, 1) or findings is None or (
            done.returncode == 1 and not findings):
        detail = (done.stderr or done.stdout or "").strip().splitlines()
        raise SecretsError("gitleaks could not complete the scan"
                           + (f": {detail[-1]}" if detail else ""))
    found = dict.fromkeys(f"{_location(f)}: {f.get('RuleID', 'secret')}" for f in findings)
    return list(found)


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    if done.returncode:
        raise SecretsError("Git inspection failed; fetch the required base before retrying")
    return done.stdout


def _commit(root: Path, revision: str) -> str:
    return _git(root, "rev-parse", "--verify", "--end-of-options",
                revision + "^{commit}").strip()


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
    """Every private key the staged additions, or the commits after `base` or not on
    `remote`, add; refuses to scan with any gitleaks but the pinned release."""
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
    """Every private key the commits of a pre-push hook's ref updates add."""
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


def main(argv: Sequence[str] | None = None, root: Path = ROOT, *, run: Run = _run,
         version_problem: VersionProblem = gitleaks_problem) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--staged", action="store_true")
    modes.add_argument("--base")
    modes.add_argument("--outgoing", metavar="REMOTE")
    modes.add_argument("--pre-push", metavar="REMOTE")
    args = parser.parse_args(argv)
    try:
        if args.pre_push:
            findings = pre_push(root, args.pre_push, sys.stdin.read().splitlines(), run=run,
                                version_problem=version_problem)
        else:
            findings = scan(root, staged=args.staged, base=args.base, remote=args.outgoing,
                            run=run, version_problem=version_problem)
    except SecretsError as exc:
        print("REFUSED: " + str(exc), file=sys.stderr)
        return 1
    if findings:
        print("\n".join("REFUSED: " + f for f in findings), file=sys.stderr)
        return 1
    print("OK: gitleaks found no secret in the inspected additions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
