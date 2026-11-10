"""The change's workflow log: one line per run, and the orchestrating session's notes.

`record_outcome` appends a step's outcome as a line of the change's
`reviews/workflow.jsonl`, with a sequence number, the time, the step, and the
run's session and commit: the wrapper's for an unattended run, and
`record_interactive` for a run the owner held interactively, which records its own.
`note_round` and `note_orchestrator` append the
orchestrating session's own lines: a `round` line recording the implementation
round the owner agreed, and an `orchestrator` line recording a decision — the
orchestrating session's own routing or recovery, or the owner's — naming the run
whose denials it reads, the run it resolves, and, for the owner's alone, the node
it directs the change to next, so the next-step computation routes on it, or the
finished triage it revisits, which the wrapper then resumes. Reading
and resolving are distinct because a run can be denied a call and still end with a
question or a proposed return: its denials are read first, and its outcome is
answered or decided after. This module is the log's only writer.

A run's line may carry `invoked`: each hook, part, and command the run invoked
through `run` or the guarded push, with its owed workflow and phase where it has
them, the command it resolved to, its exit status, when it started, and how long it
took. The field is optional, so a line without it reads as before and the record
set's format does not move.

A finished merge's or archive cleanup's outcome carries `landing`, the remote,
branch, and commit the run fetched, which the writer checks against the checkout
the run ran in before the line is written (`landing_problems`), recording on
cleanup's line whether its commit contains the one fetched (`CONTAINED`). A line
written before the record existed has neither, and keeps its meaning.

The log holds only what the change's files cannot: session ids, the owner's round
agreements, and the last outcome. Where the log and the files disagree, the files
win. It lives in the change's untracked `reviews/` directory and moves with the
change when it is archived.

Every line this module appends carries the record set's format (`common.FORMAT`),
which the log is the only authority for. A line with no format, or a lower one, is
older (`older`): its records are converted before anything routes on them. A line
with a higher one is newer (`newer`), written by an engine this one predates, and
nothing here routes on, converts, or appends to such a log (`NewerFormat`). `start`
opens the log with a line of its own before any step it starts runs (`open_log`),
so a change worked through the command has its format marked before any other
record; nothing routes on that line.

A line naming a step, a node, or a kind of review the graph does not declare is
reported by name (`undeclared`): the graph's vocabulary is closed, and a reader
does not guess what a newer one meant.

A log may be replaced whole, a new file renamed over its name (`replace_log`), so
every reader and appender checks, once it holds the lock, that the file it locked
is still the one the name holds.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import timezone
from pathlib import Path
from typing import IO, Any, Callable, Collection, Mapping, Sequence

from .common import CHANGES, FORMAT, ORCHESTRATOR, Clock, Entry, StepError, utc_now
from .find import (ARCHIVE, ChangeNotFound, change_directory, change_name, find_records,
                   landing_branch)
from .graph import (IMPLEMENTATION_TRIAGE, LATE_MERGE, NODES, ROUND, STEPS, Node, Standing,
                    TargetError, entry_refusal, node_of, review_phase, section_ids)
from .index import index_rows
from .outcome import outcome_problems, triage_outcome_problems
from .records import (NUMBERED, git_contains, git_remotes, git_resolve, has_records,
                      latest_validation, next_number, validation_result)

LOG = "workflow.jsonl"
# The lines no step's run writes: the conversion's, and the one `start` opens a
# step with. Neither names an exit, and nothing routes on either.
CONVERSION = "convert"
OPENING = "start"
# The steps whose finished outcome records, as `landing`, the landing branch the
# run fetched: the merge, before closeout and after the archive, and archive cleanup.
MERGE = "merge"
CLEANUP = "archive-cleanup"
# On a finished archive cleanup line carrying `landing`: whether the run's commit
# contains the commit it fetched, decided as the line is written, in the checkout
# that fetched it. Archive cleanup's first exit to `done` reads only this, so no
# later fetch, by anyone, changes where that exit leads.
CONTAINED = "landing_contained"


class LogError(StepError):
    """The workflow log cannot be read."""


class NewerFormat(LogError):
    """The log holds a line of a format this engine does not read."""


def log_path(root: Path, change: str) -> Path:
    try:
        return change_directory(root, change) / "reviews" / LOG
    except ChangeNotFound as exc:
        raise StepError(str(exc)) from exc


def history_log_path(root: Path, change: str) -> Path:
    """The log a report of the change's history reads: wherever its records are.

    A cleaned-up change's records are in its archive directory, in this checkout or,
    from another change's clone, in the owner's workspace; the workspace may also
    hold the change's active directory from a branch, without them, which
    `log_path` would prefer. Only reports read through this; a step's own lines are
    written where `log_path` says, in the checkout working the change.
    """
    try:
        return find_records(root, change) / LOG
    except ChangeNotFound:
        return log_path(root, change)


def _parse(path: Path, text: str) -> list[Entry]:
    entries = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise LogError(f"{path}:{number}: not a JSON line: {exc.msg}") from exc
        if not isinstance(entry, dict):
            raise LogError(f"{path}:{number}: not a JSON object")
        seq = entry.get("seq")
        if not isinstance(seq, int) or isinstance(seq, bool):
            raise LogError(f"{path}:{number}: has no integer seq")
        entries.append(entry)
    return entries


def _locked(path: Path, mode: str, operation: int) -> IO[str] | None:
    """The log opened in `mode` and locked by `operation`; None when there is no log
    to open for reading.

    A lock is held on a file, not on its name: a process that opened the log, then
    waited for its lock while the log was replaced by a rename, would take the lock
    on the replaced file and read or append where no one looks. So once the lock is
    held, the file locked is compared with the file the name holds, and the log is
    opened and locked again until they are one.
    """
    while True:
        try:
            stream = path.open(mode, encoding="utf-8")
        except FileNotFoundError:
            return None
        try:
            fcntl.flock(stream, operation)
            locked = os.fstat(stream.fileno())
            try:
                named = path.stat()
            except FileNotFoundError:
                named = None
        except BaseException:
            stream.close()
            raise
        if named is not None and (named.st_dev, named.st_ino) == (locked.st_dev,
                                                                  locked.st_ino):
            return stream
        stream.close()


def read_log(path: Path) -> list[Entry]:
    """Every line of the workflow log, in order; an absent log is empty.

    A malformed line is reported with its line number, never skipped: a skipped
    line could be the last outcome, and routing on the one before it would repeat
    or skip a step.
    """
    if not path.is_file():
        return []
    # Shared, so a line being appended is never read half-written.
    stream = _locked(path, "r", fcntl.LOCK_SH)
    if stream is None:
        return []
    with stream:
        return _parse(path, stream.read())


def last_entries(path: Path, count: int) -> list[Entry]:
    entries = read_log(path)
    return entries[-count:] if count > 0 else []


def _readable(mark: Any) -> bool:
    """Whether a line's `format` is one this engine reads, current or older: absent,
    or a whole number no higher than its own."""
    return mark is None or (isinstance(mark, int) and not isinstance(mark, bool)
                            and mark <= FORMAT)


def older(entries: Sequence[Entry]) -> Entry | None:
    """The first line of an older format: with no `format`, or a lower one, as a
    writer before this format appended it; None when there is none."""
    return next((entry for entry in entries if _readable(entry.get("format"))
                 and entry.get("format") != FORMAT), None)


def newer(entries: Sequence[Entry]) -> Entry | None:
    """The first line of a format this engine does not read: a higher one, which a
    later engine appended, or a mark that is no format number; None when there is
    none. Such a line is refused rather than read or converted backwards."""
    return next((entry for entry in entries if not _readable(entry.get("format"))), None)


def refuse_newer(where: Path | str, entries: Sequence[Entry]) -> None:
    """Refuse the log `where` names, whose lines are `entries`, when one is newer,
    naming its format."""
    if (line := newer(entries)) is not None:
        raise NewerFormat(f"{where} holds a line of format {line.get('format')!r} at seq "
                          f"{line['seq']}, which this engine, reading format {FORMAT}, does "
                          "not read: run the engine that wrote it")


def undeclared(entry: Entry) -> str | None:
    """Why `entry` names something the graph does not declare — a step no node runs,
    a kind of review no node is, an exit or a direction naming no node — or None
    when every name it carries is declared. Read at the graph's own declaration, so
    a step, node, or kind added to it is known with nothing else edited."""
    step = entry.get("step")
    if step == ORCHESTRATOR:
        target = entry.get("next") if entry.get("by") == "owner" else None
        what = "the owner's direction"
    elif step in (CONVERSION, OPENING):
        return None
    elif step not in STEPS:
        return f"{step!r} is no step of the workflow graph"
    else:
        kind = entry.get("kind")
        if step == "review" and not (isinstance(kind, str) and review_phase(kind)):
            return f"{kind!r} is no kind of review the workflow graph declares"
        target = entry.get("next") if entry.get("outcome") in ("finished", "returned") \
            else None
        what = f"the {step} run's exit"
    if not isinstance(target, Mapping):
        return None
    try:
        node_of(target)
    except TargetError as exc:
        return f"{what} names no node: {exc}"
    return None


def _refuse_reserved(entry: Entry) -> None:
    if reserved := {"seq", "at", "format"} & entry.keys():
        raise StepError(f"a log line may not set {', '.join(sorted(reserved))}, which "
                        "the log assigns")


def numbered(entries: Sequence[Entry], entry: Entry, clock: Clock = utc_now) -> Entry:
    """`entry` as the line that follows `entries`: the next `seq`, the time, and the
    log's format, which no writer sets itself."""
    _refuse_reserved(entry)
    return {"seq": max((e["seq"] for e in entries), default=0) + 1,
            "at": clock().astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "format": FORMAT, **entry}


