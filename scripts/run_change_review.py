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

A review takes its number when it is published, not when its run starts, so a
validation written beside it meanwhile is numbered first; until then its transcript
has a provisional name. The record's name is claimed with an exclusive create, so
this runner never overwrites a record. Records of different kinds written at the same
moment may still share a number; their file times order them.

Each published review names the commit it reviewed, `HEAD` when its run started,
in a comment at its end, so triage can compare it with the commit a validation
describes.

A pre-closeout review asks whether the change is ready for closeout, which a failing
pipeline answers, so it refuses to start unless the change's latest validation
record names `HEAD`, or an ancestor from which `HEAD` changes only changes' records —
their ledgers and reviews, which no check or pipeline reads — and its result is
`passed`; the owner may override that.

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
import uuid
import subprocess
import sys
from pathlib import Path
from typing import Callable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from find_change import ChangeNotFound, change_directory  # noqa: E402

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
REVIEWED_COMMIT = "<!-- reviewed-commit: {} -->"
_VALIDATION_COMMIT = re.compile(r"^- \*\*Commit:\*\*\s*([0-9a-f]{7,40})\b", re.M)
_VALIDATION_RESULT = re.compile(r"^- \*\*Result:\*\*\s*(\w+)", re.M)

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


def claim_record(reviews: Path, kind: str,
                 propose: Callable[[Path, str], Path] | None = None) -> Path:
    """Create the next numbered record of `kind`, empty, and return it.

    The create is exclusive: if another writer took the proposed name in the
    meantime, the next number is tried, so no record is overwritten.
    """
    propose = propose or next_review_path
    while True:
        path = propose(reviews, kind)
        try:
            path.open("x", encoding="utf-8").close()
            return path
        except FileExistsError:
            continue


# The paths a commit changes since an earlier one, or None when that commit is not
# an ancestor of it.
ChangedSince = Callable[[Path, str, str], list[str] | None]


def _changed_since(root: Path, commit: str, head: str) -> list[str] | None:
    if subprocess.run(["git", "merge-base", "--is-ancestor", commit, head], cwd=root,
                      capture_output=True).returncode != 0:
        return None
    # Without --no-renames a file moved under a change's records would be listed
    # only at its new path, hiding the code it removed.
    diff = subprocess.run(["git", "diff", "--name-only", "--no-renames", "-z", commit, head],
                          cwd=root, capture_output=True, text=True)
    return [path for path in diff.stdout.split("\0") if path] if diff.returncode == 0 else None


_RECORD = re.compile(
    rf"^{re.escape(str(CHANGES))}/(?!archive/)[^/]+/(interventions\.jsonl$|reviews/)")


def validation_problem(reviews: Path, head: str, root: Path | None = None,
                       changed_since: ChangedSince = _changed_since) -> str | None:
    """Why the latest validation record does not clear `head` for closeout, if it does not.

    A validation of an ancestor clears `head` when the two commits differ only in
    changes' records; without `root` to compare them in, only `head` itself does.
    """
    records = [(int(match.group(1)), entry) for entry in
               (reviews.glob("[0-9]*-validation.md") if reviews.is_dir() else [])
               if (match := _NUMBERED.match(entry.name))]
    if not records:
        return "the change has no validation record"
    record = max(records)[1]
    text = record.read_text("utf-8")
    commit = _VALIDATION_COMMIT.search(text)
    result = _VALIDATION_RESULT.search(text)
    if not commit:
        return f"{record.name} validates no commit, not HEAD {head[:12]}"
    validated = commit.group(1)
    if not head.startswith(validated):
        changed = changed_since(root, validated, head) if root else None
        if changed is None:
            return f"{record.name} validates {validated[:12]}, not HEAD {head[:12]}"
        if others := [path for path in changed if not _RECORD.match(path)]:
            return (f"{record.name} validates {validated[:12]}, and HEAD {head[:12]} also "
                    f"changes {', '.join(others[:3])}" + (" …" if len(others) > 3 else ""))
    if not result or result.group(1).lower() != "passed":
        return f"{record.name}'s result is {result.group(1) if result else 'missing'}, not passed"
    return None


def _git_head(root: Path) -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ReviewError(f"could not read HEAD, the commit under review: {exc}") from exc


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


