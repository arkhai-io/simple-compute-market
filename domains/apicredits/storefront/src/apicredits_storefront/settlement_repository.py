"""Negotiation-bound source evidence and independent issuance checkpoints."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from market_core import SettlementEvidence
from domains.apicredits.settlement.fulfillment import credit_delivery


class SettlementRepository:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    def store(self, evidence: SettlementEvidence) -> SettlementEvidence:
        credit_delivery(evidence, require_verified=False)
        payload = dict(evidence.evidence)
        digest = payload["agreement_digest"]
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        with sqlite3.connect(self.db_path, timeout=30) as conn:
            conn.execute("BEGIN IMMEDIATE")
            old = conn.execute(
                "SELECT mechanism, agreement_digest, settlement_ref, evidence, status "
                "FROM api_credit_settlement_evidence WHERE negotiation_id = ?",
                (evidence.negotiation_id,),
            ).fetchone()
            if old:
                if old[0] != evidence.mechanism or old[1] != digest:
                    raise ValueError("settlement evidence changed accepted Agreement binding")
                if old[2] is not None and old[2] != evidence.settlement_ref:
                    raise ValueError("settlement evidence changed established reference")
                old_payload = json.loads(old[3])
                if old[4] == "verified" and (
                    evidence.status != "verified" or old_payload != payload
                ):
                    raise ValueError("verified settlement evidence is immutable")
                if old_payload["delivery"] != payload["delivery"]:
                    raise ValueError("settlement evidence changed accepted delivery inputs")
            conn.execute(
                "INSERT INTO api_credit_settlement_evidence "
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
                "FROM api_credit_settlement_evidence WHERE negotiation_id = ?",
                (negotiation_id,),
            ).fetchone()
        if row is None:
            return None
        evidence = SettlementEvidence(negotiation_id, row[0], row[1], row[2], json.loads(row[3]))
        credit_delivery(evidence, require_verified=False)
        if evidence.evidence["agreement_digest"] != row[4]:
            raise ValueError("settlement evidence no longer matches its Agreement binding")
        return evidence

    def progress(self, reference: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.db_path, timeout=30) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM api_credit_issuance_progress "
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
                "SELECT public_ref, fulfillment_uid FROM api_credit_issuance_progress WHERE negotiation_id = ?",
                (negotiation_id,),
            ).fetchone()
            if old and (old[0] != public_ref or (old[1] and fulfillment_uid and old[1] != fulfillment_uid)):
                raise ValueError("issuance progress changed established identity")
            conn.execute(
                "INSERT INTO api_credit_issuance_progress "
                "(negotiation_id, public_ref, status, fulfillment_uid, public_result, credentials_ref, reason, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(negotiation_id) DO UPDATE SET "
                "status=excluded.status, fulfillment_uid=COALESCE(excluded.fulfillment_uid, fulfillment_uid), "
                "public_result=excluded.public_result, credentials_ref=COALESCE(excluded.credentials_ref, credentials_ref), "
                "reason=excluded.reason, updated_at=excluded.updated_at",
                (negotiation_id, public_ref, status, fulfillment_uid,
                 json.dumps(public, sort_keys=True), credentials_ref, reason, now, now),
            )
        return self.progress(negotiation_id)