def _locked_for_writing(path: Path) -> IO[str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Opened to append, so a log that does not exist yet is created; only a
    # directory that has gone since cannot be opened.
    stream = _locked(path, "a+", fcntl.LOCK_EX)
    if stream is None:
        raise StepError(f"{path.parent} is gone; the change was moved while its log was "
                        "written")
    return stream


def append_entry(path: Path, entry: Entry, clock: Clock = utc_now) -> Entry:
    """Append `entry` to the log with the next `seq`, the time, and the log's format,
    and return the line.

    Several processes may append to one change's log at once, so the log is
    locked from reading the last `seq` to writing the new line; without the lock
    both could take the same number. A log holding a newer line is refused, since a
    line of this format after it would mix two formats in one record set.
    """
    _refuse_reserved(entry)
    with _locked_for_writing(path) as stream:
        stream.seek(0)
        text = stream.read()
        entries = _parse(path, text)
        refuse_newer(path, entries)
        line = numbered(entries, entry, clock)
        stream.seek(0, 2)
        # A last line saved without its newline would otherwise be joined to this one.
        separator = "\n" if text and not text.endswith("\n") else ""
        stream.write(separator + json.dumps(line, ensure_ascii=False) + "\n")
        stream.flush()
    return line


def replace_log(path: Path, rewrite: Callable[[list[Entry]], list[Entry]], *,
                replace: Callable[[Path, Path], Any] = os.replace) -> list[Entry]:
    """Replace the log whole with what `rewrite` makes of its lines, and return the
    lines written; a log that does not exist yet is created.

    The log's lock is held from the read until the new log has been written to a
    file beside it and renamed over its name, so no line is appended in between,
    and a replacement that fails leaves either the log as it was or the new one
    whole, never part of either; a process killed before the rename may leave its
    temporary file, a dotfile beside the log that nothing reads. A refusal `rewrite`
    raises writes no log. Nothing `rewrite` calls may read the log by its name:
    that read would wait on the lock held here.
    """
    existed = path.exists()
    with _locked_for_writing(path) as stream:
        try:
            stream.seek(0)
            lines = rewrite(_parse(path, stream.read()))
            _write_over(path, lines, os.fstat(stream.fileno()).st_mode & 0o777, replace)
        except BaseException:
            # A log the lock's opening created is removed again while the name
            # still holds it, empty, so nothing is left of a replacement that did
            # not happen; once the rename has happened the name holds the new log,
            # which is kept. An appender that opened the created log meanwhile
            # finds its name gone once it holds the lock, and opens the log again.
            locked = os.fstat(stream.fileno())
            try:
                named = path.stat()
            except FileNotFoundError:
                named = None
            if not existed and locked.st_size == 0 and named is not None and (
                    named.st_dev, named.st_ino) == (locked.st_dev, locked.st_ino):
                path.unlink()
            raise
    return lines


def _write_over(path: Path, lines: Sequence[Entry], mode: int,
                replace: Callable[[Path, Path], Any]) -> None:
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp",
                                        dir=path.parent)
    written = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as new:
            # The new log keeps the old one's permissions, not the private ones a
            # temporary file is created with.
            os.fchmod(new.fileno(), mode)
            new.writelines(json.dumps(line, ensure_ascii=False) + "\n" for line in lines)
            new.flush()
            os.fsync(new.fileno())
        replace(written, path)
    finally:
        # Gone once renamed; left only by a replacement that did not happen.
        written.unlink(missing_ok=True)


