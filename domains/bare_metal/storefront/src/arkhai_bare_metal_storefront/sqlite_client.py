"""Schema-opaque SQLite persistence for the bare-metal composition."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any, TypeVar

from arkhai_bare_metal import (
    BareMetalAcceptedHostedBinding,
    BareMetalAccessResult,
    BareMetalLeaseReadyEvidence,
    BareMetalLeaseReadyResult,
    BareMetalListing,
    BareMetalMaterialization,
    BareMetalMessage,
    BareMetalReceipt,
    BareMetalTerms,
    derive_bare_metal_fulfillment_identity,
)
from core_storefront.sqlite_client import SQLiteClient as CoreSQLiteClient
from core_storefront.sqlite_migrations import MigrationLike
from market_core import MarketDomainContract, validate_domain_contract
from core_storefront import (
    StorefrontDomainBinding,
    StorefrontDomainRegistration,
    StorefrontDomainRegistry,
    StorefrontListingBinding,
    StorefrontThreadBinding,
    build_storefront_derivation_key,
)
from market_contact_exchange import (
    CONTACT_EXCHANGE_MIGRATIONS,
    IntroductionRecord,
    insert_introduction,
    load_introduction,
)
from market_settlement_runtime import settlement_migrations
from market_identity import Identity
from pydantic import BaseModel

from .domain_runtime import get_market_domain_contract
from .migrations import BARE_METAL_STOREFRONT_MIGRATIONS
from .models import BareMetalHostedLifecycle

T = TypeVar("T", bound=BaseModel)


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

    def _domain_migrations(self) -> tuple[MigrationLike, ...]:
        return (
            *settlement_migrations(),
            *CONTACT_EXCHANGE_MIGRATIONS,
            *BARE_METAL_STOREFRONT_MIGRATIONS,
        )

    async def save_contact_introduction(
        self,
        record: IntroductionRecord,
    ) -> IntroductionRecord:
        """Persist one revealed introduction exactly once (idempotent replays)."""

        def _save() -> IntroductionRecord:
            conn = sqlite3.connect(self.db_path)
            try:
                stored = insert_introduction(conn, record)
                conn.commit()
                return stored
            finally:
                conn.close()

        return await asyncio.to_thread(_save)

    async def load_contact_introduction(
        self,
        *,
        obligation_ref: str,
    ) -> IntroductionRecord | None:
        def _load() -> IntroductionRecord | None:
            conn = sqlite3.connect(self.db_path)
            try:
                return load_introduction(conn, obligation_ref)
            finally:
                conn.close()

        return await asyncio.to_thread(_load)

    async def is_global_paused(self) -> bool:
        """Return the durable storefront-wide negotiation pause state."""

        def _load() -> bool:
            conn = sqlite3.connect(self.db_path)
            try:
                row = conn.execute(
                    "SELECT paused FROM bare_metal_operator_state "
                    "WHERE singleton_id = 1",
                ).fetchone()
                if row is None:
                    raise RuntimeError("bare-metal operator state is missing")
                return bool(row[0])
            finally:
                conn.close()

        return await asyncio.to_thread(_load)

    async def set_global_paused(self, *, paused: bool) -> None:
        """Persist storefront-wide negotiation pause state."""

        def _save() -> None:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.execute(
                    "UPDATE bare_metal_operator_state "
                    "SET paused = ?, "
                    "updated_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now') "
                    "WHERE singleton_id = 1",
                    (1 if paused else 0,),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("bare-metal operator state is missing")
                conn.commit()
            finally:
                conn.close()

        await asyncio.to_thread(_save)

    async def count_open_bare_metal_resources(self) -> int:
        """Count open specific-resource publications for operator status."""

        def _count() -> int:
            conn = sqlite3.connect(self.db_path)
            try:
                row = conn.execute(
                    "SELECT COUNT(*) FROM derived_bare_metal_listings d "
                    "JOIN listings l ON l.listing_id = d.listing_id "
                    "WHERE d.status = 'open' AND l.status = 'open' "
                    "AND COALESCE(l.paused, 0) = 0",
                ).fetchone()
                return int(row[0])
            finally:
                conn.close()

        return await asyncio.to_thread(_count)

    async def persist_bare_metal_opening(
        self,
        *,
        negotiation_id: str,
        listing_id: str,
        seller_principal: Identity,
        buyer_agent_id: str,
        buyer_principal: Identity,
        seller_reference_amount: int,
        strategy: str,
        message: BareMetalMessage,
        proposal: Mapping[str, Any],
        buyer_amount: int | None,
        seller_action: str,
        seller_amount: int | None,
        terms: BareMetalTerms | None,
        agreed_amount: int | None,
    ) -> None:
        """Persist one opening under the listing's immutable domain/site binding."""
        listing_binding = await self.load_listing_binding(listing_id=listing_id)
        if listing_binding is None:
            raise RuntimeError(
                f"listing {listing_id!r} has no immutable storefront binding"
            )
        self._domain_registry.resolve(listing_binding.binding)
        thread_binding = StorefrontThreadBinding(
            negotiation_id=negotiation_id,
            listing_id=listing_id,
            site_id=listing_binding.site_id,
            binding=listing_binding.binding,
        )
        normalized_message = self._market_domain.codecs.message(message)
        prepared_message, _ = self.prepare_domain_artifact(
            artifact_slot="message",
            value=normalized_message,
            binding=thread_binding.binding,
            registry=self._domain_registry,
        )
        now = datetime.now(timezone.utc).isoformat()
        owner_id = f"{seller_principal.scheme.value}:{seller_principal.identifier}"
        await self.create_negotiation_opening(
            thread={
                "negotiation_id": negotiation_id,
                "listing_id": listing_id,
                "counterparty_listing_id": "",
                "seller_agent_url": "",
                "buyer_agent_url": buyer_agent_id,
                "requested_duration_seconds": message.duration_seconds,
                "requested_start_utc": None,
                "pinned_proposal": dict(proposal),
                "terms_wire": normalized_message.model_dump(
                    mode="json",
                    exclude_none=True,
                ),
                "buyer_principal": buyer_principal,
                "seller_principal": seller_principal,
                "owner_id": owner_id,
                "seller_initial_amount": seller_reference_amount,
                "strategy_label": strategy,
            },
            initial_message={
                "round_number": 0,
                "sender_role": "buyer",
                "sender_principal": buyer_principal,
                "seller_amount": seller_reference_amount,
                "buyer_amount": buyer_amount,
                "proposed_amount": buyer_amount,
                "action_taken": "initial_proposal",
                "message_type": "initial_proposal",
                "timestamp": now,
            },
            binding=thread_binding,
            domain_artifact=prepared_message,
        )
        normalized_terms = (
            self._market_domain.codecs.terms(terms) if terms is not None else None
        )
        terms_payload = (
            self._canonical_artifact_json(normalized_terms)
            if normalized_terms is not None
            else None
        )
        terminal_state = "success" if seller_action == "accept" else None
        status = "terminated" if terminal_state else "active"
        seller_action_taken = {
            "accept": "accept_offer",
            "counter": "counter_offer",
        }.get(seller_action, seller_action)
        seller_message_type = {
            "accept": "accepted",
            "counter": "counter_proposal",
        }.get(seller_action, seller_action)

        def _finish() -> None:
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    """
                    UPDATE negotiation_threads
                    SET status=?, terminal_state=?, agreed_price=?,
                        agreed_duration_seconds=?, agreed_at=?, updated_at=?
                    WHERE negotiation_id=?
                    """,
                    (
                        status,
                        terminal_state,
                        None if agreed_amount is None else str(agreed_amount),
                        message.duration_seconds if agreed_amount is not None else None,
                        now if agreed_amount is not None else None,
                        now,
                        negotiation_id,
                    ),
                )
                conn.execute(
                    """
                    INSERT OR IGNORE INTO negotiation_messages(
                      negotiation_id, round, sender_role, sender_scheme,
                      sender_identifier, our_price, their_price, proposed_price,
                      action_taken, message_type, timestamp
                    ) VALUES (?, 1, 'seller', ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        negotiation_id,
                        seller_principal.scheme.value,
                        seller_principal.identifier,
                        str(seller_reference_amount),
                        None if buyer_amount is None else str(buyer_amount),
                        None if seller_amount is None else str(seller_amount),
                        seller_action_taken,
                        seller_message_type,
                        now,
                    ),
                )
                if terms_payload is not None:
                    binding = thread_binding.binding
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO storefront_domain_artifacts(
                          negotiation_id, artifact_slot, offering_mode,
                          domain_identity, contract_major, contract_minor,
                          artifact_json
                        ) VALUES (?, 'terms', ?, ?, ?, ?, ?)
                        """,
                        (
                            negotiation_id,
                            binding.offering_mode,
                            str(binding.domain_identity),
                            binding.contract_major,
                            binding.contract_minor,
                            terms_payload,
                        ),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

        await asyncio.to_thread(_finish)

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
        domain_binding = StorefrontDomainBinding(
            offering_mode="bare_metal",
            domain_identity=self._market_domain.identity,
            contract_major=self._market_domain.contract_version.major,
            contract_minor=self._market_domain.contract_version.minor,
        )
        source_envelope = {
            "kind": "bare_metal.resource-projection.v1",
            "schema_version": 1,
            "site_id": site_id,
            "pool_id": pool_id,
            "physical_resource_id": physical_resource_id,
            "machine_id": normalized.machine_id,
            "physical_host_id": normalized.physical_host_id,
        }
        binding = StorefrontListingBinding.from_source_envelope(
            listing_id=listing_id,
            site_id=site_id,
            pool_id=pool_id,
            physical_resource_id=physical_resource_id,
            binding=domain_binding,
            derivation_key=build_storefront_derivation_key(
                site_id=site_id,
                offering_mode="bare_metal",
                binding=domain_binding,
                source_identity={
                    "pool_id": pool_id,
                    "physical_resource_id": physical_resource_id,
                },
            ),
            source_envelope=source_envelope,
            last_reconciled_at=updated_at,
        )
        offer_resource = normalized.model_dump(mode="json", exclude_none=True)
        offer_resource["virtualization_type"] = domain_binding.offering_mode
        await self.upsert_listing_with_binding(
            binding=binding,
            status=status,
            created_at=created_at,
            updated_at=updated_at,
            offer_resource=offer_resource,
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
        raw = row.get("offer_resource")
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
        result: BareMetalAccessResult | Mapping[str, Any],
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
    ) -> BareMetalAccessResult | None:
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
                "machine_id": listing.machine_id,
                "physical_host_id": listing.physical_host_id,
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
        escrow_uid: str,
        site_id: str,
        physical_resource_id: str,
    ) -> dict[str, Any]:
        def _save() -> dict[str, Any]:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                with conn:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO bare_metal_fulfillment_lifecycle(
                          negotiation_id, escrow_uid, site_id,
                          physical_resource_id, state
                        ) VALUES (?, ?, ?, ?, 'planning')
                        """,
                        (
                            negotiation_id,
                            escrow_uid,
                            site_id,
                            physical_resource_id,
                        ),
                    )
                row = conn.execute(
                    "SELECT * FROM bare_metal_fulfillment_lifecycle "
                    "WHERE negotiation_id = ?",
                    (negotiation_id,),
                ).fetchone()
                if row is None:
                    raise RuntimeError("bare-metal fulfillment lifecycle is missing")
                result = dict(row)
                expected = {
                    "escrow_uid": escrow_uid,
                    "site_id": site_id,
                    "physical_resource_id": physical_resource_id,
                }
                if any(result[key] != value for key, value in expected.items()):
                    raise RuntimeError(
                        "bare-metal fulfillment lifecycle identity conflict"
                    )
                return result
            finally:
                conn.close()

        return await asyncio.to_thread(_save)

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
    def _hosted_lifecycle_from_row(
        row: Mapping[str, Any],
    ) -> BareMetalHostedLifecycle:
        binding = BareMetalAcceptedHostedBinding.model_validate_json(
            str(row["accepted_binding_json"])
        )
        public_result = (
            BareMetalLeaseReadyResult.model_validate_json(
                str(row["public_result_json"])
            )
            if row.get("public_result_json") is not None
            else None
        )
        portable_evidence = (
            BareMetalLeaseReadyEvidence.model_validate_json(
                str(row["portable_evidence_json"])
            )
            if row.get("portable_evidence_json") is not None
            else None
        )
        return BareMetalHostedLifecycle(
            accepted_binding=binding,
            accepted_binding_digest=str(row["accepted_binding_digest"]),
            fulfillment_identity=str(row["fulfillment_identity"]),
            physical_state=str(row["physical_state"]),
            financial_state=str(row["financial_state"]),
            recovery_state=str(row["recovery_state"]),
            teardown_state=str(row["teardown_state"]),
            capacity_reservation_id=row.get("capacity_reservation_id"),
            settlement_resource_id=row.get("settlement_resource_id"),
            fulfillment_id=row.get("fulfillment_id"),
            public_result=public_result,
            public_result_digest=row.get("public_result_digest"),
            portable_evidence=portable_evidence,
            portable_evidence_digest=row.get("portable_evidence_digest"),
            portable_evidence_ref=row.get("portable_evidence_ref"),
            failure_reason=row.get("failure_reason"),
        )

    async def save_bare_metal_hosted_binding(
        self,
        binding: BareMetalAcceptedHostedBinding,
    ) -> BareMetalHostedLifecycle:
        """Persist one seller-derived hosted binding or reject changed replay."""

        accepted = BareMetalAcceptedHostedBinding.model_validate(binding)
        accepted_json = accepted.model_dump_json(exclude_none=True)
        accepted_digest = accepted.binding_digest
        fulfillment_identity = derive_bare_metal_fulfillment_identity(accepted)

        def _save() -> BareMetalHostedLifecycle:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                with conn:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO bare_metal_hosted_lifecycle(
                          obligation_ref, agreement_ref, negotiation_id,
                          accepted_binding_json, accepted_binding_digest,
                          fulfillment_identity
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            accepted.obligation_ref,
                            accepted.agreement_ref,
                            accepted.negotiation_id,
                            accepted_json,
                            accepted_digest,
                            fulfillment_identity,
                        ),
                    )
                row = conn.execute(
                    "SELECT * FROM bare_metal_hosted_lifecycle "
                    "WHERE obligation_ref = ?",
                    (accepted.obligation_ref,),
                ).fetchone()
                if row is None:
                    raise RuntimeError(
                        "bare-metal hosted negotiation/obligation identity conflict"
                    )
                lifecycle = self._hosted_lifecycle_from_row(dict(row))
                if (
                    lifecycle.accepted_binding != accepted
                    or lifecycle.accepted_binding_digest != accepted_digest
                    or lifecycle.fulfillment_identity != fulfillment_identity
                ):
                    raise RuntimeError(
                        "bare-metal hosted accepted binding changed on replay"
                    )
                return lifecycle
            finally:
                conn.close()

        return await asyncio.to_thread(_save)

    async def load_bare_metal_hosted_lifecycle(
        self,
        *,
        obligation_ref: str,
    ) -> BareMetalHostedLifecycle | None:
        def _load() -> BareMetalHostedLifecycle | None:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                row = conn.execute(
                    "SELECT * FROM bare_metal_hosted_lifecycle "
                    "WHERE obligation_ref = ?",
                    (obligation_ref,),
                ).fetchone()
                return (
                    self._hosted_lifecycle_from_row(dict(row))
                    if row is not None
                    else None
                )
            finally:
                conn.close()

        return await asyncio.to_thread(_load)

    async def load_bare_metal_hosted_evidence(
        self,
        *,
        evidence_digest: str,
    ) -> BareMetalLeaseReadyEvidence | None:
        """Resolve one content-addressed public evidence document."""

        def _load() -> BareMetalLeaseReadyEvidence | None:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                row = conn.execute(
                    "SELECT portable_evidence_json FROM bare_metal_hosted_lifecycle "
                    "WHERE portable_evidence_digest = ?",
                    (evidence_digest,),
                ).fetchone()
                if row is None or row["portable_evidence_json"] is None:
                    return None
                return BareMetalLeaseReadyEvidence.model_validate_json(
                    str(row["portable_evidence_json"])
                )
            finally:
                conn.close()

        return await asyncio.to_thread(_load)

    async def load_bare_metal_hosted_lifecycle_for_agreement(
        self,
        *,
        agreement_ref: str,
    ) -> BareMetalHostedLifecycle | None:
        def _load() -> BareMetalHostedLifecycle | None:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(
                    "SELECT * FROM bare_metal_hosted_lifecycle WHERE agreement_ref = ?",
                    (agreement_ref,),
                ).fetchall()
                if len(rows) > 1:
                    raise RuntimeError(
                        "bare-metal hosted agreement has multiple obligations"
                    )
                return self._hosted_lifecycle_from_row(dict(rows[0])) if rows else None
            finally:
                conn.close()

        return await asyncio.to_thread(_load)

    async def advance_bare_metal_hosted_lifecycle(
        self,
        *,
        obligation_ref: str,
        physical_state: str | None = None,
        financial_state: str | None = None,
        recovery_state: str | None = None,
        teardown_state: str | None = None,
        capacity_reservation_id: str | None = None,
        settlement_resource_id: str | None = None,
        fulfillment_id: str | None = None,
        public_result: BareMetalLeaseReadyResult | None = None,
        portable_evidence: BareMetalLeaseReadyEvidence | None = None,
        portable_evidence_ref: str | None = None,
        failure_reason: str | None = None,
    ) -> BareMetalHostedLifecycle:
        """Advance monotonic hosted/physical facts with exact replay checks."""

        if (portable_evidence is None) != (portable_evidence_ref is None):
            raise ValueError("portable evidence payload and ref are atomic")

        physical_order = {
            "accepted": 0,
            "funded": 1,
            "capacity_reserved": 2,
            "capacity_committed": 3,
            "scheduled": 4,
            "fulfillment_pending": 5,
            "access_ready": 6,
            "evidence_published": 7,
        }
        financial_transitions = {
            "pending": {
                "pending",
                "collection_unknown",
                "collected",
                "collection_blocked",
                "reclaimed",
                "manual_review",
            },
            "collection_unknown": {
                "collection_unknown",
                "collected",
                "manual_review",
            },
            "collection_blocked": {
                "collection_blocked",
                "reclaimed",
                "manual_review",
            },
            "collected": {"collected"},
            "reclaimed": {"reclaimed"},
            "manual_review": {"manual_review"},
        }
        recovery_transitions = {
            "none": {
                "none",
                "funding_returned",
                "reclaim_pending",
                "reclaimed",
                "loss_manual",
                "manual_review",
            },
            "funding_returned": {
                "funding_returned",
                "reclaim_pending",
                "reclaimed",
                "manual_review",
            },
            "reclaim_pending": {
                "reclaim_pending",
                "reclaimed",
                "manual_review",
            },
            "reclaimed": {"reclaimed"},
            "loss_manual": {"loss_manual"},
            "manual_review": {"manual_review"},
        }
        teardown_transitions = {
            "not_started": {"not_started", "pending", "released"},
            "pending": {"pending", "tearing_down", "failed", "torn_down"},
            "tearing_down": {"tearing_down", "failed", "torn_down"},
            "failed": {"failed", "pending", "tearing_down", "torn_down"},
            "torn_down": {"torn_down", "released"},
            "released": {"released"},
        }

        def _advance() -> BareMetalHostedLifecycle:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                with conn:
                    row = conn.execute(
                        "SELECT * FROM bare_metal_hosted_lifecycle "
                        "WHERE obligation_ref = ?",
                        (obligation_ref,),
                    ).fetchone()
                    if row is None:
                        raise RuntimeError("bare-metal hosted lifecycle is missing")
                    current = self._hosted_lifecycle_from_row(dict(row))
                    for field_name, incoming in (
                        ("capacity_reservation_id", capacity_reservation_id),
                        ("settlement_resource_id", settlement_resource_id),
                        ("fulfillment_id", fulfillment_id),
                    ):
                        existing = getattr(current, field_name)
                        if (
                            incoming is not None
                            and existing is not None
                            and incoming != existing
                        ):
                            raise RuntimeError(
                                f"bare-metal hosted {field_name} changed on replay"
                            )
                    if public_result is not None and (
                        current.public_result is not None
                        and current.public_result != public_result
                    ):
                        raise RuntimeError(
                            "bare-metal hosted public result changed on replay"
                        )
                    if portable_evidence is not None and (
                        current.portable_evidence is not None
                        and (
                            current.portable_evidence != portable_evidence
                            or current.portable_evidence_ref != portable_evidence_ref
                        )
                    ):
                        raise RuntimeError(
                            "bare-metal hosted evidence changed on replay"
                        )
                    next_physical = physical_state or current.physical_state
                    if next_physical != "physical_failed":
                        if current.physical_state == "physical_failed":
                            raise RuntimeError(
                                "failed bare-metal physical lifecycle cannot advance"
                            )
                        if (
                            next_physical not in physical_order
                            or physical_order[next_physical]
                            < physical_order[current.physical_state]
                        ):
                            raise RuntimeError(
                                "bare-metal hosted physical state regressed"
                            )
                    elif current.physical_state == "evidence_published":
                        raise RuntimeError(
                            "published bare-metal evidence cannot become failure"
                        )
                    next_financial = financial_state or current.financial_state
                    if (
                        next_financial
                        not in financial_transitions[current.financial_state]
                    ):
                        raise RuntimeError(
                            "bare-metal hosted financial state conflicts"
                        )
                    next_recovery = recovery_state or current.recovery_state
                    if (
                        next_recovery
                        not in recovery_transitions[current.recovery_state]
                    ):
                        raise RuntimeError("bare-metal hosted recovery state conflicts")
                    next_teardown = teardown_state or current.teardown_state
                    if (
                        next_teardown
                        not in teardown_transitions[current.teardown_state]
                    ):
                        raise RuntimeError("bare-metal hosted teardown state conflicts")
                    result_json = (
                        public_result.model_dump_json(exclude_none=True)
                        if public_result is not None
                        else None
                    )
                    evidence_json = (
                        portable_evidence.model_dump_json(exclude_none=True)
                        if portable_evidence is not None
                        else None
                    )
                    conn.execute(
                        """
                        UPDATE bare_metal_hosted_lifecycle SET
                          physical_state = ?,
                          financial_state = ?,
                          recovery_state = ?,
                          teardown_state = ?,
                          capacity_reservation_id =
                            COALESCE(?, capacity_reservation_id),
                          settlement_resource_id =
                            COALESCE(?, settlement_resource_id),
                          fulfillment_id = COALESCE(?, fulfillment_id),
                          public_result_json =
                            COALESCE(?, public_result_json),
                          public_result_digest =
                            COALESCE(?, public_result_digest),
                          portable_evidence_json =
                            COALESCE(?, portable_evidence_json),
                          portable_evidence_digest =
                            COALESCE(?, portable_evidence_digest),
                          portable_evidence_ref =
                            COALESCE(?, portable_evidence_ref),
                          failure_reason = COALESCE(?, failure_reason),
                          updated_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')
                        WHERE obligation_ref = ?
                        """,
                        (
                            next_physical,
                            next_financial,
                            next_recovery,
                            next_teardown,
                            capacity_reservation_id,
                            settlement_resource_id,
                            fulfillment_id,
                            result_json,
                            (
                                public_result.result_digest
                                if public_result is not None
                                else None
                            ),
                            evidence_json,
                            (
                                portable_evidence.evidence_digest
                                if portable_evidence is not None
                                else None
                            ),
                            portable_evidence_ref,
                            failure_reason,
                            obligation_ref,
                        ),
                    )
                updated = conn.execute(
                    "SELECT * FROM bare_metal_hosted_lifecycle "
                    "WHERE obligation_ref = ?",
                    (obligation_ref,),
                ).fetchone()
                assert updated is not None
                return self._hosted_lifecycle_from_row(dict(updated))
            finally:
                conn.close()

        return await asyncio.to_thread(_advance)
