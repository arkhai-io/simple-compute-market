#!/usr/bin/env python3
"""Reject recognizable private content before publishing repository changes.

Only added text, filenames and commit messages are inspected. Diagnostics omit
matched values. Unknown operational identifiers require a private local denylist;
this check supplements review rather than proving the absence of secrets.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOME = re.compile(r"(?:/(?:home|Users)/|[A-Za-z]:[\\/]+Users[\\/]+)([^/\\\s\"'<>{}$]+)")
# These are explicit fixture names or accounts used by repository-owned images.
PUBLIC_USERS = frozenset({'example-user', 'appuser', 'ubuntu', 'you'})
PRIVATE_PLAN = re.compile(r"[/.](?:hermes|codex)/(?:plans|sessions)/")


def git(root: Path, *args: str) -> str:
    result = subprocess.run(['git', *args], cwd=root, capture_output=True)
    if result.returncode:
        raise ValueError('Git inspection failed; fetch the required base before retrying')
    return result.stdout.decode('utf-8', errors='replace')


def denylist(root: Path) -> tuple[str, ...]:
    result = subprocess.run(['git', 'config', '--path', '--get',
                             'scm.publicContentDenyFile'], cwd=root, capture_output=True)
    if result.returncode == 1:
        return ()
    if result.returncode:
        raise ValueError('Cannot read local public-content configuration')
    path = Path(result.stdout.decode().strip())
    if not path.is_absolute():
        path = root / path
    try:
        values = path.read_text(encoding='utf-8').splitlines()
    except (OSError, UnicodeError) as exc:
        raise ValueError('Configured private denylist is unreadable') from exc
    return tuple(line.strip().casefold() for line in values
                 if line.strip() and not line.lstrip().startswith('#'))


def reasons(text: str, denied: tuple[str, ...]) -> list[str]:
    found = []
    if any(m.group(1) not in PUBLIC_USERS for m in HOME.finditer(text)):
        found.append('personal home path')
    if PRIVATE_PLAN.search(text):
        found.append('private assistant planning/session path')
    if any(value in text.casefold() for value in denied):
        found.append('locally denied identifier')
    return found


def inspect_diff(diff: str, denied: tuple[str, ...]) -> list[str]:
    """Read a zero-context Git patch without printing the patch or its values."""
    findings = []
    path = '<file>'
    number = 0
    for line in diff.splitlines():
        if line.startswith('diff --git '):
            # Filenames may themselves contain private values. Never echo a
            # suspicious header, including Git's quoted/escaped filenames.
            decoded = re.sub(rb'\\([0-7]{3})',
                             lambda m: bytes((int(m[1], 8),)),
                             line.encode('utf-8')).decode('utf-8', errors='replace')
            if reasons(decoded, denied):
                findings.append('<filename>: private path or identifier')
            path = '<file>'
        elif line.startswith('+++ b/'):
            candidate = line[6:]
            matched = reasons(candidate, denied)
            findings.extend('<filename>: ' + reason for reason in matched)
            path = '<filename>' if matched else candidate
        elif line.startswith('@@ '):
            match = re.search(r'\+(\d+)', line)
            number = int(match[1]) if match else 0
        elif line.startswith('+'):
            for reason in reasons(line[1:], denied):
                findings.append(f'{path}:{number}: {reason}')
            number += 1
        elif line.startswith('Binary files ') or line == 'GIT binary patch':
            findings.append('<binary file>: content requires explicit review; automatic scan unavailable')
    return findings


def scan(root: Path, *, staged: bool = False, base: str | None = None,
         remote: str | None = None, tip: str = "HEAD") -> list[str]:
    denied = denylist(root)
    if staged:
        return inspect_diff(git(root, 'diff', '--cached', '--no-ext-diff',
                                '--no-textconv', '--no-renames', '--unified=0'), denied)
    tip = git(root, 'rev-parse', '--verify', tip + '^{commit}').strip()
    if base:
        base = git(root, 'rev-parse', '--verify', base + '^{commit}').strip()
        commits = git(root, 'rev-list', '--reverse', tip, '^' + base).splitlines()
    else:
        if not remote or remote.startswith('-'):
            raise ValueError('A target remote is required')
        refs = git(root, 'for-each-ref', '--format=%(objectname)',
                   'refs/remotes/' + remote + '/').splitlines()
        if not refs:
            raise ValueError('No target-remote refs available; fetch before publishing')
        commits = git(root, 'rev-list', '--reverse', tip, *('^' + r for r in refs)).splitlines()
    findings = []
    for commit in commits:
        message = git(root, 'show', '-s', '--format=%B', commit)
        findings.extend(f'{commit[:12]}:<commit message>: {r}' for r in reasons(message, denied))
        # Compare every parent, including merges, and inspect each intermediate
        # commit: removing a leak later does not remove it from public history.
        patch = git(root, 'diff-tree', '--root', '-m', '-p', '--no-ext-diff',
                    '--no-textconv', '--no-renames', '--unified=0', commit)
        findings.extend(f'{commit[:12]}:{f}' for f in inspect_diff(patch, denied))
    return findings


def main(argv: list[str] | None = None, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--staged', action='store_true')
    modes.add_argument('--base')
    modes.add_argument('--outgoing', metavar='REMOTE')
    modes.add_argument('--pre-push', metavar='REMOTE')
    args = parser.parse_args(argv)
    try:
        if args.pre_push:
            findings = []
            for line in sys.stdin:
                fields = line.split()
                if len(fields) != 4:
                    raise ValueError('Malformed pre-push update')
                local_ref, local_oid, remote_ref, remote_oid = fields
                denied = denylist(root)
                findings.extend('<ref name>: ' + r
                                for r in reasons(local_ref + ' ' + remote_ref, denied))
                if local_oid == '0' * 40:
                    continue
                if git(root, 'cat-file', '-t', local_oid).strip() == 'tag':
                    tag = git(root, 'cat-file', 'tag', local_oid)
                    findings.extend('<tag annotation>: ' + r for r in reasons(tag, denied))
                findings.extend(scan(root, tip=local_oid,
                    base=remote_oid if remote_oid != '0' * 40 else None,
                    remote=args.pre_push))
        else:
            findings = scan(root, staged=args.staged, base=args.base, remote=args.outgoing)
    except ValueError as exc:
        print('REFUSED: ' + str(exc), file=sys.stderr)
        return 1
    if findings:
        print('\n'.join('REFUSED: ' + f for f in findings), file=sys.stderr)
        return 1
    print('OK: no recognizable private content in inspected additions/messages.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
