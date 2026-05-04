"""ListingService — listing lifecycle business logic.

Owns all state-mutating listing operations:
  - create_listing()     — policy pipeline → SQLite insert
  - close_listing()      — policy pipeline → SQLite update
  - refund()             — direct ERC-20 transfer to buyer
  - claim()              — seller collects on-chain escrow
  - reclaim()            — buyer reclaims expired escrow
  - arbitrate()          — oracle records arbitration decision
  - discover()           — registry query for matching listings

The ``_run_*_flow`` functions that previously lived in agent.py are
rewritten here as methods that accept typed dicts (all HTTP concerns
stripped). Controllers parse the request, build the dict, call the
service, and map results to HTTP responses.

Dependencies are injected at construction time:
  sqlite_client  — storefront SQLiteClient singleton
  alkahest_client — AlkahestClient | None (None when keys not configured)
  config          — CONFIG singleton
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from market_storefront.models.domain_models import (
    ComputeResource,
    ListingClosedEvent,
    ListingCreatedEvent,
)
from market_storefront.resources import parse_resource_from_dict
from market_storefront.utils.event_ingestion import is_event_queue_enabled, queue_event
from market_storefront.utils.stage_log import stage_event

logger = logging.getLogger(__name__)


class ListingService:
    """Stateful singleton — constructed once at lifespan startup.

    Methods that touch the alkahest client guard against ``None`` and
    return a 500-flavoured error dict rather than raising, so controllers
    can map directly to HTTP responses.
    """

    def __init__(self, *, sqlite_client, alkahest_client, config) -> None:
        self._db = sqlite_client
        self._alkahest = alkahest_client
        self._config = config

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_token_resource(resource_payload: dict) -> dict:
        """Resolve token symbol/dict → full ERC20TokenMetadata dict and scale amount."""
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
                    raise ValueError("Token metadata must include symbol/contract_address/decimals")
            else:
                raise ValueError("Token must be a symbol or contract address")
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
            raise ValueError("Amount has too many decimal places for token")

        normalized = dict(resource_payload)
        normalized["token"] = token_dump
        normalized["amount"] = int(raw)
        return normalized

    def _require_alkahest(self) -> tuple[int, dict] | None:
        """Return an error tuple if alkahest is not configured, else None."""
        if self._alkahest is None:
            return 500, {
                "error": "Alkahest client not configured",
                "detail": "AGENT_PRIV_KEY and CHAIN_RPC_URL must both be set",
            }
        return None

    # ------------------------------------------------------------------
    # Policy-pipeline listing operations (create / close)
    # These build a domain event and push it through the pipeline.
    # The actual SQLite writes are performed by action_executor as part
    # of the MAKE_OFFER / CLOSE_ORDER action handlers.
    # ------------------------------------------------------------------

    async def create_listing(self, body: dict, pipeline_service) -> dict:
        """Run the create-listing policy pipeline.

        Parameters
        ----------
        body:
            Dict with keys: offer, demand, max_duration_seconds, paused.
        pipeline_service:
            PolicyPipelineService singleton — called to run the event
            through the reactive pipeline.

        Returns
        -------
        Pipeline result dict with keys: status, event_id, listing_request,
        and optionally listing_id.

        Raises
        ------
        ValueError
            On invalid offer/demand resources.
        """
        from service.clients.token import TOKEN_REGISTRY

        offer_data = body.get("offer")
        demand_data = body.get("demand")
        if offer_data is None or demand_data is None:
            raise ValueError("Request must include both 'offer' and 'demand'")

        try:
            offer_resource = parse_resource_from_dict(
                self._normalize_token_resource(offer_data)
            )
            demand_resource = parse_resource_from_dict(
                self._normalize_token_resource(demand_data)
            )
        except Exception as exc:
            raise ValueError(f"Invalid offer/demand resource: {exc}") from exc

        from market_storefront.resources import TokenResource as _TR
        if not (
            (isinstance(offer_resource, ComputeResource) and isinstance(demand_resource, _TR))
            or (isinstance(offer_resource, _TR) and isinstance(demand_resource, ComputeResource))
        ):
            raise ValueError("Offer and demand must be one compute and one token resource")

        base_url = self._config.base_url_override or ""
        max_duration = body.get("max_duration_seconds")
        create_paused = bool(body.get("paused", False))
        event_id = f"order_create_{uuid.uuid4()}"

        event = ListingCreatedEvent(
            event_id=event_id,
            source=base_url,
            offer=offer_resource,
            demand=demand_resource,
            max_duration_seconds=max_duration,
            data={
                "offer": offer_resource.model_dump(mode="json"),
                "demand": demand_resource.model_dump(mode="json"),
                "max_duration_seconds": max_duration,
                "paused": create_paused,
            },
        )

        if is_event_queue_enabled():
            queue_event(event.model_dump(mode="json"))
            return {
                "status": "queued",
                "event_id": event_id,
                "listing_request": event.model_dump(mode="json"),
            }

        final_response = await pipeline_service.process_event(event)
        outcome = pipeline_service.pop_outcome(event_id)
        listing_id = _extract_listing_id(outcome)

        result: dict[str, Any] = {
            "status": "created" if listing_id else "no_action",
            "event_id": event_id,
            "listing_request": event.model_dump(mode="json"),
            "root_agent_response": final_response or "",
        }
        if listing_id:
            result["listing_id"] = listing_id
        return result

    async def close_listing(self, listing_id: str, pipeline_service) -> dict:
        """Run the close-listing policy pipeline."""
        base_url = self._config.base_url_override or ""
        event_id = f"order_close_{uuid.uuid4()}"

        event = ListingClosedEvent(
            event_id=event_id,
            source=base_url,
            listing_id=listing_id,
            data={"listing_id": listing_id},
        )

        if is_event_queue_enabled():
            queue_event(event.model_dump(mode="json"))
            return {
                "status": "queued",
                "event_id": event_id,
                "listing_request": event.model_dump(mode="json"),
            }

        final_response = await pipeline_service.process_event(event)
        return {
            "status": "closed",
            "event_id": event_id,
            "listing_request": event.model_dump(mode="json"),
            "root_agent_response": final_response or "",
        }

    # ------------------------------------------------------------------
    # Escrow operations (refund / claim / reclaim / arbitrate)
    # ------------------------------------------------------------------

    async def refund(self, payload: dict) -> tuple[int, dict]:
        """Provider-initiated direct token-transfer refund.

        Does NOT touch the escrow contract — this is a side-channel
        make-whole transfer out of the provider's own wallet.

        Returns (status_code, body_dict).
        """
        priv_key = (self._config.agent_priv_key or "").strip()
        rpc_url = (self._config.chain_rpc_url or "").strip()
        if not priv_key:
            return 500, {"error": "AGENT_PRIV_KEY not configured on agent"}
        if not rpc_url:
            return 500, {"error": "CHAIN_RPC_URL not configured on agent"}

        listing_id_peek = payload.get("listing_id") if isinstance(payload, dict) else None
        order = None
        if isinstance(listing_id_peek, str) and listing_id_peek.strip():
            order = await self._db.load_listing(listing_id=listing_id_peek.strip())

        from service.clients.token import TOKEN_REGISTRY

        def _resolve_token(ident: str) -> dict:
            try:
                meta = TOKEN_REGISTRY.require(ident)
            except Exception as exc:
                raise ValueError(f"Unknown token: {ident}") from exc
            return meta.model_dump() if hasattr(meta, "model_dump") else dict(meta)

        from market_storefront.utils.refund import derive_refund_params
        outcome = derive_refund_params(order=order, payload=payload, resolve_token=_resolve_token)
        if outcome[0] == "error":
            _, status, body = outcome
            return status, body
        params = outcome[1]

        from market_storefront.utils.token_transfer import transfer_erc20
        try:
            result = await transfer_erc20(
                private_key=priv_key,
                rpc_url=rpc_url,
                token_address=params["token_address"],
                to_address=params["buyer_address"],
                amount_raw=params["amount_raw"],
            )
        except RuntimeError as exc:
            logger.error("[REFUND] Transfer failed for listing %s: %s", params["listing_id"], exc)
            return 502, {"error": "Token transfer failed", "detail": str(exc)}

        await self._db.update_listing(
            listing_id=params["listing_id"],
            status="refunded",
            updated_at=datetime.now().isoformat(),
        )
        stage_event(
            "post_settlement", "refund_transferred",
            listing_id=params["listing_id"],
            escrow_uid=params.get("escrow_uid"),
            tx_hash=result["tx_hash"],
            token_symbol=params["token_meta"].get("symbol"),
            token_address=params["token_meta"].get("contract_address"),
            to_address=result["to_address"],
            amount_raw=params["amount_raw"],
        )
        return 200, {
            "status": "refunded",
            "listing_id": params["listing_id"],
            "tx_hash": result["tx_hash"],
            "from_address": result["from_address"],
            "to_address": result["to_address"],
            "token": {
                "symbol": params["token_meta"].get("symbol"),
                "contract_address": params["token_meta"].get("contract_address"),
                "decimals": params["decimals"],
            },
            "amount_raw": params["amount_raw"],
            "block_number": result["block_number"],
        }

    async def claim(self, payload: dict) -> tuple[int, dict]:
        """Seller collects an on-chain escrow after fulfillment."""
        err = self._require_alkahest()
        if err:
            return err

        listing_id_peek = payload.get("listing_id") if isinstance(payload, dict) else None
        order = None
        if isinstance(listing_id_peek, str) and listing_id_peek.strip():
            order = await self._db.load_listing(listing_id=listing_id_peek.strip())

        from market_storefront.utils.recovery import derive_claim_params
        outcome = derive_claim_params(order=order, payload=payload)
        if outcome[0] == "error":
            _, status, body = outcome
            return status, body
        params = outcome[1]

        try:
            collect_result = await self._alkahest.erc20.escrow.non_tierable.collect(
                params["escrow_uid"], params["fulfillment_uid"],
            )
        except Exception as exc:
            logger.error("[CLAIM] collect failed for listing %s: %s", params["listing_id"], exc)
            return 502, {
                "error": "Escrow collect failed on-chain",
                "detail": str(exc),
                "listing_id": params["listing_id"],
                "escrow_uid": params["escrow_uid"],
            }

        await self._db.update_listing(
            listing_id=params["listing_id"],
            status="closed",
            updated_at=datetime.now().isoformat(),
        )
        stage_event(
            "post_settlement", "escrow_claimed",
            listing_id=params["listing_id"],
            escrow_uid=params["escrow_uid"],
            fulfillment_uid=params["fulfillment_uid"],
            collect_result=str(collect_result),
        )
        return 200, {
            "status": "claimed",
            "listing_id": params["listing_id"],
            "escrow_uid": params["escrow_uid"],
            "fulfillment_uid": params["fulfillment_uid"],
            "collect_result": str(collect_result),
        }

    async def reclaim(self, payload: dict) -> tuple[int, dict]:
        """Buyer reclaims an expired on-chain escrow."""
        err = self._require_alkahest()
        if err:
            return err

        listing_id_peek = payload.get("listing_id") if isinstance(payload, dict) else None
        order = None
        if isinstance(listing_id_peek, str) and listing_id_peek.strip():
            order = await self._db.load_listing(listing_id=listing_id_peek.strip())

        from market_storefront.utils.recovery import derive_reclaim_params
        outcome = derive_reclaim_params(order=order, payload=payload)
        if outcome[0] == "error":
            _, status, body = outcome
            return status, body
        params = outcome[1]

        try:
            reclaim_result = await self._alkahest.erc20.escrow.non_tierable.reclaim_expired(
                params["escrow_uid"],
            )
        except Exception as exc:
            logger.error("[RECLAIM] reclaim_expired failed for listing %s: %s", params["listing_id"], exc)
            return 502, {
                "error": "Escrow reclaim failed on-chain",
                "detail": str(exc),
                "listing_id": params["listing_id"],
                "escrow_uid": params["escrow_uid"],
            }

        await self._db.update_listing(
            listing_id=params["listing_id"],
            status="reclaimed",
            updated_at=datetime.now().isoformat(),
        )
        stage_event(
            "post_settlement", "escrow_reclaimed",
            listing_id=params["listing_id"],
            escrow_uid=params["escrow_uid"],
            reclaim_result=str(reclaim_result),
        )
        return 200, {
            "status": "reclaimed",
            "listing_id": params["listing_id"],
            "escrow_uid": params["escrow_uid"],
            "reclaim_result": str(reclaim_result),
        }

    async def arbitrate(self, payload: dict) -> tuple[int, dict]:
        """Buyer-as-oracle records an arbitration decision (no-op under RecipientArbiter)."""
        err = self._require_alkahest()
        if err:
            return err

        listing_id_peek = payload.get("listing_id") if isinstance(payload, dict) else None
        order = None
        if isinstance(listing_id_peek, str) and listing_id_peek.strip():
            order = await self._db.load_listing(listing_id=listing_id_peek.strip())

        from market_storefront.utils.recovery import derive_arbitrate_params
        outcome = derive_arbitrate_params(order=order, payload=payload)
        if outcome[0] == "error":
            _, status, body = outcome
            return status, body
        params = outcome[1]

        try:
            from alkahest_py import ArbitrationMode
            decision_value = bool(params["decision"])

            async def decision_function(_attestation, _demand):
                return decision_value

            decisions = await self._alkahest.oracle.arbitrate_many(
                decision_function,
                lambda _d: None,
                ArbitrationMode.PastUnarbitrated,
                timeout_seconds=5.0,
            )
        except Exception as exc:
            logger.error("[ARBITRATE] arbitrate_many failed for listing %s: %s", params["listing_id"], exc)
            return 502, {
                "error": "Oracle arbitration failed on-chain",
                "detail": str(exc),
                "listing_id": params["listing_id"],
            }

        stage_event(
            "post_settlement", "oracle_arbitrated",
            listing_id=params["listing_id"],
            fulfillment_uid=params["fulfillment_uid"],
            escrow_uid=params["escrow_uid"],
            decision=params["decision"],
            decisions_count=len(decisions or []) if decisions is not None else 0,
        )
        return 200, {
            "status": "arbitrated",
            "listing_id": params["listing_id"],
            "fulfillment_uid": params["fulfillment_uid"],
            "decision": params["decision"],
            "decisions_count": len(decisions or []) if decisions is not None else 0,
            "note": (
                "Under RecipientArbiter this decision does not gate escrow collection; "
                "use /listings/claim to release funds."
            ),
        }

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    async def discover(self, payload: dict) -> tuple[int, dict]:
        """Query the registry for listings matching a local listing."""
        listing_id = payload.get("listing_id")
        if not isinstance(listing_id, str) or not listing_id.strip():
            raise ValueError("Request must include non-empty 'listing_id'")
        listing_id = listing_id.strip()
        include_active = bool(payload.get("include_active", False))

        from market_storefront.utils.action_executor import discover as _discover
        try:
            matches = await _discover(
                order_id=listing_id,
                include_active_negotiations=include_active,
            )
        except ValueError as exc:
            return 400, {"error": "Discover request invalid", "detail": str(exc), "listing_id": listing_id}
        except RuntimeError as exc:
            return 500, {"error": "Discovery unavailable", "detail": str(exc), "listing_id": listing_id}

        return 200, {
            "listing_id": listing_id,
            "match_count": len(matches),
            "matches": matches,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_listing_id(outcome: dict | None) -> str | None:
    if not isinstance(outcome, dict):
        return None
    if outcome.get("listing_id"):
        return outcome["listing_id"]
    result = outcome.get("result")
    if isinstance(result, dict):
        return result.get("listing_id") or (result.get("listing") or {}).get("listing_id")
    return None
