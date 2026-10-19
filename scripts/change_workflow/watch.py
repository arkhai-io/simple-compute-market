"""Following a change's steps as they run, and reading a run's denials.

`watch` follows the progress file of the step running now, moving to each new
step's as it starts. `denial_report` lists each denial on a run's line with the
tool calls the run made after it, for the orchestrating session's reading of a
denial: whether a later call did the denied call's work by another means.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from change_workflow.common import Entry, StepError
from change_workflow.records import TRANSCRIPTS
from change_workflow.stream import call_summary, tool_summary


def newest_progress(reviews: Path) -> Path | None:
    """The progress file a step of the change wrote to last, if any."""
    files = list((reviews / TRANSCRIPTS).glob("*.progress"))
    return max(files, key=lambda f: f.stat().st_mtime_ns) if files else None


def watch(locate: Callable[[], Path], echo: Callable[[str], None] = print,
          sleep: Callable[[float], None] = time.sleep, polls: int | None = None,
          backlog: int = 10) -> None:
    """Follow the change's newest progress file, moving to each newer one as a step starts.

    `locate` names the change's reviews directory, and is asked again on every
    poll: closeout archives the change while its run is still writing, and the
    run's files move with the directory, so the file being followed is followed
    where it now is, from the line shown last. The file being followed when
    watching begins shows only its last `backlog` lines; a file that appears later
    is shown from its start, since it is a new run. `polls` bounds the loop for
    tests; the command runs until interrupted.
    """
    current: Path | None = None
    shown = 0
    polled = 0
    while polls is None or polled < polls:
        polled += 1
        reviews = locate()
        if current is not None and current.parent != reviews / TRANSCRIPTS:
            current = reviews / TRANSCRIPTS / current.name
        newest = newest_progress(reviews)
        if newest is not None and newest != current:
            lines = newest.read_text("utf-8").splitlines()
            shown = max(len(lines) - backlog, 0) if current is None else 0
            current = newest
            echo(f"== {newest.name}")
        if current is not None:
            lines = current.read_text("utf-8").splitlines()
            for line in lines[shown:]:
                echo(line)
            shown = len(lines)
        sleep(1.0)


def denial_report(reviews: Path, entry: Entry) -> list[str]:
    """Each denial on a run's log line, with the tool calls the run made after it.

    Read from the run's transcript, for the orchestrating session's reading of a
    denial: the call as the harness recorded it, the harness's reason, and what
    the run did next, which shows whether a later call did the denied call's work
    by another means. The step's message is never consulted.
    """
    denials = entry.get("denials")
    denials = [d for d in denials if isinstance(d, dict)] if isinstance(denials, list) else []
    if not denials:
        return [f"seq {entry.get('seq')}: the {entry.get('step')} run recorded no denial"]
    transcript = entry.get("transcript")
    if not isinstance(transcript, str) or not transcript:
        raise StepError(f"seq {entry.get('seq')} is a {entry.get('step')} line with no "
                        "transcript to read")
    path = reviews / transcript
    if not path.is_file():
        raise StepError(f"seq {entry.get('seq')}'s transcript {transcript} is not in {reviews}")
    calls: list[tuple[Any, str]] = []
    for line in path.read_text("utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("type") != "assistant":
            continue
        message = event.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        for item in content if isinstance(content, list) else []:
            if isinstance(item, dict) and item.get("type") == "tool_use":
                calls.append((item.get("id"),
                              f"{item.get('name', '?')} {tool_summary(item)}".rstrip()))
    shown: list[str] = []
    for denial in denials:
        call = f"{denial.get('tool_name', '?')} {call_summary(denial.get('tool_input'))}".rstrip()
        reason = denial.get("reason")
        shown.append(f"denied: {call} ({reason if reason else 'reason not recorded'})")
        key = denial.get("tool_use_id")
        index = next((i for i, (id_, _) in enumerate(calls) if key is not None and id_ == key),
                     None)
        if index is None:
            shown.append("  the call is not in the transcript; every call of the run:")
            after = calls
        elif not calls[index + 1:]:
            shown.append("  no call after it")
            after = []
        else:
            shown.append("  calls after it:")
            after = calls[index + 1:]
        shown += [f"    {text}" for _, text in after]
    return shown
