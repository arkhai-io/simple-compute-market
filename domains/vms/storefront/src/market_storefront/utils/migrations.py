"""VM-domain schema migrations and explicit legacy demand synthesis.

The migration engine plus domain-neutral market-state migrations live in
``core_storefront.sqlite_migrations``.  This module supplies VM-owned
migrations and the legacy converter as an explicit per-database input.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

from arkhai_vms import VmConnectionDetails
from core_storefront.sqlite_migrations import (  # noqa: F401 — re-exported
    LegacyMigrationInputs,
    Migration,
    _add_column_if_missing,
    _column_exists,
    _table_exists,
    apply_schema_migrations,
)

from market_storefront.payment_repository import add_vm_settlement_records

logger = logging.getLogger(__name__)


def _normalize_to_dict(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None
    return None


def synthesize_accepted_escrows_from_demand(
    demand_resource: Any,
) -> list[dict[str, Any]] | None:
    """Build ``accepted_escrows`` from a legacy ERC20 ``demand_resource``."""
    from market_storefront.utils.config import CHAINS

    normalized = _normalize_to_dict(demand_resource)
    if not normalized:
        return None
    token = normalized.get("token")
    if not isinstance(token, dict):
        return None
    contract_address = token.get("contract_address")
    if not isinstance(contract_address, str) or not contract_address:
        return None

    amount = normalized.get("amount")
    if isinstance(amount, bool):
        rate_value: str | None = None
    elif isinstance(amount, int):
        rate_value = str(amount)
    elif isinstance(amount, str):
        stripped = amount.strip()
        rate_value = stripped if stripped.isdigit() else None
    else:
        rate_value = None

    from market_alkahest.alkahest import get_erc20_escrow_obligation_default

    entries: list[dict[str, Any]] = []
    for name, chain in CHAINS.items():
        try:
            escrow_address = get_erc20_escrow_obligation_default(
                name,
                config_path=chain.alkahest_address_config_path,
            )
        except Exception as exc:
            logger.debug(
                "Skipping accepted_escrows synthesis for chain %r: %s", name, exc
            )
            continue
        entries.append(
            {
                "chain_name": name,
                "escrow_address": escrow_address.lower(),
                "literal_fields": {"token": contract_address},
                "rates": [
                    {
                        "field": "amount",
                        "per": "hour",
                        "value": rate_value,
                    }
                ]
                if rate_value is not None
                else [],
            }
        )
    return entries or None


VM_LEGACY_MIGRATION_INPUTS = LegacyMigrationInputs(
    accepted_escrows_synthesizer=synthesize_accepted_escrows_from_demand
)


def _migrate_derived_compute_listing_pool_ids(conn: sqlite3.Connection) -> None:
    """Give each legacy derived listing a pool: its own resource.

    Only a database written before the common listing binding existed has
    ``derived_compute_listings``. The pool membership such a database recorded
    lives in a retired inventory table, which no storefront code reads, so a
    listing without a pool takes its resource as one.
    """
    _add_column_if_missing(conn, "derived_compute_listings", "pool_id", "TEXT")
    if _table_exists(conn, "derived_compute_listings"):
        conn.execute(
            "UPDATE derived_compute_listings SET pool_id = resource_id "
            "WHERE pool_id IS NULL"
        )


def _migrate_escrow_settlement_identity(conn: sqlite3.Connection) -> None:
    """Bind the public escrow row to its exact canonical obligation."""
    _add_column_if_missing(conn, "escrows", "obligation_ref", "TEXT")
    _add_column_if_missing(conn, "escrows", "obligation_index", "INTEGER")
    if _table_exists(conn, "settlement_obligations"):
        ambiguous = conn.execute(
            """
            SELECT e.escrow_uid
            FROM escrows e
            JOIN settlement_obligations o
              ON o.agreement_ref = e.negotiation_id
             AND o.mechanism_ref = e.escrow_uid
            GROUP BY e.escrow_uid
            HAVING COUNT(*) != 1
            LIMIT 1
            """
        ).fetchone()
        if ambiguous is not None:
            raise RuntimeError(
                f"escrow has ambiguous canonical settlement obligations: {ambiguous[0]}"
            )
        conflicting = conn.execute(
            """
            SELECT e.escrow_uid
            FROM escrows e
            JOIN settlement_obligations o
              ON o.agreement_ref = e.negotiation_id
             AND o.mechanism_ref = e.escrow_uid
            WHERE e.obligation_ref IS NOT NULL
              AND (
                e.obligation_ref != o.obligation_ref
                OR e.obligation_index != o.obligation_index
              )
            LIMIT 1
            """
        ).fetchone()
        if conflicting is not None:
            raise RuntimeError(
                "escrow conflicts with canonical settlement obligation: "
                f"{conflicting[0]}"
            )
        conn.execute(
            """
            UPDATE escrows
            SET obligation_ref = (
                  SELECT o.obligation_ref
                  FROM settlement_obligations o
                  WHERE o.agreement_ref = escrows.negotiation_id
                    AND o.mechanism_ref = escrows.escrow_uid
                ),
                obligation_index = (
                  SELECT o.obligation_index
                  FROM settlement_obligations o
                  WHERE o.agreement_ref = escrows.negotiation_id
                    AND o.mechanism_ref = escrows.escrow_uid
                )
            WHERE obligation_ref IS NULL
              AND (
                SELECT COUNT(*)
                FROM settlement_obligations o
                WHERE o.agreement_ref = escrows.negotiation_id
                  AND o.mechanism_ref = escrows.escrow_uid
              ) = 1
            """
        )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_escrows_obligation_ref "
        "ON escrows(obligation_ref) WHERE obligation_ref IS NOT NULL"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_escrows_negotiation_obligation "
        "ON escrows(negotiation_id, obligation_index)"
    )


# The fields a deal's connection details may hold.
_CONNECTION_FIELDS = frozenset({"host", "port", "user", "ready_at", "provisioned_resource_ids"})


def _connection_details(stored: dict[str, Any]) -> dict[str, Any]:
    """An older record's connection details, rewritten to what a delivery holds.

    Only a buyer-facing address is a ``host``. A record that predates
    deliveries names it ``host_ip``, except behind a relay: there the buyer
    connects to the relay's address and the relay's port, and such a record's
    ``host_ip`` is the KVM host's address while its ``ssh_port`` is the relay's
    port, a pair that never granted access. A relayed record therefore takes
    both from its relay record, and omits the host when that record lacks
    either. Later records named only the KVM host's inventory name, so their
    host is omitted. A field the record cannot supply is omitted rather than
    invented.
    """
    frp = stored.get("frp") if isinstance(stored.get("frp"), dict) else {}
    if str(frp.get("enabled")).lower() == "true":
        relay_addr = frp.get("relay_addr")
        relay_port = frp.get("remote_port")
        proven = (
            isinstance(relay_addr, str)
            and relay_addr.strip() not in ("", "N/A")
            and str(relay_port).isdigit()
        )
        host = relay_addr.strip() if proven else None
        port = relay_port if proven else None
    else:
        ansible_result = stored.get("ansible_result")
        host = stored.get("host_ip") or None
        port = stored.get("ssh_port") or (
            ansible_result.get("external_ssh_port")
            if isinstance(ansible_result, dict)
            else None
        )
    candidate: dict[str, Any] = {
        "host": host,
        "port": int(str(port)) if port is not None and str(port).isdigit() else None,
        "user": stored.get("tenant_user") or None,
        "ready_at": stored.get("timestamp") or None,
        "provisioned_resource_ids": stored.get("provisioned_resource_ids") or [],
    }
    for name in ("host", "port", "user", "ready_at"):
        try:
            VmConnectionDetails.model_validate({name: candidate[name]})
        except ValueError:
            candidate[name] = None
    return VmConnectionDetails.model_validate(candidate).model_dump(
        mode="json", exclude_none=True
    )


def _migrate_connection_details_to_delivery(conn: sqlite3.Connection) -> None:
    """Rewrite stored connection details into the shape a delivery records.

    Covers each deal's escrow record and the listing a VM was delivered on.
    Rows already in that shape are left alone, so a rerun changes nothing; a
    value that is not a JSON object was never readable as connection details
    and is left as it is.
    """
    for table, column, key in (
        ("escrows", "connection_details", "escrow_uid"),
        ("listings", "fulfillment_resource", "listing_id"),
    ):
        if not _table_exists(conn, table) or not _column_exists(conn, table, column):
            continue
        rows = conn.execute(
            f"SELECT {key}, {column} FROM {table} WHERE {column} IS NOT NULL"
        ).fetchall()
        for row_key, raw in rows:
            try:
                stored = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if not isinstance(stored, dict) or set(stored) <= _CONNECTION_FIELDS:
                continue
            conn.execute(
                f"UPDATE {table} SET {column} = ? WHERE {key} = ?",
                (json.dumps(_connection_details(stored), sort_keys=True), row_key),
            )


def _migrate_fulfillment_context_names_no_guest(conn: sqlite3.Connection) -> None:
    """Remove the guest name from every escrow's stored fulfillment request.

    Provisioning names a VM's guest and refuses a request that names one. A
    stored request is replayed verbatim when restart convergence resumes a deal,
    and provisioning accepts a repeat only when it equals its own stored copy,
    which the provisioning service rewrites the same way, so a replay of a
    rewritten request still matches.

    Every escrow is rewritten, in every state. Contexts of another kind, values
    that are not JSON, and requests naming no guest are left as they are, so a
    rerun changes nothing.
    """
    _remove_fulfillment_request_fields(conn, frozenset({"vm_target"}))


def _migrate_fulfillment_context_carries_no_connectivity(conn: sqlite3.Connection) -> None:
    """Remove ``connectivity`` from every escrow's stored fulfillment request.

    Provisioning refuses a VM request that carries ``connectivity``: the relay
    a host dials is the one its pool references, and the buyer's address and
    port come back in the fulfillment result. An escrow's context keeps a copy
    of the request the storefront sent, which may hold a relay dashboard
    credential nothing reads; it is rewritten as the provisioning service
    rewrites its own copy, so no stored request still carries the field.
    """
    _remove_fulfillment_request_fields(conn, frozenset({"connectivity"}))


def _remove_fulfillment_request_fields(
    conn: sqlite3.Connection, fields: frozenset[str]
) -> None:
    """Drop ``fields`` from every escrow's stored fulfillment request payload.

    Contexts of another kind, values that are not JSON, and requests carrying
    none of ``fields`` are left as they are, so a rerun changes nothing.
    """
    if not _table_exists(conn, "escrows") or not _column_exists(
        conn, "escrows", "fulfillment_context"
    ):
        return
    rows = conn.execute(
        "SELECT escrow_uid, fulfillment_context FROM escrows "
        "WHERE fulfillment_context IS NOT NULL"
    ).fetchall()
    for escrow_uid, raw in rows:
        try:
            context = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if not isinstance(context, dict) or context.get("kind") != (
            "vm.storefront.fulfillment-context"
        ):
            continue
        payload = context.get("payload")
        request = payload.get("fulfillment_request") if isinstance(payload, dict) else None
        stored = request.get("payload") if isinstance(request, dict) else None
        if not isinstance(stored, dict) or fields.isdisjoint(stored):
            continue
        rewritten = {
            **context,
            "payload": {
                **payload,
                "fulfillment_request": {
                    **request,
                    "payload": {
                        key: value for key, value in stored.items() if key not in fields
                    },
                },
            },
        }
        conn.execute(
            "UPDATE escrows SET fulfillment_context = ? WHERE escrow_uid = ?",
            (json.dumps(rewritten, sort_keys=True, separators=(",", ":")), escrow_uid),
        )


VM_MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        "20260604_003_derived_compute_listing_pool_ids",
        _migrate_derived_compute_listing_pool_ids,
    ),
    Migration(
        "20260810_009_escrow_settlement_identity",
        _migrate_escrow_settlement_identity,
    ),
    Migration(
        "20261006_011_connection_details_to_delivery",
        _migrate_connection_details_to_delivery,
    ),
    Migration(
        "20261006_012_fulfillment_context_names_no_guest",
        _migrate_fulfillment_context_names_no_guest,
    ),
    Migration("20261001_011_vm_settlement_records", add_vm_settlement_records),
    Migration(
        "20261027_001_fulfillment_context_carries_no_connectivity",
        _migrate_fulfillment_context_carries_no_connectivity,
    ),
)
