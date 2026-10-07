#!/usr/bin/env python3
"""Run a review of an OpenSpec change in Codex and record it under the change.

The review is produced by the `change-review` skill in a read-only Codex sandbox,
so the reviewer cannot change what it reviews. Its final message is the review. It
is checked for the review format before it is published as the change's next
numbered `reviews/NN-<kind>.md`, which is the only authoritative record of its
findings. The full session goes to `reviews/transcripts/NN-<kind>.log`: a
non-authoritative transcript that no review or triage step reads, kept for export.
A run whose output is not a review publishes nothing; its output is kept beside the
transcript as `NN-<kind>.rejected.md`.

A later review of the same kind continues the reviewer session that wrote the
latest one, so the reviewer weighs a revision with the context that led to its
findings; the session is named in a comment at the end of each published record,
because transcripts are disposable and the record is not. A continued reviewer
still reads the triage and dispositions from the records.

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
TRANSCRIPTS = "transcripts"
SECTIONS = ("Summary", "Assessment", "Questions", "Findings", "Readiness")
FIELDS = {
    "Lens": {"direction", "consistency", "testing", "documentation", "architecture",
             "scope", "readiness"},
    "Basis": {"specification", "guidance", "evidence", "judgement"},
    "Severity": {"blocking", "should", "minor"},
    "Evidence": None,
}
_NUMBERED = re.compile(r"^(\d+)-")
_FINDING = re.compile(r"^### F\d+\b", re.M)
_FIELD = re.compile(r"^- \*\*(\w+):\*\*\s*(.*?)\s*$", re.M)
_SESSION_LINE = re.compile(r"^session id: (\S+)\s*$", re.M)
_SESSION_MARKER = re.compile(r"<!-- reviewer-session: (\S+) -->")

Runner = Callable[[Sequence[str], Path], int]


class ReviewError(RuntimeError):
    """The review could not be started or produced no review."""


def next_review_path(reviews: Path, kind: str) -> Path:
    """The next numbered review file, after every record and transcript in `reviews`.

    A failed run keeps its number through its transcript, so a later run never
    overwrites the evidence of an earlier one.
    """
    entries = [entry for directory in (reviews, reviews / TRANSCRIPTS) if directory.is_dir()
               for entry in directory.iterdir()]
    numbers = [int(match.group(1)) for entry in entries if (match := _NUMBERED.match(entry.name))]
    return reviews / f"{max(numbers, default=0) + 1:02d}-{kind}.md"


def review_problems(text: str, kind: str, change: str) -> list[str]:
    """Why `text` is not a review in the `change-review` format; empty when it is."""
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return ["the output is empty"]
    title = lines[0].lower()
    if not (title.startswith("# ") and f"{kind} review" in title and change.lower() in title):
        return [f"the first line is not the title of a {kind} review of {change}: {lines[0][:80]!r}"]
    problems = []
    positions = [text.find(f"\n## {section}\n") for section in SECTIONS]
    for section, position in zip(SECTIONS, positions):
        if position < 0:
            problems.append(f"missing section '## {section}'")
    present = [position for position in positions if position >= 0]
    if present != sorted(present):
        problems.append(f"sections are not in the order {', '.join(SECTIONS)}")
    if problems:
        return problems
    findings = text[positions[3]:positions[4]]
    starts = [match.start() for match in _FINDING.finditer(findings)] + [len(findings)]
    for start, end in zip(starts, starts[1:]):
        block = findings[start:end]
        name = block.splitlines()[0][4:].split()[0]
        fields = {key: value for key, value in _FIELD.findall(block)}
        for field, allowed in FIELDS.items():
            value = fields.get(field, "")
            if not value:
                problems.append(f"{name} has no {field}")
            elif allowed is not None and value.lower() not in allowed:
                problems.append(f"{name} has {field} {value!r}, not one of {', '.join(sorted(allowed))}")
    return problems


def review_prompt(kind: str, change: str, base: str) -> str:
    prompt = f"Use the change-review skill. Review kind: {kind}. Change: {change}."
    if kind != "design":
        prompt += f" Base: {base}."
    return prompt


def continuation_prompt(kind: str, change: str, base: str, previous: str) -> str:
    prompt = (f"The change {change} has been revised since your review, {previous}. Re-read the "
              "change-review skill, which may have changed, and every file in the change, including "
              f"the triage records in reviews/. Then write a complete new {kind} review in the skill's "
              "format: say for each earlier finding, yours and any triaged beside it, whether the "
              "revision resolves it, and review the revised change as a whole.")
    if kind != "design":
        prompt += f" Base: {base}."
    return prompt


def prior_session(reviews: Path, kind: str) -> tuple[str, str] | None:
    """The reviewer session and record of the latest published review of `kind`."""
    records = sorted(reviews.glob(f"[0-9]*-{kind}.md")) if reviews.is_dir() else []
    for record in reversed(records):
        if match := _SESSION_MARKER.search(record.read_text("utf-8")):
            return match.group(1), record.stem
    return None


def _options(output: Path, model: str | None, effort: str | None) -> list[str]:
    options = ["--output-last-message", str(output)]
    if model:
        options += ["--model", model]
    if effort:
        options += ["--config", f'model_reasoning_effort="{effort}"']
    return options


def codex_command(prompt: str, output: Path, root: Path, model: str | None,
                  effort: str | None = None) -> list[str]:
    return ["codex", "exec", "--sandbox", "read-only", "--cd", str(root),
            *_options(output, model, effort), prompt]


def resume_command(session: str, prompt: str, output: Path, model: str | None,
                   effort: str | None = None) -> list[str]:
    # `exec resume` takes no --sandbox flag, so the read-only sandbox is set through
    # configuration; the reviewer must never be able to change what it reviews.
    return ["codex", "exec", "resume", session, "--config", 'sandbox_mode="read-only"',
            *_options(output, model, effort), prompt]


def _run_codex(command: Sequence[str], log: Path) -> int:
    with log.open("w", encoding="utf-8") as stream:
        return subprocess.run(list(command), cwd=ROOT, stdin=subprocess.DEVNULL, stdout=stream,
                              stderr=subprocess.STDOUT, check=False).returncode


def run_review(change: str, kind: str, *, base: str = DEFAULT_BASE, model: str | None = None,
               effort: str | None = None, fresh: bool = False, root: Path = ROOT,
               runner: Runner = _run_codex) -> Path:
    if kind not in KINDS:
        raise ReviewError(f"unknown review kind {kind!r}; expected one of {', '.join(KINDS)}")
    change_dir = root / CHANGES / change
    if change in ("", "archive") or "/" in change or not change_dir.is_dir():
        raise ReviewError(f"no active change {change!r} under {CHANGES}")
    reviews = change_dir / "reviews"
    transcripts = reviews / TRANSCRIPTS
    transcripts.mkdir(parents=True, exist_ok=True)
    output = next_review_path(reviews, kind)
    log = transcripts / output.with_suffix(".log").name
    draft = transcripts / output.with_suffix(".rejected.md").name
    prior = None if fresh else prior_session(reviews, kind)
    if prior:
        session, previous = prior
        command = resume_command(session, continuation_prompt(kind, change, base, previous),
                                 draft, model, effort)
    else:
        command = codex_command(review_prompt(kind, change, base), draft, root, model, effort)
    status = runner(command, log)
    text = draft.read_text("utf-8") if draft.is_file() else ""
    problems = [f"the reviewer exited {status}"] if status != 0 else review_problems(text, kind, change)
    if problems:
        if not text.strip():
            draft.unlink(missing_ok=True)
        raise ReviewError("the reviewer produced no review: " + "; ".join(problems)
                          + f"; see {log.relative_to(root)}")
    session = _SESSION_LINE.search(log.read_text("utf-8")) if log.is_file() else None
    if session:
        text = text.rstrip("\n") + f"\n\n<!-- reviewer-session: {session.group(1)} -->\n"
    output.write_text(text, "utf-8")
    draft.unlink()
    return output


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--change", required=True)
    parser.add_argument("--kind", required=True, choices=KINDS)
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--model", default=None)
    parser.add_argument("--effort", default=None)
    parser.add_argument("--fresh", action="store_true",
                        help="start a new reviewer session instead of continuing the last one")
    args = parser.parse_args(argv)
    try:
        output = run_review(args.change, args.kind, base=args.base, model=args.model or None,
                            effort=args.effort or None, fresh=args.fresh)
    except ReviewError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Review written to {output.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