@dataclass(frozen=True)
class Checkout:
    """What the log's writer reads of the checkout a run ran in, to check the landing
    record on a merge's or archive cleanup's line: the remotes it names, whether one
    commit contains another (`contains(commit, ancestor)`), the branch the change's
    clone recorded as the one it lands on, and the commit a full ref name names
    (`resolve(ref)`, None for none)."""

    remotes: Callable[[], Collection[str]]
    contains: Callable[[str, str], bool]
    base: Callable[[], str | None]
    resolve: Callable[[str], str | None]


def git_checkout(root: Path, change: str) -> Checkout:
    """The checkout at `root`, read through Git, for `change`."""
    return Checkout(remotes=lambda: git_remotes(root),
                    contains=lambda commit, ancestor: git_contains(root, commit, ancestor),
                    base=lambda: landing_branch(root, change),
                    resolve=lambda ref: git_resolve(root, ref))


def landing_ref(remote: str, branch: str) -> str:
    """The ref a fetch of `branch` from `remote` leaves the fetched commit at: the
    remote-tracking branch, or, for `.`, the branch the checkout holds itself."""
    return f"refs/heads/{branch}" if remote == "." else f"refs/remotes/{remote}/{branch}"


def _finished_merges(entries: Sequence[Entry]) -> list[Entry]:
    return [entry for entry in entries
            if entry.get("step") == MERGE and entry.get("outcome") == "finished"]


def recorded_landing(entries: Sequence[Entry]) -> Mapping[str, Any] | None:
    """The `landing` the last finished merge recorded; None when no finished merge
    recorded one, as in a log written before the record existed."""
    return next((entry["landing"] for entry in reversed(_finished_merges(entries))
                 if isinstance(entry.get("landing"), Mapping)), None)


def landing_source(entries: Sequence[Entry],
                   base: Callable[[], str | None]) -> tuple[str | None, str] | None:
    """The remote and branch archive cleanup fetches: those the last finished merge
    recorded, else the branch the change's clone recorded, with no remote, which
    cleanup chooses as the merge would; None with neither, for an older log's merge
    of a change worked in place."""
    if (landing := recorded_landing(entries)) is not None:
        return landing["remote"], landing["branch"]
    recorded = base()
    return (None, recorded) if recorded else None


