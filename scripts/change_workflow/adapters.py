"""Each harness's adapter, by the harness a model names (CW-t6mb).

The configuration's models name a harness, and a model may appear only for a step
its harness's adapter can run (CW-zq4h). A step's scope takes the paths of the
adapter of the harness that runs it: its state, which the sandbox lets it write, and
its settings files, which it keeps read-only.

Contract: openspec/specs/change-workflow/spec.md, CW-t6mb and CW-zq4h.
"""

from __future__ import annotations

from . import claude_code, codex
from .harness import Adapter

ADAPTERS: dict[str, Adapter] = {adapter.harness: adapter
                                for adapter in (claude_code.ADAPTER, codex.ADAPTER)}
HARNESSES: tuple[str, ...] = tuple(ADAPTERS)
# Every adapter's protected paths, which no repository's writable path may open,
# whichever harness runs the step.
PROTECTED: tuple[str, ...] = tuple(dict.fromkeys(
    path for adapter in ADAPTERS.values() for path in adapter.protected))
