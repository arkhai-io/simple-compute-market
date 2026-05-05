"""ListingService — synchronous listing lifecycle orchestrator.

Each public method is a named sequence of steps. Policy consultation and
execution are delegated to PolicyService via named methods — no event
terminology is visible here.

Startup validation: config prerequisites for escrow operations are checked
at construction time so failures are visible immediately rather than per-call.
"""
from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from market_storefront.models.listing_models import (
    AdminEvaluateCloseResponse,
    AdminEvaluateCreateResponse,
    ArbitrateRequest,
    ClaimRequest,
    CloseListingResponse,
    CreateListingRequest,
    CreateListingResponse,
    ReclaimRequest,
    RefundRequest,
)
from market_storefront.resources import parse_resource_from_dict
from market_storefront.utils.stage_log import stage_event

if TYPE_CHECKING:
    from market_storefront.services.policy_service import PolicyService

logger = logging.getLogger(__name__)


class ListingService:
    def __init__(self, *, sqlite_client, alkahest_client, config) -> None:
        self._db = sqlite_client
        self._alkahest = alkahest_client
        self._config = config

        priv_key = (config.agent_priv_key or "").strip()
        rpc_url = (config.chain_rpc_url or "").strip()
        self._token_transfers_available: bool = bool(priv_key and rpc_url)
        self._alkahest_available: bool = alkahest_client is not None

        if not self._token_transfers_available:
            logger.warning(
                "[STOREFRONT] Token transfer operations (refund) unavailable — "
                "AGENT_PRIV_KEY and CHAIN_RPC_URL must both be set in storefront config."
            )
        if not self._alkahest_available:
            logger.warning(
                "[STOREFRONT] On-chain escrow operations (claim, reclaim, arbitrate) unavailable — "
                "AGENT_PRIV_KEY and CHAIN_RPC_URL must both be set in storefront config."
            )

    @staticmethod
    def _normalize_token_resource(resource_payload: dict) -> dict:
        from service.clients.token import TOKEN_REGISTRY
        if "token" not in resource_payload:
            return resource_payload
        token_value = resource_payload.get("token")
        if token_value is None:
            raise ValueError("Token must be a symbol or contract address")
        try:
            if isinstance(token_value, str):
                token_meta = TOKEN_REGISTRY.require(token_value)
            elif isinstance(token_value, dict):
                if all(k in token_value for k in ("symbol", "contract_address", "decimals")):
                    token_meta = token_value
                elif "symbol" in token_value:
                    token_meta = TOKEN_REGISTRY.require(token_value["symbol"])
                elif "contract_address" in token_value:
                    token_meta = TOKEN_REGISTRY.require(token_value["contract_address"])
                else:
                    raise ValueError("Token dict must include symbol/contract_address/decimals")
            else:
                raise ValueError("Token must be a symbol string or metadata dict")
        except Exception as exc:
            raise ValueError(f"Unknown token: {token_value}") from exc
        amount_value = resource_payload.get("amount")
        if amount_value is None:
            raise ValueError("Token resource must include amount")
        if isinstance(token_meta, dict):
            decimals = int(token_meta["decimals"])
            token_dump = token_meta
        else:
            decimals = token_meta.decimals
            token_dump = token_meta.model_dump()
        raw = Decimal(str(amount_value)) * (Decimal(10) ** decimals)
        if raw != raw.to_integral_value():
            raise ValueError("Amount has too many decimal places for this token")
        normalized = dict(resource_payload)
        normalized["token"] = token_dump
        normalized["amount"] = int(raw)
        return normalized

    def _parse_offer_demand(self, request: CreateListingRequest) -> tuple[Any, Any]:
        from market_storefront.models.domain_models import ComputeResource
        from market_storefront.resources import TokenResource as _TR
        try:
            offer_resource = parse_resource_from_dict(
                self._normalize_token_resource(request.offer)
            )
            demand_resource = parse_resource_from_dict(
                self._normalize_token_resource(request.demand)
            )
        except Exception as exc:
            raise ValueError(f"Invalid offer/demand resource: {exc}") from exc
        if not (
            (isinstance(offer_resource, ComputeResource) and isinstance(demand_resource, _TR))
            or (isinstance(offer_resource, _TR) and isinstance(demand_resource, ComputeResource))
        ):
            raise ValueError(
                "Offer and demand must be one compute resource and one token resource"
            )
        return offer_resource, demand_resource

    async def create_listing(
        self, request: CreateListingRequest, policy_svc: "PolicyService"
    ) -> CreateListingResponse:
        offer, demand = self._parse_offer_demand(request)
        action = await policy_svc.evaluate_create_listing_policy(
            offer, demand, request.max_duration_seconds, request.paused
        )
        if action != "make_offer":
            return CreateListingResponse(
                status="no_action",
                root_agent_response=f"Policy returned: {action}",
            )
        listing_id = await policy_svc.execute_create_listing(
            offer, demand, request.max_duration_seconds, request.paused
        )
        return CreateListingResponse(
            status="created" if listing_id else "no_action",
            listing_id=listing_id,
        )

    async def evaluate_create(
        self, request: CreateListingRequest, policy_svc: "PolicyService"
    ) -> AdminEvaluateCreateResponse:
        offer, demand = self._parse_offer_demand(request)
        action = await policy_svc.evaluate_create_listing_policy(
            offer, demand, request.max_duration_seconds, request.paused
        )
        return AdminEvaluateCreateResponse(
            would_create=(action == "make_offer"),
            action=action,
        )

    async def close_listing(
        self, listing_id: str, policy_svc: "PolicyService"
    ) -> CloseListingResponse:
        action = await policy_svc.evaluate_close_listing_policy(listing_id)
        if action not in ("close_order", "close_listing"):
            return CloseListingResponse(
                status="no_action", listing_id=listing_id,
                root_agent_response=f"Policy returned: {action}",
            )
        result = await policy_svc.execute_close_listing(listing_id)
        return CloseListingResponse(
            status=result.get("status", "closed"), listing_id=listing_id,
        )

    async def evaluate_close(
        self, listing_id: str, policy_svc: "PolicyService"
    ) -> AdminEvaluateCloseResponse:
        action = await policy_svc.evaluate_close_listing_policy(listing_id)
        return AdminEvaluateCloseResponse(
            would_close=action in ("close_order", "close_listing"),
            action=action, listing_id=listing_id,
        )

    async def refund(self, listing_id: str, payload: RefundRequest) -> tuple[int, dict]:
        if not self._token_transfers_available:
            return 503, {
                "error": "Token transfer not configured",
                "detail": "AGENT_PRIV_KEY and CHAIN_RPC_URL must both be set in storefront config.",
            }
        order = await self._db.load_listing(listing_id=listing_id)
        from service.clients.token import TOKEN_REGISTRY
        def _resolve_token(ident: str) -> dict:
            try:
                meta = TOKEN_REGISTRY.require(ident)
            except Exception as exc:
                raise ValueError(f"Unknown token: {ident}") from exc
            return meta.model_dump() if hasattr(meta, "model_dump") else dict(meta)
        from market_storefront.utils.refund import derive_refund_params
        outcome = derive_refund_params(
            order=order,
            payload={"listing_id": listing_id, "buyer_address": payload.buyer_address,
                     "amount": payload.amount, "token": payload.token},
            resolve_token=_resolve_token,
        )
        if outcome[0] == "error":
            _, status, body = outcome
            return status, body
        params = outcome[1]
        from market_storefront.utils.token_transfer import transfer_erc20
        try:
            result = await transfer_erc20(
                private_key=self._config.agent_priv_key.strip(),
                rpc_url=self._config.chain_rpc_url.strip(),
                token_address=params["token_address"],
                to_address=params["buyer_address"],
                amount_raw=params["amount_raw"],
            )
        except RuntimeError as exc:
            return 502, {"error": "Token transfer failed", "detail": str(exc)}
        await self._db.update_listing(
            listing_id=listing_id, status="refunded",
            updated_at=datetime.now().isoformat(),
        )
        stage_event("post_settlement", "refund_transferred",
                    listing_id=listing_id, tx_hash=result["tx_hash"])
        return 200, {
            "status": "refunded", "listing_id": listing_id,
            "tx_hash": result["tx_hash"], "from_address": result["from_address"],
            "to_address": result["to_address"],
            "token": {"symbol": params["token_meta"].get("symbol"),
                      "contract_address": params["token_meta"].get("contract_address"),
                      "decimals": params.get("decimals")},
            "amount_raw": params["amount_raw"], "block_number": result["block_number"],
        }

    async def claim(self, listing_id: str, payload: ClaimRequest) -> tuple[int, dict]:
        if not self._alkahest_available:
            return 503, {"error": "On-chain escrow operations not configured",
                         "detail": "AGENT_PRIV_KEY and CHAIN_RPC_URL must both be set in storefront config."}
        try:
            collect_result = await self._alkahest.erc20.escrow.non_tierable.collect(
                payload.escrow_uid, payload.fulfillment_uid)
        except Exception as exc:
            return 502, {"error": "Escrow collect failed on-chain", "detail": str(exc),
                         "listing_id": listing_id}
        await self._db.update_listing(listing_id=listing_id, status="closed",
                                       updated_at=datetime.now().isoformat())
        stage_event("post_settlement", "escrow_claimed",
                    listing_id=listing_id, escrow_uid=payload.escrow_uid)
        return 200, {"status": "claimed", "listing_id": listing_id,
                     "escrow_uid": payload.escrow_uid, "fulfillment_uid": payload.fulfillment_uid,
                     "collect_result": str(collect_result)}

    async def reclaim(self, listing_id: str, payload: ReclaimRequest) -> tuple[int, dict]:
        if not self._alkahest_available:
            return 503, {"error": "On-chain escrow operations not configured",
                         "detail": "AGENT_PRIV_KEY and CHAIN_RPC_URL must both be set in storefront config."}
        try:
            reclaim_result = await self._alkahest.erc20.escrow.non_tierable.reclaim_expired(
                payload.escrow_uid)
        except Exception as exc:
            return 502, {"error": "Escrow reclaim failed on-chain", "detail": str(exc),
                         "listing_id": listing_id}
        await self._db.update_listing(listing_id=listing_id, status="reclaimed",
                                       updated_at=datetime.now().isoformat())
        stage_event("post_settlement", "escrow_reclaimed",
                    listing_id=listing_id, escrow_uid=payload.escrow_uid)
        return 200, {"status": "reclaimed", "listing_id": listing_id,
                     "escrow_uid": payload.escrow_uid, "reclaim_result": str(reclaim_result)}

    async def arbitrate(self, listing_id: str, payload: ArbitrateRequest) -> tuple[int, dict]:
        if not self._alkahest_available:
            return 503, {"error": "On-chain escrow operations not configured",
                         "detail": "AGENT_PRIV_KEY and CHAIN_RPC_URL must both be set in storefront config."}
        try:
            from alkahest_py import ArbitrationMode
            async def decision_function(_a, _d): return bool(payload.decision)
            decisions = await self._alkahest.oracle.arbitrate_many(
                decision_function, lambda _d: None,
                ArbitrationMode.PastUnarbitrated, timeout_seconds=5.0)
        except Exception as exc:
            return 502, {"error": "Oracle arbitration failed on-chain", "detail": str(exc),
                         "listing_id": listing_id}
        stage_event("post_settlement", "oracle_arbitrated",
                    listing_id=listing_id, decision=payload.decision)
        return 200, {
            "status": "arbitrated", "listing_id": listing_id,
            "fulfillment_uid": payload.fulfillment_uid, "decision": payload.decision,
            "decisions_count": len(decisions or []) if decisions is not None else 0,
            "note": "Under RecipientArbiter use /api/v1/listings/{listing_id}/claim to release funds.",
        }