def _repairs_unrecorded(entries: Sequence[Entry], reviews: Path) -> bool:
    """Whether a finished merge may omit `landing`: a repair of a failed validation of
    the merged `HEAD`, the change's latest validation failed, where no finished merge
    before it recorded one, so the repair has none to carry. Never once archive
    cleanup ran: the merge after the archive records one, and a repair carries it, so
    a merge after cleanup without one is only an older line (`unrouted_merge`)."""
    merges = _finished_merges(entries)
    if not merges or any(isinstance(entry.get("landing"), Mapping) for entry in merges) \
            or any(entry.get("step") == CLEANUP for entry in entries):
        return False
    record = latest_validation(reviews)
    return record is not None and validation_result(record) == "failed"


def landing_problems(entries: Sequence[Entry], step: str, outcome: Entry, commit: str | None,
                     checkout: Checkout, reviews: Path) -> list[str]:
    """Why the log's writer refuses the landing record of `step`'s outcome, a run whose
    commit is `commit`, to follow `entries`; empty when it does not, or when nothing
    is required of it.

    Only a finished merge or archive cleanup is checked: a merge that asks at a
    conflict holds the fetched commit in `MERGE_HEAD`, not `HEAD`, and one that
    stops before its fetch has none. A merge's record names one of the checkout's
    remotes, or `.` for a branch the checkout holds, and a commit `HEAD` contains,
    which shows the merge brought it in; a repair of a merge logged before the
    record existed may omit it (`_repairs_unrecorded`). Archive cleanup records
    one whenever a source resolves (`landing_source`), on every run, so a fetch that
    failed never passes for a check, and it must be what cleanup fetched from that
    source (`_cleanup_landing_problems`); whether `HEAD` contains it is recorded, not
    refused (`CONTAINED`).
    """
    if step not in (MERGE, CLEANUP) or outcome.get("outcome") != "finished":
        return []
    landing = outcome.get("landing")
    if not isinstance(landing, Mapping):
        if step == MERGE:
            return [] if _repairs_unrecorded(entries, reviews) else [
                "its finished outcome records no landing, the remote, branch, and commit it "
                "fetched, which every finished merge records but a repair of a merge logged "
                "before the record existed"]
        if (source := landing_source(entries, checkout.base)) is None:
            return []
        remote, branch = source
        return [f"its finished outcome records no landing, and it fetches {branch}"
                + (f" from {remote}" if remote else "") + ": a fetch that fails ends it "
                "stopped, never finished"]
    if not commit:
        return ["the run's commit could not be read, so its landing cannot be checked"]
    if step == CLEANUP:
        return _cleanup_landing_problems(landing, landing_source(entries, checkout.base),
                                         checkout)
    problems = []
    if landing["remote"] != "." and landing["remote"] not in checkout.remotes():
        problems.append(f"its landing.remote {landing['remote']!r} is none of the checkout's "
                        "remotes, nor . for a branch the checkout holds")
    if not checkout.contains(commit, landing["commit"]):
        problems.append(f"its landing.commit {landing['commit'][:12]} is not contained in the "
                        f"run's commit {commit[:12]}, so the merge did not bring it in")
    return problems


def _cleanup_landing_problems(landing: Mapping[str, Any], source: tuple[str | None, str] | None,
                              checkout: Checkout) -> list[str]:
    """Why a finished archive cleanup's `landing` is not what it fetched from `source`.

    The first exit's guard trusts the containment recorded from this line, so a line
    naming another branch, or a commit other than the one the fetch left, would let
    a moved landing branch pass for a contained one. The branch is the source's. The
    remote is the source's where that remote is `.` or one of the checkout's; a
    source from the clone's recorded branch names none, and a recorded remote the
    checkout lacks is replaced on the owner's word, so there it is any of the
    checkout's or `.`. The commit is the one the fetch left at the ref for that remote
    and branch, compared for equality: an older commit of the right branch, which
    `HEAD` may well contain, is exactly the record the guard must not accept. A fetch
    in the checkout between cleanup's and this write makes the line refused, and the
    rerun fetches again.
    """
    problems = []
    remote, branch = landing["remote"], landing["branch"]
    if source is not None and branch != source[1]:
        problems.append(f"its landing.branch {branch!r} is not {source[1]!r}, the branch "
                        "cleanup fetches")
    allowed = {".", *checkout.remotes()}
    if source is not None and source[0] in allowed:
        if remote != source[0]:
            problems.append(f"its landing.remote {remote!r} is not {source[0]!r}, the remote "
                            "cleanup fetches from")
    elif remote not in allowed:
        problems.append(f"its landing.remote {remote!r} is none of the checkout's remotes, "
                        "nor . for a branch the checkout holds")
    if not problems:
        ref = landing_ref(remote, branch)
        fetched = checkout.resolve(ref)
        if fetched != landing["commit"]:
            problems.append(f"its landing.commit {landing['commit'][:12]} is not the commit "
                            f"{ref} names, "
                            + (fetched[:12] if fetched else "none")
                            + ", so it is not what the fetch left")
    return problems


