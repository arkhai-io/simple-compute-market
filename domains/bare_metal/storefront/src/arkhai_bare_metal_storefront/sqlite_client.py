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
from core_storefront.sqlite_migrations import Migration
from market_core import MarketDomainContract, validate_domain_contract
from pydantic import BaseModel

from .domain_runtime import get_market_domain_contract
from .migrations import BARE_METAL_STOREFRONT_MIGRATIONS

T = TypeVar("T", bound=BaseModel)


class SQLiteClient(CoreSQLiteClient):
    """Core market state plus validated opaque bare-metal artifacts."""

    _ARTIFACT_COLUMNS = {
        "message": "message_json",
        "terms": "terms_json",
        "materialization": "materialization_json",
        "receipt": "receipt_json",
        "result": "result_json",
    }

    def __init__(
        self,
        db_path: str,
        *,
        domain: MarketDomainContract | None = None,
    ) -> None:
        self._market_domain = validate_domain_contract(
            domain or get_market_domain_contract(),
        )
        super().__init__(db_path)

    def _domain_migrations(self) -> tuple[Migration, ...]:
        return BARE_METAL_STOREFRONT_MIGRATIONS

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
        seller_id: str,
        buyer_agent_id: str,
        buyer_identity: str,
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
        """Atomically persist one validated opening and seller decision."""
        message_payload = json.dumps(
            self._market_domain.codecs.message(message).model_dump(
                mode="json",
                exclude_none=True,
            ),
            sort_keys=True,
            separators=(",", ":"),
        )
        terms_payload = None
        if terms is not None:
            terms_payload = json.dumps(
                self._market_domain.codecs.terms(terms).model_dump(
                    mode="json",
                    exclude_none=True,
                ),
                sort_keys=True,
                separators=(",", ":"),
            )
        proposal_payload = json.dumps(
            dict(proposal),
            sort_keys=True,
            separators=(",", ":"),
        )
        now = datetime.now(timezone.utc).isoformat()
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

        def _save() -> None:
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    """
                    INSERT INTO negotiation_threads(
                      negotiation_id, our_listing_id, their_listing_id,
                      our_agent_id, their_agent_id, status, created_at,
                      updated_at, terminal_state, requested_duration_seconds,
                      buyer_escrow_proposal, agreed_price,
                      agreed_duration_seconds, agreed_at, buyer
                    ) VALUES (?, ?, '', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        negotiation_id,
                        listing_id,
                        seller_id,
                        buyer_agent_id,
                        status,
                        now,
                        now,
                        terminal_state,
                        message.duration_seconds,
                        proposal_payload,
                        None if agreed_amount is None else str(agreed_amount),
                        message.duration_seconds if agreed_amount is not None else None,
                        now if agreed_amount is not None else None,
                        buyer_identity,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO negotiation_local_state(
                      negotiation_id, owner_id, our_initial_price, our_strategy
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        negotiation_id,
                        seller_id,
                        str(seller_reference_amount),
                        strategy,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO negotiation_messages(
                      negotiation_id, round, sender, our_price, their_price,
                      proposed_price, action_taken, message_type, timestamp
                    ) VALUES (?, 0, ?, ?, ?, ?, 'initial_proposal',
                              'initial_proposal', ?)
                    """,
                    (
                        negotiation_id,
                        buyer_agent_id,
                        str(seller_reference_amount),
                        None if buyer_amount is None else str(buyer_amount),
                        None if buyer_amount is None else str(buyer_amount),
                        now,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO negotiation_messages(
                      negotiation_id, round, sender, our_price, their_price,
                      proposed_price, action_taken, message_type, timestamp
                    ) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        negotiation_id,
                        seller_id,
                        str(seller_reference_amount),
                        None if buyer_amount is None else str(buyer_amount),
                        None if seller_amount is None else str(seller_amount),
                        seller_action_taken,
                        seller_message_type,
                        now,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO bare_metal_agreement_payloads(
                      negotiation_id, message_json, terms_json
                    ) VALUES (?, ?, ?)
                    """,
                    (negotiation_id, message_payload, terms_payload),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

        await asyncio.to_thread(_save)

    async def upsert_bare_metal_listing(
        self,
        *,
        listing_id: str,
        status: str,
        created_at: str,
        updated_at: str,
        seller: str,
        listing: BareMetalListing | Mapping[str, Any],
        accepted_escrows: list[dict[str, Any]],
        demands: list[dict[str, Any]] | None = None,
        paused: bool = False,
        oracle_address: str | None = None,
    ) -> None:
        normalized = self._market_domain.codecs.listing(listing)
        await self.upsert_listing(
            listing_id=listing_id,
            status=status,
            created_at=created_at,
            updated_at=updated_at,
            offer_resource=normalized.model_dump(mode="json", exclude_none=True),
            fulfillment_resource=None,
            max_duration_seconds=normalized.max_duration_seconds,
            seller=seller,
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
        column = self._ARTIFACT_COLUMNS[artifact]
        normalized = normalize(value)
        payload = json.dumps(
            normalized.model_dump(mode="json", exclude_none=True),
            sort_keys=True,
            separators=(",", ":"),
        )

        def _save() -> None:
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute(
                    f"""
                    INSERT INTO bare_metal_agreement_payloads(
                      negotiation_id, {column}
                    ) VALUES (?, ?)
                    ON CONFLICT(negotiation_id) DO UPDATE SET
                      {column}=excluded.{column},
                      updated_at=STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')
                    """,
                    (negotiation_id, payload),
                )
                conn.commit()
            finally:
                conn.close()

        await asyncio.to_thread(_save)

    async def _load_artifact(
        self,
        *,
        negotiation_id: str,
        artifact: str,
        normalize: Callable[[Any], T],
    ) -> T | None:
        column = self._ARTIFACT_COLUMNS[artifact]

        def _load() -> str | None:
            conn = sqlite3.connect(self.db_path)
            try:
                row = conn.execute(
                    f"SELECT {column} FROM bare_metal_agreement_payloads "
                    "WHERE negotiation_id = ?",
                    (negotiation_id,),
                ).fetchone()
            finally:
                conn.close()
            return None if row is None else row[0]

        raw = await asyncio.to_thread(_load)
        if raw is None:
            return None
        return normalize(json.loads(raw))

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
