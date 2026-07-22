"""Schema-opaque SQLite persistence for the bare-metal composition."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Callable, Mapping
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
