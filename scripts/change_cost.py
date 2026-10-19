#!/usr/bin/env python3
"""Report what an OpenSpec change's unattended runs cost, by step and by round.

Reads the `cost` the wrapper records on each run's line of the change's workflow
log: for a Claude run its own dollars, turns, duration, and tokens, and for a
Codex review the tokens it reports. A line's round is the `round` line in force
when it was written; lines before any round are design and planning, and lines
from the first pre-closeout review on are closeout, whatever round was last
recorded. A run whose dollars could not be told from its session's other turns —
a crashed run before it, or turns the wrapper did not run — is marked
`usd_partial`, and its bucket's dollars are shown as a range: without those runs,
and with them. The runs are also totalled as session openings, resumed runs that
missed the prompt cache, and resumed runs that read it, and the misses are listed
with the gap before each, since a resumed session's first turn after its cache
expired rewrites its whole context: the cost of openings, of misses, and of warm
turns can be told apart.

Contract: openspec/specs/change-workflow/spec.md, "Unattended runs record their
cost".
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_change_step import (ORCHESTRATOR, ROOT, STEPS, StepError, log_path,  # noqa: E402
                             read_log)

BEFORE_ROUNDS = "design and planning"
CLOSEOUT = "closeout"
# A run that opened its session, or ran without resuming one; a resumed run whose
# first call missed the prompt cache; one whose first call read it.
OPENINGS, MISSES, WARM = "session openings", "resumed, cache missed", "resumed, cache warm"
TOKENS = ("input", "output", "cache_read", "cache_write")


@dataclass
class Bucket:
    """The summed cost of a group of runs."""

    runs: int = 0
    usd: float = 0.0
    # Dollars of runs whose own share is not known: the upper end of the range.
    usd_partial: float = 0.0
    turns: int = 0
    duration_s: float = 0.0
    tokens: dict[str, int] = field(default_factory=lambda: dict.fromkeys(TOKENS, 0))
    codex_tokens: int = 0

    def add(self, cost: dict[str, Any]) -> None:
        self.runs += 1
        usd = cost.get("usd")
        if isinstance(usd, (int, float)):
            if cost.get("usd_partial"):
                self.usd_partial += usd
            else:
                self.usd += usd
        self.turns += int(cost.get("turns") or 0)
        self.duration_s += float(cost.get("duration_s") or 0)
        for key in TOKENS:
            self.tokens[key] += int(cost.get(key) or 0)
        self.codex_tokens += int(cost.get("tokens") or 0)

    def dollars(self) -> str:
        if self.usd_partial:
            return f"${self.usd:.2f}–${self.usd + self.usd_partial:.2f}"
        return f"${self.usd:.2f}"


def rounds(log: Sequence[dict[str, Any]]) -> list[tuple[dict[str, Any], str]]:
    """Each run's line with the round it belongs to."""
    label = BEFORE_ROUNDS
    number = 0
    closeout = False
    runs = []
    for entry in log:
        if entry.get("step") == ORCHESTRATOR:
            if entry.get("outcome") == "round":
                number += 1
                sessions = "; ".join(",".join(str(s) for s in session)
                                     for session in entry.get("sections", []))
                label = f"round {number} ({sessions})"
            continue
        if entry.get("step") not in STEPS:
            continue
        # A pre-closeout review refused before it ran — for want of a passing
        # validation — leaves implementation where it was.
        if (entry.get("step") == "review" and entry.get("kind") == "pre-closeout"
                and entry.get("outcome") == "finished"):
            closeout = True
        runs.append((entry, CLOSEOUT if closeout else label))
    return runs


def _duration(seconds: float) -> str:
    minutes = int(seconds // 60)
    return f"{minutes // 60}h{minutes % 60:02d}m" if minutes >= 60 else f"{minutes}m"


def _tokens(count: int) -> str:
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count / 1_000:.0f}k"
    return str(count)


def _row(name: str, bucket: Bucket) -> str:
    shown = (f"  {name:<34} runs {bucket.runs:<3} {bucket.dollars():<16} "
             f"turns {bucket.turns:<4} time {_duration(bucket.duration_s):<7} "
             f"in {_tokens(bucket.tokens['input'])} out {_tokens(bucket.tokens['output'])} "
             f"cache read {_tokens(bucket.tokens['cache_read'])} "
             f"write {_tokens(bucket.tokens['cache_write'])}")
    if bucket.codex_tokens:
        shown += f" codex {_tokens(bucket.codex_tokens)}"
    return shown


def report(log: Sequence[dict[str, Any]]) -> list[str]:
    """The cost report's lines for a change's workflow log."""
    by_step: dict[str, Bucket] = {}
    by_round: dict[str, Bucket] = {}
    by_cache = {OPENINGS: Bucket(), MISSES: Bucket(), WARM: Bucket()}
    total = Bucket()
    misses = []
    for entry, label in rounds(log):
        cost = entry.get("cost")
        if not isinstance(cost, dict):
            continue
        cache = entry.get("cache_hit")
        for bucket in (by_step.setdefault(entry["step"], Bucket()),
                       by_round.setdefault(label, Bucket()),
                       by_cache[OPENINGS if cache is None else WARM if cache else MISSES],
                       total):
            bucket.add(cost)
        if cache is False:
            misses.append(entry)
    lines = ["By step:", *(_row(name, bucket) for name, bucket in by_step.items()),
             "By round:", *(_row(name, bucket) for name, bucket in by_round.items()),
             "By cache:", *(_row(name, bucket) for name, bucket in by_cache.items()),
             "Total:", _row("all runs", total), "Cache misses:"]
    for entry in misses:
        cost = entry["cost"]
        gap = entry.get("gap_s")
        usd = cost.get("usd")
        lines.append(f"  seq {entry['seq']:<4} {entry['step']:<16} "
                     f"gap {_duration(gap) if isinstance(gap, (int, float)) else '?':<7} "
                     + (f"${usd:.2f}" if isinstance(usd, (int, float)) else "$?")
                     + (" (partial)" if cost.get("usd_partial") else ""))
    if not misses:
        lines.append("  none recorded")
    return lines


def main(argv: Sequence[str] | None = None, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("change")
    args = parser.parse_args(argv)
    try:
        log = read_log(log_path(root, args.change))
    except StepError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    for line in report(log):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
