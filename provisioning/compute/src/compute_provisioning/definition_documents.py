"""Definition documents a domain contributes to the service's startup import.

An operator may mount a document declaring a domain's administered resources,
such as VM's relays. The service imports every contributed document kind at
startup, before its own pool and capacity documents, because pool
configuration may reference what a contributed document declares. Each kind is
imported under the service's digest guard: applied only when the mounted
document differs from the one last reconciled, in one transaction with the
digest, so a restart never reverts administration done since.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DefinitionDocumentContribution:
    """One document kind a domain imports.

    ``kind`` names the recorded digest, so it must stay stable across releases:
    renaming it makes the next startup reapply the document. ``path`` is where
    the operator mounted it, ``None`` when none is configured. ``apply``
    reconciles the document's text in the importer's session, writes there and
    never commits, and returns a one-line summary for the log; raising rolls
    the import back and records no digest.
    """

    kind: str
    label: str
    path: Path | None
    apply: Callable[[Any, str], str]


__all__ = ["DefinitionDocumentContribution"]
