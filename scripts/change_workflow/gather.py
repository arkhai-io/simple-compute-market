"""Gathering the evidence a change's commit lacks: `scripts/change-workflow gather
<change>`.

The gathering runs the preflight, pushes `HEAD` through the guarded push, starts
every missing `start` kind — an owed kind once for each argument owed — runs the
missing `run` kinds in declaration order, which keeps each `after`, then collects
each started kind. What `evidence` reports present is never touched, whoever wrote
it: evidence is gathered again only on the skill's word, through `--kind`, never
because another step wrote it or it is old. A failed preflight gathers nothing,
since evidence gathered in an environment the preflight refused would count as
present.

A kind the owner waived is skipped, saying so, unless a merge lapses the waiver,
which is mechanical (`merge_lapse`): a merge among the commits since the kind last
ran, read from the latest validation whose run invoked it, or the latest validation
when none did. Its closing line says the waiver lapsed and why. Whether a waiver's
condition still holds is the skill's to judge, and it gathers a lapsed kind with
`--kind <kind> --lapsed`.

`gather <change> --kind <kind> [--owed <argument>]` gathers a new attempt of that
kind whatever is present — of the one owed argument `--owed` names, or of each
argument a complete section owes the kind — which becomes current by path order. A
waived kind is refused without `--lapsed`. Why a new attempt was made is the
skill's to write in the record beside its path; the engine does not police it.

The gathering describes `HEAD`: it refuses a worktree whose tree is not `HEAD`'s,
since evidence gathered there would describe neither the tree `evidence` reads nor
the commit. A kind's commands are given `{tree}`, `HEAD`'s tree, `{commit}`,
`HEAD`'s, `{owed}`, and, in a `collect`, `{after}`: the marker its
`start` printed last, kept for the identity the kind's evidence describes, the
kind, and the argument (`hooks.marker_key`). Each kind ends with its closing line,
naming the kind, its argument, its identity, its result and exit status, and its
evidence as it now stands, the current match or `none`. A failure fails the
gathering's exit status, and every other kind still runs; a start that failed, or
was never made because the push was refused, is not collected. What ran is kept,
as `gather` with its kind, argument, and phase, for the line of the session it ran
in, and the engine's run of the step around it.

Contract: openspec/specs/change-workflow/spec.md, CW-g6th, CW-g4oz, CW-x9bt, CW-e7lm,
CW-p4rs, and CW-q5fy.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from . import evidence, push
from .common import StepError
from .config import COMMIT, OWED, TREE, Configuration, Kind
from .evidence import MISSING, REFUSED, WAIVED, Report
from .find import ChangeNotFound, change_directory
from .hooks import PREFIX, HookError, Hooks, Invoked, marker_key, result
from .log import log_path, read_log

GATHER = "gather"
PREFLIGHT = "preflight"


def merge_lapse(root: Path, change: str, kind: str) -> str | None:
    """Why the owner's waiver of `kind` lapses: a merge among the commits since the
    kind last ran — the commit of the latest validation of `change` whose run invoked
    it, or of the latest validation when none did. None when no validation ran, or
    when none of the commits since is a merge. A commit that cannot be read lapses
    the waiver, since what it would show is unknown."""
    path = log_path(root, change)
    runs = [entry for entry in read_log(path) if entry.get("step") == "validate"
            and entry.get("commit")] if path.exists() else []
    if not runs:
        return None
    ran = [entry for entry in runs
           if any(isinstance(invoked, dict) and invoked.get("kind") == kind
                  for invoked in entry.get("invoked") or ())]
    last = (ran or runs)[-1]["commit"]
    merges = subprocess.run(["git", "rev-list", "--merges", f"{last}..HEAD"], cwd=root,
                            capture_output=True, text=True)
    if merges.returncode != 0:
        return f"the commit {kind} last ran at, {last[:12]}, cannot be read"
    if not merges.stdout.strip():
        return None
    merge = merges.stdout.split()[0]
    return f"the merge {merge[:12]} since {kind} last ran, at {last[:12]}"


@dataclass
class Attempt:
    """One kind's attempt in a gathering: the kind, its argument, why a waived kind
    is gathered, what it has run so far, and why a phase of it was refused."""

    kind: Kind
    owed: str | None = None
    lapsed: str | None = None
    ran: list[Invoked] = field(default_factory=list)
    refusal: str | None = None

    @property
    def name(self) -> str:
        return " ".join([GATHER, self.kind.name, *([self.owed] if self.owed else [])])

    @property
    def failed(self) -> bool:
        return self.refusal is not None or any(invoked.failed for invoked in self.ran)

    def closing_line(self, identity: str, current: str | None) -> str:
        """The line the attempt ends with: its name, the identity its evidence
        describes, its result, and its evidence as it now stands, or `none`."""
        shown = (f"failed, exit 1: {self.refusal}"
                 if self.refusal is not None and not any(i.failed for i in self.ran)
                 else result(self.ran))
        lapsed = f"; the owner's waiver lapsed: {self.lapsed}" if self.lapsed else ""
        return (f"{PREFIX} {self.name} at {identity}: {shown}{lapsed}; evidence "
                f"{current or 'none'}")


@dataclass
class Gathering:
    """Gathers a change's evidence through the hook runner, its push, its report of
    what is present, and its reading of a lapse each injected."""

    hooks: Hooks
    change: str
    base: str | None
    # The guarded push of `HEAD`, and its exit status.
    push: Callable[[], int]
    # What `evidence` reports for `HEAD`.
    report: Callable[[], Report]
    # Why the owner's waiver of a kind lapses, or None.
    lapse: Callable[[str], str | None]

    @property
    def configuration(self) -> Configuration:
        return self.hooks.configuration

    def missing(self) -> bool:
        """`gather <change>`: every kind and owed argument missing and not waived, or
        waived and lapsed; whether everything it ran passed."""
        self.hooks.allow(GATHER)
        shown = self._head()
        if not self._preflight():
            return False
        passed = True
        kinds = {kind.name: kind for kind in self.configuration.kinds or ()}
        attempts: list[Attempt] = []
        for entry in shown.entries:
            if entry["status"] == REFUSED:
                self.hooks.echo(f"{PREFIX} {GATHER} {evidence.label(entry)}: refused, "
                                f"{entry['refusal']}")
                passed = False
            elif entry["status"] == MISSING:
                attempts.append(Attempt(kinds[entry["kind"]], entry["owed"]))
            elif entry["status"] == WAIVED:
                waiver = entry["waived"]
                lapse = self.lapse(entry["kind"])
                if lapse is None:
                    self.hooks.echo(f"{PREFIX} {GATHER} {evidence.label(entry)}: skipped, "
                                    f"waived by the owner at seq {waiver['seq']}")
                elif entry["matches"]:
                    self.hooks.echo(f"{PREFIX} {GATHER} {evidence.label(entry)}: skipped, "
                                    f"present; the owner's waiver at seq {waiver['seq']} "
                                    f"lapsed: {lapse}")
                else:
                    attempts.append(Attempt(kinds[entry["kind"]], entry["owed"], lapse))
        return self._gather(attempts, shown) and passed

    def again(self, name: str, owed: str | None = None, lapsed: bool = False) -> bool:
        """`gather <change> --kind <kind> [--owed <argument>] [--lapsed]`: a new attempt
        of the kind whatever is present, of the argument given or each owed; whether
        everything it ran passed. A waived kind is refused without `lapsed`."""
        self.hooks.allow(GATHER)
        kind = self.configuration.kind(name)
        shown = self._head()
        entries = [entry for entry in shown.entries
                   if entry["kind"] == name and entry["status"] != REFUSED]
        waived = next((entry["waived"] for entry in entries if entry["status"] == WAIVED), None)
        if waived is not None and not lapsed:
            raise HookError(f"{name} is waived by the owner's decision at seq {waived['seq']}: "
                            f"{waived['decision']}; gather it with --lapsed once its "
                            "waiver has lapsed")
        if lapsed and waived is None:
            raise HookError(f"--lapsed gathers a waived kind, and no owner's decision waives "
                            f"{name}")
        if not kind.owed:
            if owed is not None:
                raise HookError(f"{name} is not owed, so it takes no --owed")
            arguments: list[str | None] = [None]
        else:
            owing = [entry["owed"] for entry in entries if entry["owed"]]
            if owed is not None and owed not in owing:
                raise HookError(f"no complete section owes {name} {owed}; owed: "
                                + (", ".join(owing) or "none"))
            arguments = [owed] if owed is not None else list(owing)
            if not arguments:
                raise HookError(f"no complete section owes {name}, so there is nothing of it "
                                "to gather")
        if not self._preflight():
            return False
        why = "gathered with --lapsed" if lapsed else None
        return self._gather([Attempt(kind, argument, why) for argument in arguments], shown)

    def _head(self) -> Report:
        """What `evidence` reports for `HEAD`, refused when the worktree's tree is not
        `HEAD`'s."""
        shown = self.report()
        if (tree := self.hooks.tree(self.hooks.root)) != shown.tree:
            raise HookError(f"the worktree's tree, {tree}, is not HEAD's, {shown.tree}: "
                            "evidence gathered here would describe neither HEAD's tree nor "
                            "its commit, so commit or remove the changes first")
        return shown

    def _preflight(self) -> bool:
        """The preflight; whether it passed, a failure gathering nothing."""
        passed = self._run_preflight()
        if not passed:
            self.hooks.echo(f"{PREFIX} {GATHER}: nothing gathered, since the preflight failed")
        return passed

    def _run_preflight(self) -> bool:
        commands = self.configuration.preflight
        name = f"{GATHER} {PREFLIGHT}"
        if commands is None:
            return self.hooks.finish(name, self.hooks.skip(GATHER, "not declared",
                                                           phase=PREFLIGHT))
        values = self.hooks.values(self.change, self.base)
        try:
            self.hooks.needs(commands, values, "validation.preflight")
        except StepError as exc:
            self.hooks.echo(f"{PREFIX} {name}: refused, {exc}")
            return False
        return self.hooks.finish(name, self.hooks.run_commands(GATHER, commands, values,
                                                               phase=PREFLIGHT))

    def _gather(self, attempts: Sequence[Attempt], shown: Report) -> bool:
        """Every attempt's `start`, after the push, then every `run` in order, then
        every started attempt's `collect`."""
        starts = [attempt for attempt in attempts if attempt.kind.start is not None]
        runs = [attempt for attempt in attempts if attempt.kind.run is not None]
        identities = {TREE: shown.tree, COMMIT: shown.commit}
        pushed = True
        if starts:
            status = self.push()
            pushed = status == 0
            self.hooks.echo(f"{PREFIX} {GATHER} push at {shown.commit}: "
                            + ("passed, exit 0" if pushed else f"failed, exit {status}"))
        started: list[Attempt] = []
        for attempt in starts:
            if not pushed:
                attempt.refusal = (f"the guarded push of {shown.commit} failed, so nothing "
                                   "is dispatched for it")
                self._close(attempt, identities)
                continue
            if self._phase(attempt, "start", identities):
                started.append(attempt)
            else:
                self._close(attempt, identities)
        for attempt in runs:
            self._phase(attempt, "run", identities)
            self._close(attempt, identities)
        for attempt in started:
            self._phase(attempt, "collect", identities)
            self._close(attempt, identities)
        return not any(attempt.failed for attempt in attempts)

    def _phase(self, attempt: Attempt, phase: str, identities: Mapping[str, str]) -> bool:
        """Run one phase of an attempt; whether it passed. A refusal — a value the run
        lacks, a collect with no marker kept — fails the attempt as an exit 1."""
        kind = attempt.kind
        identity = identities[kind.identity]
        key = marker_key(identity, kind.name, attempt.owed)
        values = self.hooks.values(self.change, self.base, **identities,
                                   **({OWED: attempt.owed} if attempt.owed else {}))
        labels: dict[str, Any] = {"kind": kind.name, "owed": attempt.owed, "phase": phase,
                                  **({"lapsed": attempt.lapsed} if attempt.lapsed else {})}
        commands = getattr(kind, phase) or ()
        try:
            if phase == "collect":
                after = self.hooks.kept_marker(self.change, key)
                if after is None:
                    raise HookError(f"no start of {kind.name}"
                                    f"{f' for {attempt.owed}' if attempt.owed else ''} at "
                                    f"{identity} has kept a marker")
                values["after"] = after
            self.hooks.needs(commands, values, f"validation.evidence.{kind.name}.{phase}")
        except StepError as exc:
            attempt.refusal = f"its {phase} was refused: {exc}"
            return False
        if phase == "start":
            ran, marker = self.hooks.start(GATHER, commands, values, labels)
            self.hooks.keep_marker(self.change, key,
                                   marker if not any(i.failed for i in ran) else None)
        else:
            ran = self.hooks.run_commands(GATHER, commands, values, **labels)
        attempt.ran += ran
        return not any(invoked.failed for invoked in ran)

    def _close(self, attempt: Attempt, identities: Mapping[str, str]) -> None:
        """The attempt's closing line, naming its evidence as it now stands."""
        kind = attempt.kind
        pattern = evidence.filled(kind.evidence, {**identities, OWED: attempt.owed or "*"})
        found = evidence.matches(self.hooks.root, pattern)
        self.hooks.echo(attempt.closing_line(f"{kind.identity} {identities[kind.identity]}",
                                             found[-1] if found else None))


def main(change: str, *, root: Path, configuration: Configuration,
         environ: Mapping[str, str], base: str | None = None, kind: str | None = None,
         owed: str | None = None, lapsed: bool = False,
         gathering: Gathering | None = None) -> int:
    """`gather <change> [--kind <kind> [--owed <argument>] [--lapsed]]`: 0 when
    everything it ran passed, 1 when anything failed or it was refused, its reason on
    standard error. What ran is kept for the session's line, however it ended."""
    runner = gathering or Gathering(
        Hooks(root, configuration, environ), change, base,
        push=lambda: push.main(["push"], root=root, environ=environ),
        report=lambda: evidence.change_report(root, change, configuration),
        lapse=lambda kind: merge_lapse(root, change, kind))
    try:
        change_directory(root, change)
        passed = (runner.again(kind, owed, lapsed) if kind is not None
                  else runner.missing())
    except (ChangeNotFound, StepError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        runner.hooks.keep(change)
    return 0 if passed else 1