def record_outcome(path: Path, step: str, outcome: Entry, *, session: str | None,
                   commit: str | None, extra: Entry | None = None,
                   schema: dict[str, Any] | None = None, checkout: Checkout | None = None,
                   clock: Clock = utc_now) -> Entry:
    """Append a step's outcome, refusing one that does not conform to the schema, or,
    for a finished merge or archive cleanup, whose landing record the `checkout` the
    run ran in refuses (`landing_problems`); a finished archive cleanup line carrying
    one is recorded with whether its commit contains it (`CONTAINED`)."""
    if step not in STEPS:
        raise StepError(f"unknown step {step!r}; expected one of {', '.join(STEPS)}")
    if problems := outcome_problems(outcome, schema):
        raise StepError(f"the {step} outcome does not conform to the schema: "
                        + "; ".join(problems))
    run: Entry = {"step": step, "session": session, "commit": commit}
    if step in (MERGE, CLEANUP) and outcome.get("outcome") == "finished":
        if checkout is None:
            raise StepError(f"a finished {step} run's landing is checked in the checkout it "
                            "ran in, and none was given")
        if problems := landing_problems(read_log(path), step, outcome, commit, checkout,
                                        path.parent):
            raise StepError(f"the {step} outcome is refused: " + "; ".join(problems))
        # A line carrying `landing` has a commit, which `landing_problems` requires.
        if step == CLEANUP and commit and isinstance(landing := outcome.get("landing"),
                                                     Mapping):
            run[CONTAINED] = checkout.contains(commit, landing["commit"])
    if clash := (extra or {}).keys() & (run.keys() | outcome.keys()):
        raise StepError(f"the {step} run's fields {', '.join(sorted(clash))} are recorded "
                        "twice")
    # The schema admits no field beyond the outcome's own, so nothing a step
    # answers can overwrite what is recorded about its run.
    line = {**run, **(extra or {}), **outcome}
    if why := undeclared(line):
        raise StepError(f"the {step} run is refused: {why}")
    return append_entry(path, line, clock)


def record_interactive(path: Path, step: str, outcome: Entry, *, session: str,
                       commit: str | None, invoked: Sequence[Entry] = (),
                       checkout: Checkout | None = None, clock: Clock = utc_now) -> Entry:
    """Append the outcome of a step the owner ran interactively, which records its
    own: checked as the wrapper checks an unattended run's, a finished merge's or
    archive cleanup's landing record against the `checkout` it ran in included, and
    marked `interactive`, with what the session `invoked`, when it invoked anything.

    A triage's finished or returned outcome is refused unless it names the records
    it triaged (`triage_outcome_problems`), as the wrapper records such a run
    stopped: where an unattended run still ends with a line, an interactive one is
    told why and records again. So is an outcome without its session or commit,
    which say which run it ended and what that run left.
    """
    if not session:
        raise StepError("an interactive run's outcome names its session")
    if not commit:
        raise StepError("an interactive run's outcome names the commit at HEAD, which "
                        "could not be read")
    if step == "triage" and (problems := triage_outcome_problems(outcome, path.parent)):
        raise StepError("the triage's outcome does not name what it triaged: "
                        + "; ".join(problems))
    return record_outcome(path, step, outcome, session=session, commit=commit,
                          extra={"interactive": True,
                                 **({"invoked": list(invoked)} if invoked else {})},
                          checkout=checkout, clock=clock)


def open_log(path: Path, change: str, step: str, *, interactive: bool,
             clock: Clock = utc_now) -> Entry:
    """Open `change`'s log at `path` for a run of `step` that `start` is about to start,
    creating it if need be: a line carrying the record set's format, so the format is
    marked before anything the step records — a ledger line, its outcome — and the
    ledger beside the log is read in it. Nothing routes on the line.

    Refused, writing nothing, where the record set is not in this format: a log
    holding a newer line, which this engine does not read; and records of an older
    format — a log holding a line with no format or a lower one, or numbered records
    under `reviews/` with no line logged — which the owner converts first, since this
    line would otherwise mark them as current.
    """
    entries = read_log(path)
    refuse_newer(path, entries)
    if (line := older(entries)) is not None:
        why = f"its workflow log holds a line of an older format at seq {line['seq']}"
    elif not entries and has_records(path.parent):
        why = "it has numbered records under reviews/ and no workflow log"
    else:
        return append_entry(path, {"step": OPENING, "outcome": "opened", "starts": step,
                                   "interactive": interactive}, clock)
    raise StepError(f"{why}, so its records are not in format {FORMAT}: the owner converts "
                    f"them with `scripts/change-workflow convert {change}` before a step "
                    "starts")


def note_round(path: Path, sections: Any, by: str, after: int | None = None,
               clock: Clock = utc_now, commit: str | None = None) -> Entry:
    """Record the implementation round the owner agreed: its sessions, each a list
    of the sections that session implements, in order.

    `after` is the highest number among the records and transcripts in `reviews/`
    before the round, so the round's own records — the owner's notes, its
    validation and review, their triage — are those numbered above it. It is read
    from `reviews/` when the round is agreed before it starts, and given for a
    round recorded after the fact, whose records already exist. `commit` is `HEAD`
    as the round starts, the base its round view shows the round against: commits
    landing between rounds, a design revision among them, are not the round's.

    A round recorded while the latest round is still open — no implementation
    triage has finished or returned since it — over sections that round already
    names continues it: an owner's direction, or a plan amended mid-round, names
    only the sections left, and the round's reading, validation, and review must
    still cover the sections already done. Such a line keeps the open round's
    `after` and `commit` and names it as `continues`.
    """
    if not section_ids(sections):
        raise StepError("a round names one or more sessions, each a non-empty list of "
                        f"sections; got {sections!r}")
    if not by:
        raise StepError("a round names who agreed it")
    if after is not None and (isinstance(after, bool) or not isinstance(after, int)
                              or after < 0):
        raise StepError(f"a round's after is a record number; got {after!r}")
    continued = _open_round(path, sections) if after is None else None
    if continued is not None:
        return append_entry(path, {"step": ORCHESTRATOR, "outcome": "round",
                                   "sections": sections, "by": by,
                                   "after": continued["after"],
                                   **({"commit": continued["commit"]}
                                      if continued.get("commit") else {}),
                                   "continues": continued["seq"]}, clock)
    return append_entry(path, {"step": ORCHESTRATOR, "outcome": "round",
                               "sections": sections, "by": by,
                               "after": next_number(path.parent) - 1 if after is None
                               else after, **({"commit": commit} if commit else {})}, clock)


