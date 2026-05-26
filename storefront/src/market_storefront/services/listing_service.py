"""ListingService — synchronous listing lifecycle orchestrator.

Each public method is a procedural sequence of steps directly against
SQLite + the registry client. No policy layer for listing CRUD — the
seller's intent (offer + accepted escrows + duration + paused flag) is
the only input the storefront needs to act on.

Startup validation: config prerequisites for escrow operations are checked
at construction time so failures are visible immediately rather than per-call.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from market_storefront.models.listing_models import (
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

logger = logging.getLogger(__name__)


class ListingService:
    def __init__(self, *, sqlite_client, alkahest_client) -> None:
        from market_storefront.utils.config import settings

        self._db = sqlite_client
        self._alkahest = alkahest_client

        priv_key = (settings.wallet.private_key or "").strip()
        rpc_url = (settings.chain.rpc_url or "").strip()
        self._token_transfers_available: bool = bool(priv_key and rpc_url)
        self._alkahest_available: bool = alkahest_client is not None

        if not self._token_transfers_available:
            logger.warning(
                "[STOREFRONT] Token transfer operations (refund) unavailable — "
                "wallet.private_key and chain.rpc_url must both be set in storefront config."
            )
        if not self._alkahest_available:
            logger.warning(
                "[STOREFRONT] On-chain escrow operations (claim, reclaim, arbitrate) unavailable — "
                "wallet.private_key and chain.rpc_url must both be set in storefront config."
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
        self, request: CreateListingRequest
    ) -> CreateListingResponse:
        """Validate the seller's create request, mint a listing_id, write the
        local row, and (unless paused) publish to the registry.

        ``paused=True`` writes the local row with ``paused=1`` and skips the
        registry publish; the operator unblocks via
        ``POST /api/v1/listings/{id}/resume`` which clears the flag and runs
        the same ``publish_order_to_registry`` path.
        """
        from market_storefront.models.domain_models import Listing
        from market_storefront.utils.action_executor import publish_order_to_registry
        from market_storefront.utils.config import BASE_URL_OVERRIDE

        offer, accepted_escrows = self._parse_offer_and_escrows(request)

        listing = Listing(
            listing_id=str(uuid.uuid4()),
            seller=BASE_URL_OVERRIDE,
            offer_resource=offer,
            accepted_escrows=accepted_escrows,
            max_duration_seconds=request.max_duration_seconds,
            oracle_address=None,
        )
        listing_dict = listing.model_dump(mode="json")
        listing_id = listing.listing_id

        now_iso = datetime.now().isoformat()
        try:
            await self._db.upsert_listing(
                listing_id=listing_id,
                status="open",
                created_at=now_iso,
                updated_at=now_iso,
                offer_resource=listing_dict.get("offer_resource"),
                accepted_escrows=listing_dict.get("accepted_escrows"),
                fulfillment_resource=None,
                max_duration_seconds=listing_dict.get("max_duration_seconds"),
                seller=listing_dict.get("seller") or BASE_URL_OVERRIDE,
                oracle_address=listing_dict.get("oracle_address"),
                paused=bool(request.paused),
            )
        except Exception as exc:
            logger.error("[LISTINGS] upsert_listing %s failed: %s", listing_id, exc)
            raise

        if request.paused:
            logger.info(
                "[LISTINGS] %s created locally with paused=True; skipping registry publish",
                listing_id,
            )
            return CreateListingResponse(status="created", listing_id=listing_id)

        publish_result = await publish_order_to_registry(listing_dict)
        return CreateListingResponse(
            status="created",
            listing_id=listing_id,
            root_agent_response=publish_result.get(
                "message", f"Listing {listing_id} ({publish_result.get('status')})"
            ),
        )

    async def close_listing(self, listing_id: str) -> CloseListingResponse:
        """Mark the listing closed locally; if registry discovery is enabled,
        send the same status update to every registry the listing was published to.

        Local close is best-effort: a registry-update failure logs but does not
        roll back the SQLite write — the seller's local state is the source of
        truth for what's available to negotiate against.
        """
        from market_storefront.utils.action_executor import close_order

        result = await close_order({"listing_id": listing_id})
        return CloseListingResponse(
            status=result.get("status", "closed"), listing_id=listing_id,
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
        from market_storefront.utils.config import settings
        from market_storefront.utils.token_transfer import transfer_erc20
        try:
            result = await transfer_erc20(
                private_key=settings.wallet.private_key.strip(),
                rpc_url=settings.chain.rpc_url.strip(),
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
