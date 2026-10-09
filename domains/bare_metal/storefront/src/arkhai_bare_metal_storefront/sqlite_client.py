"""Schema-opaque SQLite persistence for the bare-metal composition."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from collections.abc import Callable, Collection, Mapping
from typing import Any, TypeVar

from arkhai_bare_metal import (
    BARE_METAL_OFFERING_MODE,
    BareMetalListing,
    BareMetalMaterialization,
    BareMetalMessage,
    BareMetalReceipt,
    BareMetalResult,
    BareMetalTerms,
    bare_metal_source_identity,
)
from core_storefront import (
    StorefrontDomainBinding,
    StorefrontDomainRegistration,
    StorefrontDomainRegistry,
    StorefrontListingBinding,
    build_storefront_derivation_key,
)
from core_storefront.sqlite_client import SQLiteClient as CoreSQLiteClient
from core_storefront.sqlite_migrations import MigrationLike
from market_contact_exchange import (
    CONTACT_EXCHANGE_MIGRATIONS,
)
from market_core import (
    MarketDomainContract,
    SettlementEvidence,
    validate_domain_contract,
)
from market_core.schemas import Agreement
from market_identity import Identity
from market_pool_overrides import pool_override_migrations
from market_settlement_runtime import settlement_migrations
from pydantic import BaseModel

from .domain_runtime import get_market_domain_contract
from .migrations import BARE_METAL_STOREFRONT_MIGRATIONS
from .settlement_evidence import EvidencePayload

T = TypeVar("T", bound=BaseModel)

# Version 2 of a bare-metal binding's source envelope records the listing's
# shape digest, which its derivation key includes. A version 1 binding's key
# matches no candidate, so source reconciliation closes it.
BARE_METAL_SOURCE_ENVELOPE_VERSION = 2


class SQLiteClient(CoreSQLiteClient):
    """Core market state plus validated opaque bare-metal artifacts."""

    def __init__(
        self,
        db_path: str,
        *,
        domain: MarketDomainContract | None = None,
        local_listing_principal: Identity | None = None,
        expected_legacy_sellers: tuple[str, ...] = (),
    ) -> None:
        self._market_domain = validate_domain_contract(
            domain or get_market_domain_contract(),
        )
        self._domain_registry = StorefrontDomainRegistry(
            (
                StorefrontDomainRegistration(
                    offering_mode="bare_metal",
                    contract=self._market_domain,
                    contribution_id="bare_metal",
                ),
            )
        )
        super().__init__(
            db_path,
            local_listing_principal=local_listing_principal,
            expected_legacy_sellers=expected_legacy_sellers,
        )
        required_columns = {
            "bare_metal_settlement_records": "evidence_json",
            "bare_metal_fulfillment_lifecycle": "settlement_ref",
        }
        with sqlite3.connect(self.db_path) as conn:
            for table, required_column in required_columns.items():
                columns = {
                    row[1] for row in conn.execute(f"PRAGMA table_info({table})")
                }
                if required_column not in columns:
                    raise RuntimeError(
                        f"{table} schema requires an explicit database reset"
                    )

    def _domain_migrations(self) -> tuple[MigrationLike, ...]:
        return (
            *settlement_migrations(),
            *CONTACT_EXCHANGE_MIGRATIONS,
            *pool_override_migrations(),
            *BARE_METAL_STOREFRONT_MIGRATIONS,
        )

    async def list_unsettled_payment_negotiations(self, *, mechanism: str, limit: int) -> list[str]:
        """Accepted payment deals not yet verified, refunds left `refunding`, and verified deals whose delivery never started.

        The filter runs before the limit, so completed deals never crowd out an
        unsettled one. A malformed Agreement is skipped, never fatal to the query.
        """

        def load() -> list[str]:
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute(
                    """
                    SELECT t.negotiation_id
                    FROM negotiation_threads t
                    JOIN bare_metal_settlement_records r ON r.negotiation_id = t.negotiation_id
                    LEFT JOIN bare_metal_fulfillment_lifecycle l ON l.negotiation_id = t.negotiation_id
                    WHERE t.terminal_state = 'success'
                      AND t.agreement_bytes IS NOT NULL
                      AND CASE WHEN json_valid(CAST(t.agreement_bytes AS TEXT))
                          THEN json_extract(CAST(t.agreement_bytes AS TEXT), '$.settlement.mechanism')
                          END = ?
                      AND (r.status IN ('accepted', 'refunding') OR (r.status = 'settlement_verified' AND l.negotiation_id IS NULL))
                    ORDER BY t.created_at ASC, t.negotiation_id ASC
                    LIMIT ?
                    """,
                    (mechanism, limit),
                ).fetchall()
            return [str(row[0]) for row in rows]

        return await asyncio.to_thread(load)

    async def count_open_bare_metal_resources(self) -> int:
        """Count open, unpaused bare-metal listings for operator status."""

        def _count() -> int:
            conn = sqlite3.connect(self.db_path)
            try:
                row = conn.execute(
                    "SELECT COUNT(*) FROM storefront_listing_bindings b "
                    "JOIN listings l ON l.listing_id = b.listing_id "
                    "WHERE b.offering_mode = ? AND l.status = 'open' "
                    "AND COALESCE(l.paused, 0) = 0",
                    (BARE_METAL_OFFERING_MODE,),
                ).fetchone()
                return int(row[0])
            finally:
                conn.close()

        return await asyncio.to_thread(_count)

    async def list_open_bare_metal_listing_bindings(
        self,
        *,
        site_ids: Collection[str],
    ) -> tuple[StorefrontListingBinding, ...]:
        """The bindings of open bare-metal listings originating at these sites."""
        sites = tuple(sorted(set(site_ids)))
        if not sites:
            return ()

        def _load() -> tuple[StorefrontListingBinding, ...]:
            placeholders = ", ".join("?" for _ in sites)
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute(
                    f"""
                    SELECT b.listing_id, b.site_id, b.pool_id,
                           b.physical_resource_id, b.offering_mode,
                           b.domain_identity, b.contract_major, b.contract_minor,
                           b.derivation_key, b.source_envelope_json,
                           b.last_reconciled_at, b.capacity_backing
                    FROM storefront_listing_bindings b
                    JOIN listings l ON l.listing_id = b.listing_id
                    WHERE b.offering_mode = ? AND l.status = 'open'
                      AND b.site_id IN ({placeholders})
                    ORDER BY b.listing_id
                    """,
                    (BARE_METAL_OFFERING_MODE, *sites),
                ).fetchall()
            return tuple(self._listing_binding_from_row(row) for row in rows)

        return await asyncio.to_thread(_load)

    def _bare_metal_domain_binding(self) -> StorefrontDomainBinding:
        return StorefrontDomainBinding(
            offering_mode=BARE_METAL_OFFERING_MODE,
            domain_identity=self._market_domain.identity,
            contract_major=self._market_domain.contract_version.major,
            contract_minor=self._market_domain.contract_version.minor,
        )

    def bare_metal_derivation_key(
        self,
        *,
        site_id: str,
        pool_id: str,
        physical_resource_id: str,
        shape_digest: str,
    ) -> str:
        """The common derivation key a bare-metal listing is bound under.

        Publication looks a candidate's listing up by this key and
        :meth:`upsert_bare_metal_listing` binds a new listing under it, so the
        two cannot disagree.
        """
        domain_binding = self._bare_metal_domain_binding()
        return build_storefront_derivation_key(
            site_id=site_id,
            offering_mode=domain_binding.offering_mode,
            binding=domain_binding,
            source_identity=bare_metal_source_identity(
                pool_id=pool_id,
                physical_resource_id=physical_resource_id,
                shape_digest=shape_digest,
            ),
        )

    async def upsert_bare_metal_listing(
        self,
        *,
        listing_id: str,
        status: str,
        created_at: str,
        updated_at: str,
        seller_principal: Identity,
        storefront_url: str,
        listing: BareMetalListing | Mapping[str, Any],
        accepted_escrows: list[dict[str, Any]],
        settlement_options: list[dict[str, Any]] | None = None,
        publication_clauses: list[dict[str, Any]] | None = None,
        demands: list[dict[str, Any]] | None = None,
        paused: bool = False,
        oracle_address: str | None = None,
        site_id: str,
        pool_id: str,
        physical_resource_id: str,
    ) -> None:
        normalized = self._market_domain.codecs.listing(listing)
        domain_binding = self._bare_metal_domain_binding()
        # The key is derived from the listing's own shape, so a listing can
        # only ever be bound under the key its published fields imply.
        shape_digest = normalized.shape_digest
        source_envelope = {
            "kind": "bare_metal.resource-projection.v1",
            "schema_version": BARE_METAL_SOURCE_ENVELOPE_VERSION,
            "site_id": site_id,
            "pool_id": pool_id,
            "physical_resource_id": physical_resource_id,
            "host_id": normalized.host_id,
            "physical_host_id": normalized.physical_host_id,
            "shape_digest": shape_digest,
        }
        binding = StorefrontListingBinding.from_source_envelope(
            listing_id=listing_id,
            site_id=site_id,
            pool_id=pool_id,
            physical_resource_id=physical_resource_id,
            binding=domain_binding,
            derivation_key=self.bare_metal_derivation_key(
                site_id=site_id,
                pool_id=pool_id,
                physical_resource_id=physical_resource_id,
                shape_digest=shape_digest,
            ),
            source_envelope=source_envelope,
            last_reconciled_at=updated_at,
            # Every bare-metal listing is backed by one selected-site Physical
            # Resource; this domain publishes nothing an admission authority
            # does not stand behind.
            capacity_backing="backed",
        )
        listing_resource = normalized.model_dump(mode="json", exclude_none=True)
        listing_resource["offering_mode"] = domain_binding.offering_mode
        await self.upsert_listing_with_binding(
            binding=binding,
            status=status,
            created_at=created_at,
            updated_at=updated_at,
            listing_resource=listing_resource,
            fulfillment_resource=None,
            max_duration_seconds=normalized.max_duration_seconds,
            storefront_url=storefront_url,
            seller_principal=seller_principal,
            oracle_address=oracle_address,
            paused=paused,
            accepted_escrows=accepted_escrows,
            settlement_options=settlement_options or [],
            publication_clauses=publication_clauses or [],
            demands=demands or [],
        )

    async def load_bare_metal_listing_payload(
        self,
        *,
        listing_id: str,
    ) -> BareMetalListing | None:
        row = await self.load_listing(listing_id=listing_id)
        if row is None:
            return None
        raw = row.get("listing_resource")
        value = json.loads(raw) if isinstance(raw, str) else raw
        return self._market_domain.codecs.listing(value)

    async def _save_artifact(
        self,
        *,
        negotiation_id: str,
        artifact: str,
        value: Any,
        normalize: Callable[[Any], T],
    ) -> None:
        normalized = normalize(value)
        await self.save_domain_artifact(
            negotiation_id=negotiation_id,
            artifact_slot=artifact,
            value=normalized,
            registry=self._domain_registry,
        )

    async def _load_artifact(
        self,
        *,
        negotiation_id: str,
        artifact: str,
        normalize: Callable[[Any], T],
    ) -> T | None:
        value = await self.load_domain_artifact(
            negotiation_id=negotiation_id,
            artifact_slot=artifact,
            registry=self._domain_registry,
        )
        return None if value is None else normalize(value)

    async def save_bare_metal_message(
        self,
        *,
        negotiation_id: str,
        message: BareMetalMessage | Mapping[str, Any],
    ) -> None:
        await self._save_artifact(
            negotiation_id=negotiation_id,
            artifact="message",
            value=message,
            normalize=self._market_domain.codecs.message,
        )

    async def load_bare_metal_message(
        self,
        *,
        negotiation_id: str,
    ) -> BareMetalMessage | None:
        return await self._load_artifact(
            negotiation_id=negotiation_id,
            artifact="message",
            normalize=self._market_domain.codecs.message,
        )

    async def save_bare_metal_terms(
        self,
        *,
        negotiation_id: str,
        terms: BareMetalTerms | Mapping[str, Any],
    ) -> None:
        await self._save_artifact(
            negotiation_id=negotiation_id,
            artifact="terms",
            value=terms,
            normalize=self._market_domain.codecs.terms,
        )

    async def load_bare_metal_terms(
        self,
        *,
        negotiation_id: str,
    ) -> BareMetalTerms | None:
        return await self._load_artifact(
            negotiation_id=negotiation_id,
            artifact="terms",
            normalize=self._market_domain.codecs.terms,
        )

    async def save_bare_metal_materialization(
        self,
        *,
        negotiation_id: str,
        materialization: BareMetalMaterialization | Mapping[str, Any],
    ) -> None:
        await self._save_artifact(
            negotiation_id=negotiation_id,
            artifact="materialization",
            value=materialization,
            normalize=self._market_domain.codecs.materialization,
        )

    async def load_bare_metal_materialization(
        self,
        *,
        negotiation_id: str,
    ) -> BareMetalMaterialization | None:
        return await self._load_artifact(
            negotiation_id=negotiation_id,
            artifact="materialization",
            normalize=self._market_domain.codecs.materialization,
        )

    async def save_bare_metal_receipt(
        self,
        *,
        negotiation_id: str,
        receipt: BareMetalReceipt | Mapping[str, Any],
    ) -> None:
        await self._save_artifact(
            negotiation_id=negotiation_id,
            artifact="receipt",
            value=receipt,
            normalize=self._market_domain.codecs.receipt,
        )

    async def load_bare_metal_receipt(
        self,
        *,
        negotiation_id: str,
    ) -> BareMetalReceipt | None:
        return await self._load_artifact(
            negotiation_id=negotiation_id,
            artifact="receipt",
            normalize=self._market_domain.codecs.receipt,
        )

    async def save_bare_metal_result(
        self,
        *,
        negotiation_id: str,
        result: BareMetalResult | Mapping[str, Any],
    ) -> None:
        await self._save_artifact(
            negotiation_id=negotiation_id,
            artifact="result",
            value=result,
            normalize=self._market_domain.codecs.result,
        )

    async def load_bare_metal_result(
        self,
        *,
        negotiation_id: str,
    ) -> BareMetalResult | None:
        return await self._load_artifact(
            negotiation_id=negotiation_id,
            artifact="result",
            normalize=self._market_domain.codecs.result,
        )

    async def load_bare_metal_fulfillment_context(
        self,
        *,
        negotiation_id: str,
    ) -> dict[str, Any] | None:
        try:
            thread_binding = await self.load_thread_binding(
                negotiation_id=negotiation_id,
            )
        except KeyError:
            return None
        self._domain_registry.resolve(thread_binding.binding)
        listing_binding = await self.load_listing_binding(
            listing_id=thread_binding.listing_id,
        )
        if listing_binding is None:
            raise RuntimeError("bare-metal negotiation references an unbound listing")
        if (
            listing_binding.site_id != thread_binding.site_id
            or listing_binding.binding != thread_binding.binding
        ):
            raise RuntimeError(
                "bare-metal negotiation binding conflicts with its listing"
            )
        if not listing_binding.physical_resource_id:
            raise RuntimeError(
                "bare-metal listing binding has no physical resource identity"
            )

        def _load() -> dict[str, Any] | None:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                row = conn.execute(
                    """
                    SELECT nt.our_listing_id AS listing_id,
                           nt.buyer_scheme, nt.buyer_identifier,
                           nt.seller_scheme, nt.seller_identifier,
                           nt.terminal_state
                    FROM negotiation_threads nt
                    WHERE nt.negotiation_id = ?
                    """,
                    (negotiation_id,),
                ).fetchone()
                return dict(row) if row is not None else None
            finally:
                conn.close()

        context = await asyncio.to_thread(_load)
        if context is None:
            return None
        listing = await self.load_bare_metal_listing_payload(
            listing_id=thread_binding.listing_id,
        )
        if listing is None:
            raise RuntimeError(
                "bare-metal negotiation references a missing listing payload"
            )
        context.update(
            {
                "site_id": thread_binding.site_id,
                "physical_resource_id": listing_binding.physical_resource_id,
                "pool_id": listing_binding.pool_id,
                "host_id": listing.host_id,
                "physical_host_id": listing.physical_host_id,
                "claimed_attributes": listing.claimed_attributes,
            }
        )
        return self.bind_fulfillment_context(
            context,
            thread_binding=thread_binding,
        )

    async def ensure_bare_metal_fulfillment_lifecycle(
        self,
        *,
        negotiation_id: str,
        settlement_ref: str,
        site_id: str,
        physical_resource_id: str,
    ) -> dict[str, Any] | None:
        """Start a deal's delivery only while its settlement evidence is verified.

        The lifecycle row is the delivery-start marker: it is inserted in the same
        transaction that checks the settlement record, so refund intent recorded
        first prevents delivery, and an existing row (an interrupted delivery)
        is returned as is. Returns ``None`` when a refund already owns the deal.
        """

        def _start() -> dict[str, Any] | None:
            conn = sqlite3.connect(self.db_path, isolation_level=None)
            conn.row_factory = sqlite3.Row
            try:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    row = conn.execute(
                        "SELECT * FROM bare_metal_fulfillment_lifecycle WHERE negotiation_id = ?",
                        (negotiation_id,),
                    ).fetchone()
                    if row is None:
                        record = conn.execute(
                            "SELECT status, settlement_ref FROM bare_metal_settlement_records "
                            "WHERE negotiation_id = ?",
                            (negotiation_id,),
                        ).fetchone()
                        if record is None or record["status"] != "settlement_verified":
                            conn.execute("ROLLBACK")
                            return None
                        if record["settlement_ref"] != settlement_ref:
                            raise RuntimeError(
                                "bare-metal fulfillment lifecycle identity conflict"
                            )
                        conn.execute(
                            "INSERT INTO bare_metal_fulfillment_lifecycle("
                            "negotiation_id, settlement_ref, site_id, physical_resource_id, state"
                            ") VALUES (?, ?, ?, ?, 'planning')",
                            (negotiation_id, settlement_ref, site_id, physical_resource_id),
                        )
                        row = conn.execute(
                            "SELECT * FROM bare_metal_fulfillment_lifecycle "
                            "WHERE negotiation_id = ?",
                            (negotiation_id,),
                        ).fetchone()
                    conn.execute("COMMIT")
                except BaseException:
                    if conn.in_transaction:
                        conn.execute("ROLLBACK")
                    raise
                result = dict(row)
                expected = {
                    "settlement_ref": settlement_ref,
                    "site_id": site_id,
                    "physical_resource_id": physical_resource_id,
                }
                if any(result[key] != value for key, value in expected.items()):
                    raise RuntimeError("bare-metal fulfillment lifecycle identity conflict")
                return result
            finally:
                conn.close()

        return await asyncio.to_thread(_start)

    async def record_bare_metal_refund_intent(self, *, negotiation_id: str) -> dict[str, Any]:
        """Record refund intent before reversing; report whether delivery had started.

        Serialized against ``ensure_bare_metal_fulfillment_lifecycle``: whichever
        commits first decides whether delivery precedes the refund.
        """

        def _record() -> dict[str, Any]:
            conn = sqlite3.connect(self.db_path, isolation_level=None)
            try:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    record = conn.execute(
                        "SELECT status FROM bare_metal_settlement_records WHERE negotiation_id = ?",
                        (negotiation_id,),
                    ).fetchone()
                    if record is None:
                        raise RuntimeError("accepted settlement record is missing")
                    started = conn.execute(
                        "SELECT 1 FROM bare_metal_fulfillment_lifecycle WHERE negotiation_id = ?",
                        (negotiation_id,),
                    ).fetchone() is not None
                    if record[0] != "refunded":
                        conn.execute(
                            "UPDATE bare_metal_settlement_records SET status = 'refunding', "
                            "updated_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now') "
                            "WHERE negotiation_id = ?",
                            (negotiation_id,),
                        )
                    conn.execute("COMMIT")
                    return {"status": record[0], "delivery_started": started}
                except BaseException:
                    conn.execute("ROLLBACK")
                    raise
            finally:
                conn.close()

        return await asyncio.to_thread(_record)

    async def abandon_bare_metal_refund_intent(
        self, *, negotiation_id: str, prior_status: str
    ) -> None:
        """Restore the settlement record when the reversal proved impossible."""

        def _abandon() -> None:
            conn = sqlite3.connect(self.db_path)
            try:
                with conn:
                    conn.execute(
                        "UPDATE bare_metal_settlement_records SET status = ?, "
                        "updated_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now') "
                        "WHERE negotiation_id = ? AND status = 'refunding'",
                        (prior_status, negotiation_id),
                    )
            finally:
                conn.close()

        await asyncio.to_thread(_abandon)

    async def load_bare_metal_fulfillment_lifecycle(
        self,
        *,
        negotiation_id: str,
    ) -> dict[str, Any] | None:
        def _load() -> dict[str, Any] | None:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                row = conn.execute(
                    "SELECT * FROM bare_metal_fulfillment_lifecycle "
                    "WHERE negotiation_id = ?",
                    (negotiation_id,),
                ).fetchone()
                return dict(row) if row is not None else None
            finally:
                conn.close()

        return await asyncio.to_thread(_load)

    async def update_bare_metal_fulfillment_lifecycle(
        self,
        *,
        negotiation_id: str,
        state: str,
        capacity_reservation_id: str | None = None,
        settlement_resource_id: str | None = None,
        fulfillment_id: str | None = None,
        failure_reason: str | None = None,
    ) -> dict[str, Any]:
        def _save() -> dict[str, Any]:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                with conn:
                    cursor = conn.execute(
                        """
                        UPDATE bare_metal_fulfillment_lifecycle SET
                          state = ?,
                          capacity_reservation_id =
                            COALESCE(?, capacity_reservation_id),
                          settlement_resource_id =
                            COALESCE(?, settlement_resource_id),
                          fulfillment_id = COALESCE(?, fulfillment_id),
                          failure_reason = ?,
                          updated_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')
                        WHERE negotiation_id = ?
                        """,
                        (
                            state,
                            capacity_reservation_id,
                            settlement_resource_id,
                            fulfillment_id,
                            failure_reason,
                            negotiation_id,
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise RuntimeError(
                            "bare-metal fulfillment lifecycle is missing"
                        )
                row = conn.execute(
                    "SELECT * FROM bare_metal_fulfillment_lifecycle "
                    "WHERE negotiation_id = ?",
                    (negotiation_id,),
                ).fetchone()
                assert row is not None
                return dict(row)
            finally:
                conn.close()

        return await asyncio.to_thread(_save)

    @staticmethod
    def _decode_bare_metal_settlement_record(row: sqlite3.Row) -> dict[str, Any]:
        record = dict(row)
        payload = EvidencePayload.model_validate_json(record.pop("evidence_json"))
        if payload.agreement_sha256 != record["agreement_sha256"]:
            raise RuntimeError("settlement evidence changed its Agreement binding")
        record["evidence"] = payload.model_dump(mode="json")
        return record

    async def load_bare_metal_settlement_record(
        self, *, negotiation_id: str
    ) -> dict[str, Any] | None:
        def _load() -> dict[str, Any] | None:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                row = conn.execute(
                    "SELECT * FROM bare_metal_settlement_records WHERE negotiation_id = ?",
                    (negotiation_id,),
                ).fetchone()
                return (
                    self._decode_bare_metal_settlement_record(row)
                    if row is not None
                    else None
                )
            finally:
                conn.close()

        return await asyncio.to_thread(_load)

    async def load_bare_metal_settlement_record_by_ref(
        self, *, settlement_ref: str
    ) -> dict[str, Any] | None:
        def _load() -> dict[str, Any] | None:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                row = conn.execute(
                    "SELECT * FROM bare_metal_settlement_records WHERE settlement_ref = ?",
                    (settlement_ref,),
                ).fetchone()
                return (
                    self._decode_bare_metal_settlement_record(row)
                    if row is not None
                    else None
                )
            finally:
                conn.close()

        return await asyncio.to_thread(_load)

    async def record_bare_metal_settlement_acceptance(
        self, *, negotiation_id: str, agreement_bytes: bytes
    ) -> None:
        """Record an accepted deal's settlement identity and unverified evidence, once.

        Every accepted Agreement gets one record, whatever its mechanism:
        settlement, recovery and refund read it. A second acceptance naming a
        different mechanism or Agreement is a conflict, not an update.
        """

        agreement = Agreement.model_validate_json(agreement_bytes)
        if agreement.settlement is None:
            raise ValueError("accepted Agreement has no selected settlement")
        mechanism = agreement.settlement.mechanism
        agreement_sha256 = hashlib.sha256(agreement_bytes).hexdigest()
        evidence_json = EvidencePayload(
            agreement_sha256=agreement_sha256
        ).model_dump_json()

        def _record() -> None:
            conn = sqlite3.connect(self.db_path)
            try:
                with conn:
                    conn.execute(
                        "INSERT OR IGNORE INTO bare_metal_settlement_records("
                        "negotiation_id, mechanism, agreement_sha256, status, "
                        "evidence_json) VALUES (?, ?, ?, 'accepted', ?)",
                        (negotiation_id, mechanism, agreement_sha256, evidence_json),
                    )
                    stored = conn.execute(
                        "SELECT mechanism, agreement_sha256 "
                        "FROM bare_metal_settlement_records WHERE negotiation_id = ?",
                        (negotiation_id,),
                    ).fetchone()
                if stored != (mechanism, agreement_sha256):
                    raise RuntimeError(
                        "accepted settlement record conflicts with Agreement"
                    )
            finally:
                conn.close()

        await asyncio.to_thread(_record)

    async def mark_bare_metal_settlement_refunded(
        self,
        *,
        negotiation_id: str,
        settlement_ref: str,
    ) -> dict[str, Any]:
        """Record a seller refund; terminal, so delivery can no longer begin.

        Only the status moves: the verified evidence the refund reversed is kept.
        """

        def _save() -> dict[str, Any]:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                with conn:
                    conn.execute(
                        "UPDATE bare_metal_settlement_records SET settlement_ref = ?, "
                        "status = 'refunded', "
                        "updated_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now') "
                        "WHERE negotiation_id = ? "
                        "AND status IN ('accepted', 'settlement_verified', 'refunding', 'refunded')",
                        (settlement_ref, negotiation_id),
                    )
                row = conn.execute(
                    "SELECT * FROM bare_metal_settlement_records WHERE negotiation_id = ?",
                    (negotiation_id,),
                ).fetchone()
                if row is None:
                    raise RuntimeError("accepted settlement record is missing")
                record = self._decode_bare_metal_settlement_record(row)
                if record["status"] != "refunded" or record["settlement_ref"] != settlement_ref:
                    raise RuntimeError("refund conflicts with accepted settlement state")
                return record
            finally:
                conn.close()

        return await asyncio.to_thread(_save)

    async def save_bare_metal_settlement_evidence(
        self, evidence: SettlementEvidence
    ) -> None:
        payload = EvidencePayload.model_validate(dict(evidence.evidence))
        if evidence.status == "settlement_verified" and not evidence.settlement_ref:
            raise ValueError("verified settlement requires a reference")
        if evidence.status in ("refunding", "refunded"):
            raise ValueError("refund status moves only through the refund transitions")
        encoded = payload.model_dump_json()

        def _save() -> None:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT * FROM bare_metal_settlement_records WHERE negotiation_id = ?",
                    (evidence.negotiation_id,),
                ).fetchone()
                if row is None:
                    raise RuntimeError("accepted settlement record is missing")
                stored = self._decode_bare_metal_settlement_record(row)
                if (
                    stored["mechanism"] != evidence.mechanism
                    or stored["agreement_sha256"] != payload.agreement_sha256
                    or (
                        stored["settlement_ref"] is not None
                        and stored["settlement_ref"] != evidence.settlement_ref
                    )
                    or (
                        stored["status"] == "settlement_verified"
                        and (
                            evidence.status != stored["status"]
                            or stored["evidence"] != payload.model_dump(mode="json")
                        )
                    )
                    # Refund statuses follow verified evidence; nothing may
                    # replace evidence a refund already acted on.
                    or stored["status"] in ("refunding", "refunded")
                ):
                    raise RuntimeError(
                        "settlement evidence conflicts with accepted state"
                    )
                accepted = conn.execute(
                    "SELECT agreement_bytes FROM negotiation_threads WHERE negotiation_id = ?",
                    (evidence.negotiation_id,),
                ).fetchone()
                if (
                    accepted is None
                    or hashlib.sha256(accepted[0]).hexdigest()
                    != payload.agreement_sha256
                ):
                    raise RuntimeError(
                        "settlement evidence is bound to another Agreement"
                    )
                conn.execute(
                    "UPDATE bare_metal_settlement_records SET settlement_ref = ?, status = ?, "
                    "evidence_json = ?, updated_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now') "
                    "WHERE negotiation_id = ?",
                    (
                        evidence.settlement_ref,
                        evidence.status,
                        encoded,
                        evidence.negotiation_id,
                    ),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

        await asyncio.to_thread(_save)