def _open_round(path: Path, sections: Any) -> Entry | None:
    """The latest round, when it is still open and names every section in
    `sections`; otherwise None."""
    entries = read_log(path) if path.exists() else []
    latest = next((e for e in reversed(entries) if e.get("outcome") == "round"), None)
    if latest is None or not isinstance(latest.get("after"), int):
        return None
    if any(e["seq"] > latest["seq"] and e.get("outcome") in ("finished", "returned")
           and ran(IMPLEMENTATION_TRIAGE, e, entries) for e in entries):
        return None
    named = {str(s) for session in latest.get("sections") or () for s in session}
    wanted = {str(s) for session in sections for s in session}
    return latest if wanted <= named else None


def _row_archived(directory: Path) -> bool:
    """Whether the change index of the repository holding the change `directory` has
    a row for it saying `archived`."""
    archived = directory.parent.as_posix().endswith(ARCHIVE.as_posix())
    root = directory.parents[len(ARCHIVE.parts) if archived else len(CHANGES.parts)]
    name = change_name(directory)
    return any(row.name == name and row.status == "archived" for row in index_rows(root))


def standing(path: Path, entries: Sequence[Entry] | None = None) -> Standing:
    """What the entry guards read of the change whose log is at `path`: whether its
    directory is under the archive, the kinds of review awaiting triage, whether an
    archive cleanup run has finished, and whether its index row says `archived`.

    A review — a numbered record of a review kind, `-external` included — awaits
    triage until a triage's finished or returned outcome, or a conversion line,
    names it in `triaged`; a review whose triage file exists and whose outcome is
    not yet recorded is a triage in progress, and still awaits it. A validation
    record numbered after the latest review, which awaits nothing, is triaged in
    that review's triage too: the validation of the fix commit its triage made,
    whose failures the owner may direct a triage of the same kind to fix, naming
    that review again. A design triage makes no commit a validation reads, so a
    validation after a design review — the first round's — awaits no design triage.
    """
    directory = path.parent.parent
    entries = read_log(path) if entries is None else entries
    triaged = {name for entry in entries
               if (entry.get("step") == "triage"
                   and entry.get("outcome") in ("finished", "returned"))
               or entry.get("step") == CONVERSION
               for name in entry.get("triaged") or () if isinstance(name, str)}
    awaiting = set()
    latest: tuple[int, str] | None = None
    validations = []
    for record in (path.parent.iterdir() if path.parent.is_dir() else ()):
        stem = record.name.removesuffix(".md")
        if not record.name.endswith(".md") or not (number := NUMBERED.match(stem)):
            continue
        kind = stem.split("-", 1)[1].removesuffix("-external")
        review = review_phase(kind) is not None
        if review and (latest is None or int(number[1]) > latest[0]):
            latest = (int(number[1]), kind)
        if stem in triaged:
            continue
        if review:
            awaiting.add(kind)
        elif kind == "validation":
            validations.append(int(number[1]))
    if latest is not None and latest[1] != "design" and any(number > latest[0]
                                                            for number in validations):
        awaiting.add(latest[1])
    return Standing(archived=directory.parent.as_posix().endswith(ARCHIVE.as_posix()),
                    awaiting=frozenset(awaiting),
                    cleaned_up=any(entry.get("step") == CLEANUP
                                   and entry.get("outcome") == "finished" for entry in entries),
                    row_archived=_row_archived(directory))


def direction(next_step: str, kind: str | None = None,
              sections: list[list[int | str]] | None = None,
              target: str | None = None) -> Entry:
    """The target a direction names, built from the command line's flags: `--next`,
    qualified by `--kind` and `--sections`, or, for a validation, `--target`, which
    they qualify instead."""
    qualified: Entry = {"step": target if target is not None else next_step}
    if kind is not None:
        qualified["kind"] = kind
    if sections is not None:
        qualified["sections"] = sections
    if target is None:
        return qualified
    return {"step": next_step, "target": qualified}


