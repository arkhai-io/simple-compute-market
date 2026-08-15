"""Schema-opaque SQLite persistence for the bare-metal composition."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any, TypeVar

from arkhai_bare_metal import (
    BareMetalAccessResult,
    BareMetalListing,
    BareMetalMaterialization,
    BareMetalMessage,
    BareMetalReceipt,
    BareMetalTerms,
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
from market_settlement_runtime import settlement_migrations
from market_identity import Identity
from pydantic import BaseModel

from .domain_runtime import get_market_domain_contract
from .migrations import BARE_METAL_STOREFRONT_MIGRATIONS

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
        return (*settlement_migrations(), *BARE_METAL_STOREFRONT_MIGRATIONS)

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
        owner_id = (
            f"{seller_principal.scheme.value}:{seller_principal.identifier}"
        )
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
            self._market_domain.codecs.terms(terms)
            if terms is not None
            else None
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
        await self.upsert_listing_with_binding(
            binding=binding,
            status=status,
            created_at=created_at,
            updated_at=updated_at,
            offer_resource=normalized.model_dump(mode="json", exclude_none=True),
            fulfillment_resource=None,
            max_duration_seconds=normalized.max_duration_seconds,
            storefront_url=storefront_url,
            seller_principal=seller_principal,
            oracle_address=oracle_address,
            paused=paused,
            accepted_escrows=accepted_escrows,
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
            raise RuntimeError(
                "bare-metal negotiation references an unbound listing"
            )
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
