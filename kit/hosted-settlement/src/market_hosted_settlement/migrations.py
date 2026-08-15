"""Hosted-settlement-owned SQLite migration extensions."""

from __future__ import annotations

import json
import sqlite3

from hosted_settlement_client import canonical_json
from market_settlement_runtime import SettlementMigration

HOSTED_SETTLEMENT_FUNDING_MIGRATION_ID = (
    "20260815_005_hosted_settlement_funding_profile"
)
_LEGACY_HOSTED_CARD_RECOVERY = {"legacy_recovery": "hosted-card.v1"}


def _classify_hosted_funding_profiles(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT obligation_ref, obligation, mechanism_params, mechanism_ref "
        "FROM settlement_obligations ORDER BY obligation_ref"
    ).fetchall()
    classified: list[tuple[str, str]] = []
    for obligation_ref, raw_obligation, raw_mechanism_params, mechanism_ref in rows:
        try:
            obligation = json.loads(raw_obligation)
            mechanism_params = json.loads(raw_mechanism_params or "{}")
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"settlement obligation {obligation_ref!r} has invalid JSON"
            ) from exc
        if not isinstance(obligation, dict) or not isinstance(mechanism_params, dict):
            raise ValueError(
                f"settlement obligation {obligation_ref!r} has invalid "
                "materialization state"
            )
        if obligation.get("mechanism") != "fiat.stripe.v1":
            continue
        params = obligation.get("params")
        if not isinstance(params, dict):
            raise ValueError(
                f"hosted settlement obligation {obligation_ref!r} has no exact params"
            )
        legacy_methods = params.get("payment_method_types")
        funding_profile = params.get("funding_profile")
        if legacy_methods is not None and funding_profile is not None:
            raise ValueError(
                f"hosted settlement obligation {obligation_ref!r} mixes legacy "
                "and current funding fields"
            )
        if legacy_methods is not None:
            if not isinstance(mechanism_ref, str) or not mechanism_ref:
                raise ValueError(
                    f"legacy hosted settlement {obligation_ref!r} has no immutable "
                    "mechanism reference"
                )
            if (
                legacy_methods != ["card"]
                or "funding_authorization_ref" in params
                or (
                    mechanism_params
                    and mechanism_params != _LEGACY_HOSTED_CARD_RECOVERY
                )
            ):
                raise ValueError(
                    f"hosted settlement obligation {obligation_ref!r} is ambiguous "
                    "legacy funding"
                )
            classified.append(
                (canonical_json(_LEGACY_HOSTED_CARD_RECOVERY), str(obligation_ref))
            )
            continue
        if funding_profile is None:
            raise ValueError(
                f"hosted settlement obligation {obligation_ref!r} has no funding "
                "classification"
            )
        if mechanism_params:
            accepted_profile = mechanism_params.get("funding_profile")
            authorization_ref = mechanism_params.get("funding_authorization_ref")
            if (
                accepted_profile != funding_profile
                or not isinstance(authorization_ref, str)
                or not authorization_ref
                or set(mechanism_params)
                != {"funding_profile", "funding_authorization_ref"}
            ):
                raise ValueError(
                    f"hosted settlement obligation {obligation_ref!r} has ambiguous "
                    "materialization params"
                )
    conn.executemany(
        "UPDATE settlement_obligations SET mechanism_params=? WHERE obligation_ref=?",
        classified,
    )


HOSTED_SETTLEMENT_MIGRATIONS = (
    SettlementMigration(
        HOSTED_SETTLEMENT_FUNDING_MIGRATION_ID,
        _classify_hosted_funding_profiles,
    ),
)

__all__ = [
    "HOSTED_SETTLEMENT_FUNDING_MIGRATION_ID",
    "HOSTED_SETTLEMENT_MIGRATIONS",
]