class Progress:
    """Condense Codex's plain session output into a readable progress stream.

    The transcript keeps everything; the terminal gets the session header, each
    command as one line, failed commands, errors, and the agent's messages, with
    long messages — the final review among them — cut short. Command output, which
    is mostly the files the reviewer reads, is never shown.
    """

    HEADER_KEYS = ("model:", "reasoning effort:", "sandbox:", "session id:")
    MESSAGE_LINES = 4

    def __init__(self) -> None:
        self._block = "header"
        self._message: list[str] = []

    def feed(self, line: str) -> list[str]:
        line = line.rstrip("\n")
        if line.startswith("ERROR:"):
            return [line]
        label = line.strip()
        if label in ("codex", "exec", "user", "thinking", "tokens used") and line == label:
            shown = self._flush()
            self._block = label
            return shown
        if line.startswith(" succeeded in ") or line.startswith(" exited "):
            self._block = "output"
            return [f"  ✗{line}"] if line.startswith(" exited ") else []
        if self._block == "header":
            return [line] if line.startswith(self.HEADER_KEYS) else []
        if self._block == "exec" and line.startswith("/bin/bash -lc "):
            command = line[len("/bin/bash -lc "):].rsplit(" in /", 1)[0].strip("'\"")
            return [f"$ {command[:150]}"]
        if self._block == "codex":
            self._message.append(line)
        elif self._block == "tokens used" and label:
            self._block = "done"
            return [f"tokens used: {label}"]
        return []

    def close(self) -> list[str]:
        return self._flush()

    def _flush(self) -> list[str]:
        lines = [line for line in self._message if line.strip()]
        self._message = []
        if not lines:
            return []
        shown = [f"» {line}" for line in lines[:self.MESSAGE_LINES]]
        if len(lines) > self.MESSAGE_LINES:
            shown.append(f"» … ({len(lines) - self.MESSAGE_LINES} more lines in the transcript)")
        return shown


def _run_codex(command: Sequence[str], log: Path) -> int:
    progress = Progress()
    with log.open("w", encoding="utf-8") as stream:
        process = subprocess.Popen(list(command), cwd=ROOT, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding="utf-8", errors="replace")
        assert process.stdout is not None
        for line in process.stdout:
            stream.write(line)
            for shown in progress.feed(line):
                print(shown, flush=True)
        for shown in progress.close():
            print(shown, flush=True)
        return process.wait()


def run_review(change: str, kind: str, *, base: str = DEFAULT_BASE, model: str | None = None,
               effort: str | None = None, fresh: bool = False, root: Path = ROOT,
               runner: Runner = _run_codex, unvalidated: bool = False,
               head: Callable[[Path], str] = _git_head,
               changed_since: ChangedSince = _changed_since) -> Path:
    if kind not in KINDS:
        raise ReviewError(f"unknown review kind {kind!r}; expected one of {', '.join(KINDS)}")
    try:
        reviews = change_directory(root, change) / "reviews"
    except ChangeNotFound as exc:
        raise ReviewError(str(exc)) from exc
    reviewed = head(root)
    if kind == "pre-closeout" and not unvalidated:
        if problem := validation_problem(reviews, reviewed, root, changed_since):
            raise ReviewError(f"a pre-closeout review needs a passing validation of HEAD: "
                              f"{problem}; validate first, or set UNVALIDATED=1 to override")
    transcripts = reviews / TRANSCRIPTS
    transcripts.mkdir(parents=True, exist_ok=True)
    provisional = f"pending-{kind}-{uuid.uuid4().hex[:12]}"
    log = transcripts / f"{provisional}.log"
    draft = transcripts / f"{provisional}.rejected.md"
    prior = None if fresh else prior_session(reviews, kind)
    if prior:
        session, previous = prior
        command = resume_command(session, continuation_prompt(kind, change, base, previous),
                                 draft, model, effort)
    else:
        command = codex_command(review_prompt(kind, change, base), draft, root, model, effort)
    status: int | None = None
    try:
        status = runner(command, log)
    finally:
        # Numbered now, after every record written while the reviewer ran; an
        # interrupted run keeps its number too, through its transcript, and
        # leaves no empty record behind.
        output = claim_record(reviews, kind)
        if log.is_file():
            log = log.rename(transcripts / output.with_suffix(".log").name)
        if draft.is_file():
            draft = draft.rename(transcripts / output.with_suffix(".rejected.md").name)
        if status is None:
            output.unlink()
    text = draft.read_text("utf-8") if draft.is_file() else ""
    problems = [f"the reviewer exited {status}"] if status != 0 else review_problems(text, kind, change)
    if problems:
        output.unlink()
        if not text.strip():
            draft.unlink(missing_ok=True)
        raise ReviewError("the reviewer produced no review: " + "; ".join(problems)
                          + f"; see {log.relative_to(root)}")
    session = _SESSION_LINE.search(log.read_text("utf-8")) if log.is_file() else None
    text = text.rstrip("\n") + "\n"
    if session:
        text += f"\n<!-- reviewer-session: {session.group(1)} -->\n"
    text += REVIEWED_COMMIT.format(reviewed) + "\n"
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
    parser.add_argument("--unvalidated", action="store_true",
                        help="run a pre-closeout review without a passing validation of HEAD")
    args = parser.parse_args(argv)
    try:
        output = run_review(args.change, args.kind, base=args.base, model=args.model or None,
                            effort=args.effort or None, fresh=args.fresh,
                            unvalidated=args.unvalidated)
    except ReviewError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Review written to {output.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
