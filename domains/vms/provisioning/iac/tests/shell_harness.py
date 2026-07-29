"""Test harness for exercising real bash logic embedded in Ansible tasks.

Ansible task shell blocks are opaque strings from a pure-YAML perspective:
`test_vm_management_contracts.py`'s substring assertions can prove specific
text is present, in order, but cannot prove the shell logic actually does
what it says -- which is exactly how a corrupted `continue` statement
(`continueThen remove all task that ...`, a syntactically-valid command
invoking a nonexistent binary, not a parse error `bash -n` would catch)
shipped undetected. This module extracts real shell content out of a task
file and runs it for real, with the handful of external commands it calls
(``virsh``, ``lspci``, ...) faked via `PATH`-shimmed stub executables --
the same technique as faking an HTTP client, applied to a subprocess
boundary instead.

Reusable across any future shell-logic test in this suite; a second bug of
this class should not need its own extraction/faking code written from
scratch.
"""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


def extract_between(text: str, start_anchor: str, end_anchor: str) -> str:
    """Return the text strictly between the first occurrence of each anchor.

    Anchors are matched literally, not as regexes -- deliberately, so a
    test reads as "the text between these two exact lines" rather than
    needing to reason about pattern-matching semantics. Raises ``ValueError``
    with the anchor text if either is not found, so a renamed task/line
    fails the test with a clear "the anchor moved" message rather than a
    silent empty extraction.
    """
    start = text.find(start_anchor)
    if start == -1:
        raise ValueError(f"start anchor not found: {start_anchor!r}")
    start += len(start_anchor)
    end = text.find(end_anchor, start)
    if end == -1:
        raise ValueError(f"end anchor not found after start: {end_anchor!r}")
    return text[start:end]


@contextmanager
def fake_binaries(scripts: dict[str, str]) -> Iterator[str]:
    """Create a temp directory of fake executables and yield its path.

    ``scripts`` maps a binary name (e.g. ``"virsh"``) to the literal
    ``#!/bin/sh`` script content that should run in its place. Callers
    prepend the yielded directory to ``PATH`` (see :func:`run_bash`) so the
    real script under test calls these instead of the real binaries --
    the script itself is never mocked, only what it shells out to.
    """
    with tempfile.TemporaryDirectory(prefix="shell-harness-bin-") as tmp:
        for name, content in scripts.items():
            path = Path(tmp) / name
            path.write_text(content, encoding="utf-8")
            path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        yield tmp


def run_bash(
    script: str,
    *,
    fake_bin_dir: str | None = None,
    env: dict[str, str] | None = None,
    timeout: float = 10,
) -> subprocess.CompletedProcess:
    """Run ``script`` with the real ``bash``, optionally with faked binaries.

    ``fake_bin_dir`` (from :func:`fake_binaries`) is prepended to ``PATH``
    so fake executables shadow real ones of the same name without needing
    the script itself to know anything was faked.
    """
    run_env = dict(os.environ if env is None else env)
    if fake_bin_dir is not None:
        run_env["PATH"] = f"{fake_bin_dir}:{run_env.get('PATH', '')}"
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env=run_env,
        timeout=timeout,
    )


def assert_bash_syntax_valid(script: str) -> None:
    """Raise with bash's own error text if ``script`` fails to parse.

    This is a cheap first-pass check, not the primary defense: a
    syntactically valid command that simply doesn't exist (exactly the bug
    this harness exists for) parses fine under ``bash -n`` and needs the
    behavioral checks in :func:`run_bash` instead.
    """
    result = subprocess.run(
        ["bash", "-n", "-c", script],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise AssertionError(f"bash -n rejected script:\n{result.stderr}")
