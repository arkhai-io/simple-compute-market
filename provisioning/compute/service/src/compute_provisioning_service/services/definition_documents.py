"""Reconciling mounted definition documents, gated on the document changing.

Import treats its document as authoritative: it overwrites entries that differ
from it and, for pools, disables entries it does not name. Capacity and relay
documents retain the entries they do not name. That authority
belongs to the act of an operator submitting a document. A process start is not
a submission.

The distinction is easy to lose because import is idempotent — but idempotent
with respect to the *document*, not the *database*. Re-running it against state
something else changed reverts that change, because a diff against the document
is exactly what detects it. Applied on every startup, it would undo relay and
pool administration on eviction, drain, and crash recovery: silently, with no
failure and no log line an operator would think to check.

So the digest of the last reconciled document is recorded, and a startup
reconciles only when the mounted document differs from it. The digest is written
in the same transaction as the apply, because a digest committed after an
already-committed apply is indistinguishable at the next startup from one
recorded before a crash.
"""

from __future__ import annotations

import hashlib
from contextlib import nullcontext
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from market_site import (
    CapacityDefinitionProblem,
    CapacityDefinitionsOutcome,
    CapacityLedgerService,
    reconcile_capacity_definitions_in_session,
)

from compute_provisioning_service.db.models import DefinitionDocumentImport
from compute_provisioning_service.services.relay_definitions import (
    import_relay_definitions_in_session,
)

logger = logging.getLogger(__name__)

_CAPACITY = "capacity"
_POOLS = "pools"
_RELAYS = "relays"


class CapacityDefinitionsRejected(ValueError):
    """A capacity-definitions document with problems; nothing was applied."""

    def __init__(self, problems: tuple[CapacityDefinitionProblem, ...]) -> None:
        self.problems = problems
        super().__init__(
            "capacity definitions refused: "
            + "; ".join(f"{p.path}: {p.message}" for p in problems)
        )


def reconcile_capacity_document(
    db: Any, ledger: CapacityLedgerService, yaml_text: str
) -> CapacityDefinitionsOutcome:
    """Reconcile a capacity-definitions document into ``db``'s transaction.

    The caller holds ``ledger.serialized()`` around its transaction and
    commits only a valid outcome it means to apply.
    """
    return reconcile_capacity_definitions_in_session(db, ledger, yaml_text)


@dataclass(frozen=True)
class ImportOutcome:
    kind: str
    reconciled: bool
    detail: str


class DefinitionDocumentImporter:
    """Owns reading, gating, applying, and recording — in that order, once."""

    def __init__(
        self,
        *,
        session_factory: Any,
        settings: Any,
        pool_service: Any,
        relay_service: Any,
        capacity_ledger: CapacityLedgerService | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._pool_service = pool_service
        self._relay_service = relay_service
        self._capacity_ledger = capacity_ledger

    # ------------------------------------------------------------------
    # Entry points
    # ------------------------------------------------------------------

    def import_relay_definitions(self) -> ImportOutcome:
        """Reconcile relays. Relays run before pools, so a pool's reference
        resolves on a first boot from documents."""
        return self._import(
            kind=_RELAYS,
            path=getattr(self._settings, "resolved_relay_definitions_path", None),
            label="Relay-definitions",
            apply=self._apply_relays,
        )

    def import_pool_definitions(self) -> ImportOutcome:
        return self._import(
            kind=_POOLS,
            path=getattr(self._settings, "resolved_pool_definitions_path", None),
            label="Pool-definitions",
            apply=self._apply_pools,
        )

    def import_capacity_definitions(self) -> ImportOutcome:
        """Reconcile capacity declarations. They run after pools, which a
        declaration names, and after host seeding."""
        # The ledger's serialization lock spans the whole import, through the
        # commit that records the digest, so no reservation is admitted
        # between a declaration's checks and its commit.
        guard = (
            self._capacity_ledger.serialized()
            if self._capacity_ledger is not None
            else nullcontext()
        )
        with guard:
            return self._import(
                kind=_CAPACITY,
                path=getattr(self._settings, "resolved_capacity_definitions_path", None),
                label="Capacity-definitions",
                apply=self._apply_capacity,
            )

    # ------------------------------------------------------------------
    # The gate
    # ------------------------------------------------------------------

    def _import(self, *, kind: str, path: Path | None, label: str, apply: Any) -> ImportOutcome:
        if path is None:
            logger.info("%s import: no path configured — skipped", label)
            return ImportOutcome(kind, False, "not configured")

        if not path.exists():
            # A configured path that is not there is a deployment error, not an
            # absence: something intended a document to be mounted here.
            raise FileNotFoundError(f"Configured {label.lower()} file does not exist: {path}")

        yaml_text = path.read_text(encoding="utf-8")
        digest = self.digest_of(yaml_text)

        with self._session_factory() as db, db.begin():
            if self._recorded_digest(db, kind) == digest:
                logger.info(
                    "%s import from %s: unchanged since the last reconciliation — "
                    "not reapplied, so administrative changes are preserved",
                    label,
                    path,
                )
                return ImportOutcome(kind, False, "unchanged")

            detail = apply(db, yaml_text)
            # Same transaction as the apply. A failure above leaves no digest,
            # so the next startup retries rather than treating a half-applied
            # document as done.
            self._record_digest(db, kind, digest)

        logger.info("%s import from %s: %s", label, path, detail)
        return ImportOutcome(kind, True, detail)

    # ------------------------------------------------------------------
    # Appliers
    # ------------------------------------------------------------------

    def _apply_pools(self, db: Any, yaml_text: str) -> str:
        diff = self._pool_service.import_pools_in_session(db, yaml_text)
        return (
            f"created={len(diff.created)} updated={len(diff.updated)} "
            f"disabled={len(diff.disabled)} unchanged={len(diff.unchanged)}"
        )

    def _apply_capacity(self, db: Any, yaml_text: str) -> str:
        if self._capacity_ledger is None:
            raise RuntimeError("capacity definitions need the capacity ledger")
        outcome = reconcile_capacity_document(db, self._capacity_ledger, yaml_text)
        if not outcome.valid:
            # Raising rolls back the apply's transaction, so no entry lands
            # and no digest is recorded: the next startup retries.
            raise CapacityDefinitionsRejected(outcome.problems)
        # No "disabled" count: a declaration the document stops naming is
        # retained, as a relay is.
        diff = outcome.diff
        return (
            f"created={len(diff.created)} updated={len(diff.updated)} "
            f"unchanged={len(diff.unchanged)}"
        )

    def _apply_relays(self, db: Any, yaml_text: str) -> str:
        diff = import_relay_definitions_in_session(
            db,
            yaml_text,
            relay_service=self._relay_service,
            settings=self._settings,
        )
        # No "disabled" count: a relay the document stops naming is retained.
        # Disabling one would break every pool referencing it and every live
        # tunnel on it, which is not what an operator editing an unrelated
        # entry is asking for.
        return (
            f"created={len(diff.created)} updated={len(diff.updated)} "
            f"unchanged={len(diff.unchanged)}"
        )

    # ------------------------------------------------------------------
    # Digest bookkeeping
    # ------------------------------------------------------------------

    @staticmethod
    def digest_of(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _recorded_digest(db: Any, kind: str) -> str | None:
        row = db.get(DefinitionDocumentImport, kind)
        return None if row is None else row.digest

    @staticmethod
    def _record_digest(db: Any, kind: str, digest: str) -> None:
        row = db.get(DefinitionDocumentImport, kind)
        if row is None:
            db.add(DefinitionDocumentImport(document_kind=kind, digest=digest))
        else:
            row.digest = digest
