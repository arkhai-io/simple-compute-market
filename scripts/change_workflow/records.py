"""A change's numbered records in `reviews/`, the validation they hold, and the
commits they name.

Records and transcripts share one numbering: each takes the number after every
numbered file in `reviews/` and its transcripts, so a record written beside a run
is never overwritten by it. A triage's outcome names the records it triaged by
these names (`triaged_problems`). A validation record clears a commit for what follows
it when it names that commit, or an ancestor from which the commit changes only
changes' records — or, at closeout's gate, only documentation.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any, Callable

from change_workflow.common import CHANGES, KINDS

TRANSCRIPTS = "transcripts"
NUMBERED = re.compile(r"^(\d+)-")
_VALIDATION_COMMIT = re.compile(r"^- \*\*Commit:\*\*\s*([0-9a-f]{7,40})\b", re.M)
_VALIDATION_RESULT = re.compile(r"^- \*\*Result:\*\*\s*(\w+)", re.M)

# The paths a commit changes since an earlier one, or None when that commit is not
# an ancestor of it.
ChangedSince = Callable[[Path, str, str], list[str] | None]

# A change's records: its ledger and its reviews, whether the change is active or
# under its dated archive directory. A closeout triage edits an archived change's
# ledger, so the archive must count, or that edit would read as a fix.
RECORD_PATH = re.compile(
    rf"^{re.escape(str(CHANGES))}/(?:archive/)?(?!archive/)[^/]+/(interventions\.jsonl$|reviews/)")

# The documents. A commit after a pre-closeout review, or a closeout correction, may
# change them without a validation, since closeout's own checks (`make check-change`,
# `make check-packaging`) read them again before the archive; a skill or the step
# table changes behaviour, so `.agents/` and `.claude/` are outside. Before then only
# changes' records are exempt: documentation the packaging checks read, such as
# `docs/development/ARCHITECTURE.toml`, is checked by nothing but the next validation.
DOCUMENTATION = ("openspec/", "docs/")


def is_record(path: str) -> bool:
    return bool(RECORD_PATH.match(path))


def is_documentation(path: str) -> bool:
    return path.startswith(DOCUMENTATION)


def next_number(reviews: Path) -> int:
    """The number after every numbered record and transcript in `reviews`."""
    entries = [entry for directory in (reviews, reviews / TRANSCRIPTS) if directory.is_dir()
               for entry in directory.iterdir()]
    return max((int(match.group(1)) for entry in entries
                if (match := NUMBERED.match(entry.name))), default=0) + 1


def next_transcript(reviews: Path, step: str) -> Path:
    """Claim `reviews/transcripts/NN-<step>.jsonl`, numbered after every record.

    The number follows every numbered file in `reviews/` and its transcripts, as a
    review record's does, and the create is exclusive, so no run overwrites
    another's transcript.
    """
    transcripts = reviews / TRANSCRIPTS
    transcripts.mkdir(parents=True, exist_ok=True)
    while True:
        path = transcripts / f"{next_number(reviews):02d}-{step}.jsonl"
        try:
            path.open("x", encoding="utf-8").close()
            return path
        except FileExistsError:
            continue


def git_head(root: Path) -> str | None:
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                          text=True)
    return head.stdout.strip() if head.returncode == 0 else None


def changed_since(root: Path, commit: str, head: str) -> list[str] | None:
    if subprocess.run(["git", "merge-base", "--is-ancestor", commit, head], cwd=root,
                      capture_output=True).returncode != 0:
        return None
    # Without --no-renames a file moved under a change's records would be listed
    # only at its new path, hiding the code it removed.
    diff = subprocess.run(["git", "diff", "--name-only", "--no-renames", "-z", commit, head],
                          cwd=root, capture_output=True, text=True)
    return [path for path in diff.stdout.split("\0") if path] if diff.returncode == 0 else None


_RECORD_NAME = re.compile(r"^\d+-([a-z]+(?:-[a-z]+)*)$")


def triaged_problems(triaged: Any, reviews: Path) -> list[str]:
    """Why `triaged`, the records a triage's outcome names, does not name what it
    triaged; empty when it does.

    It is a non-empty list of distinct names, each a numbered record in `reviews` as
    its file is named without `.md`, `NN-<kind>`, with its triage file beside it, and
    at least one of them a review, `-external` included; the others may be the
    validation, the owner's notes, or the orchestrating session's observations
    triaged with it. Whether a record belongs to the triage the computation meant
    cannot be checked here: the triage file beside it is that triage's mark.
    """
    if triaged is None:
        return ["the triage names no records in triaged"]
    if not isinstance(triaged, list) or not triaged:
        return [f"triaged is not a non-empty list of records: {triaged!r}"]
    problems = []
    seen: set[str] = set()
    kinds = []
    for name in triaged:
        if not isinstance(name, str) or not (match := _RECORD_NAME.match(name)):
            problems.append(f"{name!r} is not a record's name, NN-<kind>")
            continue
        if name in seen:
            problems.append(f"{name} is named twice")
            continue
        seen.add(name)
        if not (reviews / f"{name}.md").is_file():
            problems.append(f"{name} is no record in reviews/")
        elif not (reviews / f"{name}.triage.md").is_file():
            problems.append(f"{name} has no triage file beside it")
        kinds.append(match.group(1))
    if not problems and not any(kind.removesuffix("-external") in KINDS for kind in kinds):
        problems.append(f"{', '.join(triaged)} names no review")
    return problems


def triage_outcome_problems(outcome: Any, reviews: Path) -> list[str]:
    """Why a triage's outcome does not name what it triaged; empty when it does, or
    when it ends without an exit — a question, a block, or a stop — and so names
    nothing the next step is routed on."""
    if not isinstance(outcome, dict) or outcome.get("outcome") not in ("finished", "returned"):
        return []
    return triaged_problems(outcome.get("triaged"), reviews)


def latest_validation(reviews: Path) -> Path | None:
    """The change's latest validation record, if it has one."""
    records = [(int(match.group(1)), entry) for entry in
               (reviews.glob("[0-9]*-validation.md") if reviews.is_dir() else [])
               if (match := NUMBERED.match(entry.name))]
    return max(records)[1] if records else None


def validation_result(record: Path) -> str | None:
    """The result a validation record states, lower-cased: `passed`, `failed`,
    `inconclusive`; None when it states none."""
    result = _VALIDATION_RESULT.search(record.read_text("utf-8"))
    return result.group(1).lower() if result else None


def validation_problem(reviews: Path, head: str, root: Path | None = None,
                       changed_since: ChangedSince = changed_since,
                       require_passed: bool = True,
                       exempt: Callable[[str], bool] = is_record) -> str | None:
    """Why the latest validation record does not clear `head` for closeout, if it does not.

    A validation of an ancestor clears `head` when every path the two commits
    differ in is `exempt` — changes' records by default; without `root` to compare
    them in, only `head` itself does. Without `require_passed`, a record of the
    right commit clears it whatever its result, for a caller that reads the result
    itself.
    """
    record = latest_validation(reviews)
    if record is None:
        return "the change has no validation record"
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
        if others := [path for path in changed if not exempt(path)]:
            return (f"{record.name} validates {validated[:12]}, and HEAD {head[:12]} also "
                    f"changes {', '.join(others[:3])}" + (" …" if len(others) > 3 else ""))
    if require_passed and (not result or result.group(1).lower() != "passed"):
        return f"{record.name}'s result is {result.group(1) if result else 'missing'}, not passed"
    return None