def revisit_refusal(entries: Sequence[Entry], seq: int) -> str | None:
    """Why the triage run at `seq` cannot be revisited; None when it can.

    Only a finished triage naming the reviews it triaged is revisited, and only
    while it is the latest triage run of those reviews: a later triage of any of
    them has superseded its outcome, and so has a run that resumed it, which may
    still wait on the owner with a question or a stop before it names them again.
    """
    run = next((entry for entry in entries if entry.get("seq") == seq
                and entry.get("step") in STEPS), None)
    if run is None or run.get("step") != "triage" or run.get("outcome") != "finished":
        what = (f"a {run.get('step')} run that ended {run.get('outcome')}" if run is not None
                else "no run")
        return f"seq {seq} is {what}, not a finished triage, so there is no triage to revisit"
    triaged = {name for name in run.get("triaged") or () if isinstance(name, str)}
    if not triaged:
        return f"the triage at seq {seq} names no review it triaged, so none is revisited"
    later = next((entry for entry in reversed(entries)
                  if entry["seq"] > seq and entry.get("step") == "triage"
                  and (triaged & set(entry.get("triaged") or ())
                       or entry.get("resumes") == seq)), None)
    if later is not None:
        return (f"the triage at seq {later['seq']} came after seq {seq}, "
                + (f"triaging {', '.join(sorted(triaged & set(later['triaged'])))} again"
                   if later.get("triaged") else f"resuming it, and ended {later.get('outcome')}")
                + f"; revisit or answer seq {later['seq']} instead")
    return None


def revisit_direction(entries: Sequence[Entry], seq: int) -> Entry | None:
    """The owner's direction to revisit the triage run at `seq`, while no run has
    resumed it since; None otherwise. A direction is used once."""
    direction_ = next((entry for entry in reversed(entries)
                       if entry.get("outcome") == ORCHESTRATOR and entry.get("by") == "owner"
                       and entry.get("resumes") == seq), None)
    if direction_ is None or any(entry["seq"] > direction_["seq"]
                                 and entry.get("step") in STEPS
                                 and entry.get("resumes") == seq for entry in entries):
        return None
    return direction_


def note_orchestrator(path: Path, decision: str, reason: str, *, by: str = ORCHESTRATOR,
                      resolves: int | None = None, reads: int | None = None,
                      next_step: str | None = None, kind: str | None = None,
                      sections: list[list[int | str]] | None = None,
                      target: str | None = None,
                      branch: str | None = None, change: str | None = None,
                      resumes: int | None = None, clock: Clock = utc_now) -> Entry:
    """Record a decision: the orchestrating session's own routing or recovery, or
    the owner's, relayed by it.

    `reads` names the run (its `seq`) whose recorded denials the decision has
    read against the step's rules; `resolves` names the run the decision
    settles, so that run alone stops waiting on the owner: a decision clears
    nothing it does not name. They differ because a run denied a call can still
    end with a question or a proposed return, whose denials are read before the
    question is answered or the return decided; a reading alone leaves such an
    outcome waiting. A stopped run is read the same way: a reading that also
    resolved it would make `resume` refuse the one-run grant that recovers it,
    so a stop is resolved only when it is not recovered.

    `next_step`, qualified by `kind` and `sections`, or for a validation by
    `target`, the step it is for, which they then qualify (`direction`), is the
    owner's direction, recorded as the line's `next`: a target naming the node of
    the workflow graph the change goes to next, which the next-step computation
    names until a run of it is logged — a confirmed return, which resolves the
    returned run, a repeat review, a waiver of a step's check, any intervention.
    Only the owner
    directs: the orchestrating session neither directs a step of its own accord
    nor records a step's exit for it. A direction checks none of the exit guards a
    step's exit is held to, since the owner made it deliberately, and its `reason`
    says what it skips; it is refused, naming the guard, while an unwaivable entry
    guard of a node it names is not met — its target, and the target nested in a
    direction to validation — since the step could not carry out its work.
    `branch` and `change` record the owner's word that `change` is worked on
    `branch` though the branch is not its own, which each step's branch check
    accepts in place of asking (`branch_decisions`); only the owner gives it.
    `resumes` is the owner's direction to revisit a finished triage, naming its
    run, which `Wrapper.resume` then resumes once with the owner's words; it is
    refused unless that run is the latest triage of the reviews it triaged
    (`revisit_refusal`). It routes nothing: the resumed triage's outcome does.
    """
    if next_step is None and (kind, sections, target) != (None, None, None):
        raise StepError("a kind, sections, or target qualify the step a decision directs")
    directed = direction(next_step, kind, sections, target) if next_step is not None else None
    line = decision_line(path, read_log(path), decision, reason, by=by, resolves=resolves,
                         reads=reads, directs=directed, branch=branch, change=change,
                         resumes=resumes)
    return append_entry(path, line, clock)


