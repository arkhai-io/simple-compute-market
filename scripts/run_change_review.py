#!/usr/bin/env python3
"""Run a review of an OpenSpec change in Codex and record it under the change.

The review is produced by the `change-review` skill in a read-only Codex sandbox,
so the reviewer cannot change what it reviews. Its final message is the review and
is written to the change's next numbered `reviews/NN-<kind>.md`; the full session
output goes beside it as `NN-<kind>.log`. Both are untracked review records.

Contract: openspec/specs/change-workflow/spec.md.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable, Sequence

ROOT = Path(__file__).resolve().parents[1]
CHANGES = Path("openspec/changes")
KINDS = ("design", "implementation", "pre-closeout", "closeout")
DEFAULT_BASE = "dev"
_NUMBERED = re.compile(r"^(\d+)-")

Runner = Callable[[Sequence[str], Path], int]


class ReviewError(RuntimeError):
    """The review could not be started or produced no review."""


def next_review_path(reviews: Path, kind: str) -> Path:
    """The next numbered review file, after every record already in `reviews`."""
    numbers = [
        int(match.group(1))
        for entry in reviews.iterdir()
        if (match := _NUMBERED.match(entry.name))
    ] if reviews.is_dir() else []
    return reviews / f"{max(numbers, default=0) + 1:02d}-{kind}.md"


def review_prompt(kind: str, change: str, base: str) -> str:
    prompt = f"Use the change-review skill. Review kind: {kind}. Change: {change}."
    if kind != "design":
        prompt += f" Base: {base}."
    return prompt


def codex_command(prompt: str, output: Path, root: Path, model: str | None) -> list[str]:
    command = ["codex", "exec", "--sandbox", "read-only", "--cd", str(root),
               "--output-last-message", str(output)]
    if model:
        command += ["--model", model]
    return command + [prompt]


def _run_codex(command: Sequence[str], log: Path) -> int:
    with log.open("w", encoding="utf-8") as stream:
        return subprocess.run(list(command), stdin=subprocess.DEVNULL, stdout=stream,
                              stderr=subprocess.STDOUT, check=False).returncode


def run_review(change: str, kind: str, *, base: str = DEFAULT_BASE, model: str | None = None,
               root: Path = ROOT, runner: Runner = _run_codex) -> Path:
    if kind not in KINDS:
        raise ReviewError(f"unknown review kind {kind!r}; expected one of {', '.join(KINDS)}")
    change_dir = root / CHANGES / change
    if change in ("", "archive") or "/" in change or not change_dir.is_dir():
        raise ReviewError(f"no active change {change!r} under {CHANGES}")
    reviews = change_dir / "reviews"
    reviews.mkdir(exist_ok=True)
    output = next_review_path(reviews, kind)
    log = output.with_suffix(".log")
    status = runner(codex_command(review_prompt(kind, change, base), output, root, model), log)
    if status != 0 or not output.is_file() or not output.read_text("utf-8").strip():
        output.unlink(missing_ok=True)
        raise ReviewError(f"the reviewer produced no review (exit {status}); see {log.relative_to(root)}")
    return output


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--change", required=True)
    parser.add_argument("--kind", required=True, choices=KINDS)
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--model", default=None)
    args = parser.parse_args(argv)
    try:
        output = run_review(args.change, args.kind, base=args.base, model=args.model or None)
    except ReviewError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Review written to {output.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
