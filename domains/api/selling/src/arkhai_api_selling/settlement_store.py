"""Negotiation-bound settlement evidence and issuance checkpoints, in the domain's own tables.

Evidence moves ``verified -> refunding -> refunded``, and only ``refunding``
returns to ``verified``. Delivery start and refund intent are each one
serialized write, so exactly one decides whether delivery precedes a refund.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from market_core import SettlementEvidence

from arkhai_api_selling.contributions import SellingContributions
from arkhai_api_selling.issuance import delivery

#: Statuses whose verified facts are fixed; only the refund transitions move between them.
_SETTLED = frozenset({"verified", "refunding", "refunded"})
#: Final progress: another status is refused, the same status returns the row.
_TERMINAL_PROGRESS = frozenset({"ready", "failed"})


class SettlementRepository:
    def __init__(self, db_path: str, contributions: SellingContributions) -> None:
        self.db_path = db_path
        self._contributions = contributions
        self._evidence = contributions.table("settlement_evidence")
        self._progress = contributions.table("issuance_progress")

    def store(self, evidence: SettlementEvidence) -> SettlementEvidence:
        delivery(self._contributions, evidence, require_verified=False)
        payload = dict(evidence.evidence)
        digest = payload["agreement_digest"]
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        with sqlite3.connect(self.db_path, timeout=30) as conn:
            conn.execute("BEGIN IMMEDIATE")
            old = conn.execute(
                "SELECT mechanism, agreement_digest, settlement_ref, evidence, status "
                f"FROM {self._evidence} WHERE negotiation_id = ?",
                (evidence.negotiation_id,),
            ).fetchone()
            if old:
                if old[0] != evidence.mechanism or old[1] != digest:
                    raise ValueError("settlement evidence changed accepted Agreement binding")
                if old[2] is not None and old[2] != evidence.settlement_ref:
                    raise ValueError("settlement evidence changed established reference")
                old_payload = json.loads(old[3])
                if old[4] in _SETTLED and (
                    evidence.status != old[4] or old_payload != payload
                ):
                    raise ValueError("verified settlement evidence is immutable")
                if evidence.status in _SETTLED - {"verified"} and old[4] != evidence.status:
                    raise ValueError("refund status changes only through refund transitions")
            elif evidence.status in _SETTLED - {"verified"}:
                raise ValueError("refund status changes only through refund transitions")
            conn.execute(
                f"INSERT INTO {self._evidence} "
                "(negotiation_id, mechanism, agreement_digest, settlement_ref, status, evidence) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(negotiation_id) DO UPDATE SET "
                "settlement_ref=excluded.settlement_ref, status=excluded.status, evidence=excluded.evidence",
                (evidence.negotiation_id, evidence.mechanism, digest, evidence.settlement_ref,
                 evidence.status, encoded),
            )
        return evidence

    def get(self, negotiation_id: str) -> SettlementEvidence | None:
        with sqlite3.connect(self.db_path, timeout=30) as conn:
            row = conn.execute(
                "SELECT mechanism, settlement_ref, status, evidence, agreement_digest "
                f"FROM {self._evidence} WHERE negotiation_id = ?",
                (negotiation_id,),
            ).fetchone()
        if row is None:
            return None
        evidence = SettlementEvidence(negotiation_id, row[0], row[1], row[2], json.loads(row[3]))
        delivery(self._contributions, evidence, require_verified=False)
        if evidence.evidence["agreement_digest"] != row[4]:
            raise ValueError("settlement evidence no longer matches its Agreement binding")
        return evidence

    def progress(self, reference: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.db_path, timeout=30) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                f"SELECT * FROM {self._progress} "
                "WHERE negotiation_id = ? OR public_ref = ?", (reference, reference),
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["public_result"] = json.loads(result["public_result"])
        return result

    def checkpoint(self, negotiation_id: str, *, public_ref: str, status: str,
                   fulfillment_uid: str | None = None, public_result: dict[str, Any] | None = None,
                   credentials_ref: str | None = None, reason: str | None = None) -> dict[str, Any]:
        if status not in {"provisioning", "ready", "failed"}:
            raise ValueError("invalid issuance progress status")
        public = dict(public_result or {})
        if "secret" in public or "tenant_credentials" in public:
            raise ValueError("credentials belong in private results")
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path, timeout=30) as conn:
            conn.execute("BEGIN IMMEDIATE")
            old = conn.execute(
                f"SELECT public_ref, fulfillment_uid, status FROM {self._progress} WHERE negotiation_id = ?",
                (negotiation_id,),
            ).fetchone()
            if old and (old[0] != public_ref or (old[1] and fulfillment_uid and old[1] != fulfillment_uid)):
                raise ValueError("issuance progress changed established identity")
            if old and old[2] in _TERMINAL_PROGRESS:
                if status != old[2]:
                    raise ValueError(f"issuance progress is already {old[2]}")
                terminal = True
            else:
                terminal = False
            if not terminal:
                conn.execute(
                    f"INSERT INTO {self._progress} "
                    "(negotiation_id, public_ref, status, fulfillment_uid, public_result, credentials_ref, reason, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(negotiation_id) DO UPDATE SET "
                    "status=excluded.status, fulfillment_uid=COALESCE(excluded.fulfillment_uid, fulfillment_uid), "
                    "public_result=excluded.public_result, credentials_ref=COALESCE(excluded.credentials_ref, credentials_ref), "
                    "reason=excluded.reason, updated_at=excluded.updated_at",
                    (negotiation_id, public_ref, status, fulfillment_uid,
                     json.dumps(public, sort_keys=True), credentials_ref, reason, now, now),
                )
        return self.progress(negotiation_id)

    def record_refund_intent(self, negotiation_id: str) -> dict[str, Any]:
        """Record refund intent before the reversal is requested.

        Returns the prior evidence status and whether delivery had started. Only
        verified evidence acquires intent; a deal already ``refunding`` or
        ``refunded`` is left as is.
        """
        with sqlite3.connect(self.db_path, timeout=30) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT ev.status, p.delivery_started_at, p.status "
                f"FROM {self._evidence} ev "
                f"LEFT JOIN {self._progress} p ON p.negotiation_id = ev.negotiation_id "
                "WHERE ev.negotiation_id = ?",
                (negotiation_id,),
            ).fetchone()
            if row is None or row[0] not in _SETTLED:
                raise ValueError("refund requires verified settlement evidence")
            if row[0] == "verified":
                conn.execute(
                    f"UPDATE {self._evidence} SET status = 'refunding' "
                    "WHERE negotiation_id = ? AND status = 'verified'",
                    (negotiation_id,),
                )
        return {"status": row[0], "delivery_started": row[1] is not None or row[2] == "ready"}

    def abandon_refund_intent(self, negotiation_id: str, *, prior_status: str) -> None:
        """Restore verified evidence when the reversal proved impossible."""
        if prior_status != "verified":
            return
        with sqlite3.connect(self.db_path, timeout=30) as conn:
            conn.execute(
                f"UPDATE {self._evidence} SET status = 'verified' "
                "WHERE negotiation_id = ? AND status = 'refunding'",
                (negotiation_id,),
            )

    def complete_refund(self, negotiation_id: str) -> None:
        with sqlite3.connect(self.db_path, timeout=30) as conn:
            conn.execute(
                f"UPDATE {self._evidence} SET status = 'refunded' "
                "WHERE negotiation_id = ? AND status = 'refunding'",
                (negotiation_id,),
            )

    def claim_delivery_start(self, negotiation_id: str) -> bool:
        """Claim the right to start delivery, before any external effect.

        Succeeds only while the evidence is verified, including for a delivery
        already under way, so an interrupted delivery resumes under the same grant.
        """
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path, timeout=30) as conn:
            cursor = conn.execute(
                f"UPDATE {self._progress} "
                "SET delivery_started_at = COALESCE(delivery_started_at, ?), updated_at = ? "
                "WHERE negotiation_id = ? AND EXISTS ("
                f"SELECT 1 FROM {self._evidence} ev "
                "WHERE ev.negotiation_id = ? AND ev.status = 'verified')",
                (now, now, negotiation_id, negotiation_id),
            )
        return cursor.rowcount == 1

    def unsettled_negotiations(self, *, mechanism: str, limit: int) -> list[str]:
        """Accepted deals of one mechanism whose settlement or delivery is still open, oldest first.

        The filter runs before the limit, so completed deals never crowd out an open
        one; a malformed Agreement is skipped.
        """
        with sqlite3.connect(self.db_path, timeout=30) as conn:
            rows = conn.execute(
                f"""
                SELECT t.negotiation_id
                FROM negotiation_threads t
                LEFT JOIN {self._evidence} ev ON ev.negotiation_id = t.negotiation_id
                LEFT JOIN {self._progress} p ON p.negotiation_id = t.negotiation_id
                WHERE t.terminal_state = 'success'
                  AND t.agreement_bytes IS NOT NULL
                  AND CASE WHEN json_valid(CAST(t.agreement_bytes AS TEXT))
                      THEN json_extract(CAST(t.agreement_bytes AS TEXT), '$.settlement.mechanism')
                      END = ?
                  AND (
                    ev.negotiation_id IS NULL
                    OR ev.status IN ('pending', 'refunding')
                    OR (ev.status = 'verified' AND (p.negotiation_id IS NULL OR p.status = 'provisioning'))
                  )
                ORDER BY t.created_at ASC, t.negotiation_id ASC
                LIMIT ?
                """,
                (mechanism, limit),
            ).fetchall()
        return [str(row[0]) for row in rows]
