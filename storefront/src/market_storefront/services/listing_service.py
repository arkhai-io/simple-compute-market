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
from typing import TYPE_CHECKING, Any

from market_storefront.models.listing_models import (
    AdminEvaluateCloseResponse,
    AdminEvaluateCreateResponse,
    ArbitrateRequest,
    ClaimRequest,
    CloseListingResponse,
    CreateListingRequest,
    CreateListingResponse,
    EvaluateNegotiateResponse,
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
        """Validate + enrich an inbound token payload — strict address-only.

        Wire format expectations:
          * ``token``: a 0x-prefixed contract address string, or a full
            metadata dict with ``contract_address`` (decimals optional;
            looked up locally if omitted).
          * ``amount``: an integer in base units, or ``None`` for a
            hidden-reserve listing.

        Bare symbol strings and human-decimal amounts are rejected —
        clients pass addresses + base-unit amounts. Symbol enrichment for
        display is best-effort via the chain-resolved cache.
        """
        from service.clients.token import resolve_token_cached
        if "token" not in resource_payload:
            return resource_payload
        token_value = resource_payload.get("token")
        if token_value is None:
            raise ValueError("Token must be a 0x address or metadata dict")

        if isinstance(token_value, dict):
            address = token_value.get("contract_address")
            if not isinstance(address, str) or not address.startswith("0x"):
                raise ValueError(
                    "Token dict must include 'contract_address' as a 0x address"
                )
            decimals = token_value.get("decimals")
            if decimals is None:
                looked_up = resolve_token_cached(address)
                if looked_up is None:
                    raise ValueError(
                        f"Token dict for {address} must include 'decimals' "
                        f"(no cached chain metadata for this address)"
                    )
                token_dump = looked_up.model_dump()
            else:
                token_dump = {
                    "symbol": str(token_value.get("symbol", "")),
                    "contract_address": address,
                    "decimals": int(decimals),
                }
        elif isinstance(token_value, str):
            if not token_value.startswith("0x"):
                raise ValueError(
                    f"Token string must be a 0x address, got {token_value!r}"
                )
            looked_up = resolve_token_cached(token_value)
            if looked_up is not None:
                token_dump = looked_up.model_dump()
            else:
                token_dump = {
                    "symbol": "",
                    "contract_address": token_value,
                    "decimals": 0,
                }
        else:
            raise ValueError(
                f"Unsupported token value type: {type(token_value).__name__}"
            )

        normalized = dict(resource_payload)
        normalized["token"] = token_dump

        amount_value = resource_payload.get("amount")
        if amount_value is None:
            normalized["amount"] = None
            return normalized
        # uint256-safe wire: amount is a non-negative decimal-digit string
        # (or int for in-process Python callers). No float, no scaling.
        # Stored as Python int internally; the TokenResource serializer
        # emits it back as a string on outbound JSON.
        if isinstance(amount_value, bool):
            raise ValueError("Amount must be a non-negative decimal, not bool")
        if isinstance(amount_value, int):
            if amount_value < 0:
                raise ValueError(f"Amount must be non-negative, got {amount_value}")
            normalized["amount"] = amount_value
            return normalized
        if isinstance(amount_value, str):
            s = amount_value.strip()
            if not s.isdigit():
                raise ValueError(
                    f"Amount must be a non-negative decimal-digit string "
                    f"in base units, got {amount_value!r} (scale "
                    f"human→base units client-side)"
                )
            normalized["amount"] = int(s)
            return normalized
        raise ValueError(
            f"Amount must be int, decimal string, or None — got "
            f"{type(amount_value).__name__}"
        )

    def _parse_offer_and_escrows(
        self, request: CreateListingRequest
    ) -> tuple[Any, list[dict[str, Any]]]:
        from market_storefront.models.domain_models import ComputeResource
        try:
            offer_resource = parse_resource_from_dict(
                self._normalize_token_resource(request.offer)
            )
        except Exception as exc:
            raise ValueError(f"Invalid offer resource: {exc}") from exc
        if not isinstance(offer_resource, ComputeResource):
            raise ValueError(
                "Listing offer must be a compute resource (the buyer-as-maker "
                "token-offer shape was removed with the demand_resource cutover)."
            )
        if not request.accepted_escrows:
            raise ValueError(
                "accepted_escrows must be a non-empty list "
                "of {chain_name, escrow_address, fields, price_per_hour} entries."
            )
        return offer_resource, list(request.accepted_escrows)

    async def create_listing(
        self, request: CreateListingRequest, policy_svc: "PolicyService"
    ) -> CreateListingResponse:
        offer, accepted_escrows = self._parse_offer_and_escrows(request)
        action = await policy_svc.evaluate_create_listing_policy(
            offer, accepted_escrows, request.max_duration_seconds, request.paused
        )
        if action != "make_offer":
            return CreateListingResponse(
                status="no_action",
                root_agent_response=f"Policy returned: {action}",
            )
        listing_id = await policy_svc.execute_create_listing(
            offer, accepted_escrows, request.max_duration_seconds, request.paused
        )
        return CreateListingResponse(
            status="created" if listing_id else "no_action",
            listing_id=listing_id,
        )

    async def evaluate_create(
        self, request: CreateListingRequest, policy_svc: "PolicyService"
    ) -> AdminEvaluateCreateResponse:
        offer, accepted_escrows = self._parse_offer_and_escrows(request)
        action = await policy_svc.evaluate_create_listing_policy(
            offer, accepted_escrows, request.max_duration_seconds, request.paused
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

    async def evaluate_negotiate(
        self, listing_id: str, their_proposed_price: float
    ) -> EvaluateNegotiateResponse:
        """Dry-run the round-0 negotiation decision without creating a thread.

        Loads the listing from SQLite, then delegates to
        ``_compute_round_zero_decision`` — the same pure-compute function
        used by ``start_sync_negotiation`` — so the result is identical to
        what round 0 of a real negotiation would produce.

        Raises ``ValueError`` if the listing doesn't exist or has no usable
        negotiation strategy. The controller converts these to HTTP 404.
        """
        from market_storefront.models.domain_models import Listing
        from market_storefront.utils.sync_negotiation import _compute_round_zero_decision

        row = await self._db.load_listing(listing_id=listing_id)
        if not row:
            raise ValueError(f"Listing {listing_id} not found")
        listing = Listing.model_validate(row)
        our_price, _strategy_label, direction, strategy_name, decision = (
            _compute_round_zero_decision(
                listing=listing,
                their_proposed_price=their_proposed_price,
            )
        )
        return EvaluateNegotiateResponse(
            listing_id=listing_id,
            our_reference_price=our_price,
            their_proposed_price=their_proposed_price,
            direction=direction,
            strategy=strategy_name,
            decision=decision.action,
            decision_price=decision.price,
            decision_reason=decision.reason,
            would_negotiate=(decision.action != "exit"),
        )

    async def refund(self, listing_id: str, payload: RefundRequest) -> tuple[int, dict]:
        if not self._token_transfers_available:
            return 503, {
                "error": "Token transfer not configured",
                "detail": "AGENT_PRIV_KEY and CHAIN_RPC_URL must both be set in storefront config.",
            }
        order = await self._db.load_listing(listing_id=listing_id)
        from service.clients.token import resolve_token_cached, ERC20TokenMetadata
        def _resolve_token(address: str) -> dict:
            """Resolve a 0x address to metadata for the refund transfer.

            Strict address-only — symbols rejected upstream by RefundRequest
            validation. Unknown addresses get an address-only stub so
            transfer_erc20 can still execute (it only needs the address).
            """
            if not isinstance(address, str) or not address.startswith("0x"):
                raise ValueError(
                    f"token must be a 0x address, got {address!r}"
                )
            meta = resolve_token_cached(address)
            if meta is None:
                meta = ERC20TokenMetadata(
                    symbol="",
                    contract_address=address,
                    decimals=0,
                )
            return meta.model_dump()
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