def decision_line(path: Path, entries: Sequence[Entry], decision: str, reason: str, *,
                  by: str, resolves: int | None = None, reads: int | None = None,
                  directs: Entry | None = None, branch: str | None = None,
                  change: str | None = None, resumes: int | None = None) -> Entry:
    """The decision `note_orchestrator` records, checked against `entries`, the lines
    of the log at `path` it would follow, and not yet numbered: `directs` is the
    target of the owner's direction. A line that breaks a rule raises, naming it."""
    if not decision or not reason:
        raise StepError("an orchestrator line names its decision and its reason")
    if not by:
        raise StepError("an orchestrator line names who decided")
    line: Entry = {"step": ORCHESTRATOR, "outcome": ORCHESTRATOR, "by": by,
                   "decision": decision, "reason": reason}
    if branch is not None or change is not None:
        if not branch or not change:
            raise StepError("a branch decision names both the branch and the change")
        if by != "owner":
            raise StepError("a branch decision is the owner's")
        line.update(branch=branch, change=change)
    runs = {entry["seq"]: entry for entry in entries if entry.get("step") in STEPS}
    if resolves is not None:
        if resolves not in runs:
            raise StepError(f"no run has seq {resolves!r} in the workflow log; a decision "
                            "resolves a step's run")
        line["resolves"] = resolves
    if reads is not None:
        if reads not in runs:
            raise StepError(f"no run has seq {reads!r} in the workflow log; a decision "
                            "reads a step's run")
        if not runs[reads].get("denials"):
            raise StepError(f"the run at seq {reads} recorded no denial; a decision reads "
                            "a run's denials")
        line["reads"] = reads
    if resumes is not None:
        if by != "owner":
            raise StepError("a direction to revisit a triage is the owner's")
        if directs is not None:
            raise StepError("a direction to revisit a triage directs no step: the resumed "
                            "triage names its exit again")
        if refusal := revisit_refusal(entries, resumes):
            raise StepError(f"the revisit is refused: {refusal}")
        line["resumes"] = resumes
    if directs is not None:
        if by != "owner":
            raise StepError("a decision directing a step is the owner's; the orchestrating "
                            "session directs none")
        try:
            refusal = entry_refusal(directs, standing(path, entries), directed=True)
        except TargetError as exc:
            raise StepError(f"the direction names no node: {exc}") from exc
        if refusal:
            raise StepError(f"the direction is refused: {refusal}")
        line["next"] = directs
    return line


def after_cleanup(entry: Entry, entries: Sequence[Entry]) -> bool:
    """Whether an archive cleanup run is logged before `entry` among `entries`: a
    merge run so logged is the merge after the archive, since nothing returns an
    archived change to the phase of the merge before closeout."""
    return any(other.get("step") == CLEANUP and other["seq"] < entry["seq"]
               for other in entries)


def unrouted_merge(entry: Entry, entries: Sequence[Entry]) -> bool:
    """Whether `entry` is a merge run by hand on an archived change before the merge
    after the archive was a node: a finished merge after an archive cleanup run that
    records no `landing`, where no finished merge before it recorded one. Every
    finished merge since records `landing`, and a repair may omit it only before
    archive cleanup (`_repairs_unrecorded`), so only an older line has this shape;
    it is a run of neither
    merge node, and routes nothing, since the exit it named, often `done`, is one
    neither declares."""
    if entry.get("step") != MERGE or entry.get("outcome") != "finished" \
            or isinstance(entry.get("landing"), Mapping) or not after_cleanup(entry, entries):
        return False
    return not any(isinstance(other.get("landing"), Mapping)
                   for other in _finished_merges(entries) if other["seq"] < entry["seq"])


def ran(node: Node, entry: Entry, entries: Sequence[Entry]) -> bool:
    """Whether `entry`, a line of the log whose lines are `entries`, is a run of
    `node`: a review of its kind; a triage naming a review of its kind among the
    records it triaged; for the round, the line recording it starting, or an
    implementation session; for the merge before closeout or after the archive, a
    merge run before or after an archive cleanup run (`after_cleanup`), but an older
    merge after it that neither node ran (`unrouted_merge`)."""
    if node == ROUND and entry.get("outcome") == "round":
        return True
    if entry.get("step") != NODES[node].runs:
        return False
    if NODES[node].runs == MERGE:
        return not unrouted_merge(entry, entries) \
            and (node == LATE_MERGE) == after_cleanup(entry, entries)
    if node.step == "review":
        return entry.get("kind") == node.kind
    if node.step == "triage":
        return any(isinstance(name, str) and name.split("-", 1)[-1].removesuffix(
            "-external") == node.kind for name in entry.get("triaged") or ())
    return True


def unused_direction(entries: Sequence[Entry]) -> Entry | None:
    """The owner's latest direction, while no run of the node it directs has taken
    an exit after it; None once one has, or when the owner has directed nothing.

    A run that ended with a question, a block, or a stop took no exit: its step is
    still the one directed, and is named again once the owner answers or resolves
    it, so the direction stands for it as for the run that finishes it.
    """
    direction_ = next((entry for entry in reversed(entries)
                       if entry.get("outcome") == ORCHESTRATOR and entry.get("by") == "owner"
                       and isinstance(entry.get("next"), dict)), None)
    if direction_ is None:
        return None
    try:
        node = node_of(direction_["next"])
    except TargetError:
        return None
    return None if any(entry["seq"] > direction_["seq"] and ran(node, entry, entries)
                       and entry.get("outcome") in ("finished", "returned", "round")
                       for entry in entries) else direction_


def branch_decisions(entries: Sequence[Entry], branch: str,
                     change: str | None = None) -> list[Entry]:
    """The owner's decisions that a change is worked on `branch`, and of `change`
    when one is named."""
    return [entry for entry in entries
            if entry.get("outcome") == ORCHESTRATOR and entry.get("by") == "owner"
            and entry.get("branch") == branch
            and (change is None or entry.get("change") == change)]


def last_run(path: Path, steps: Sequence[str]) -> Entry | None:
    """The latest log line of one of `steps`, whether or not it names a session.

    A run that crashed before Claude Code reported its session names none; the
    session before it is not the one to continue, since it is not the last thing
    the step did.
    """
    for entry in reversed(read_log(path)):
        if entry.get("step") in steps:
            return entry
    return None
