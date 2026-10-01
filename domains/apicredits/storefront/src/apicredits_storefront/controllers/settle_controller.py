"""Settle an API-credit deal and deliver its issued credentials.

Alkahest submissions are escrow-verified by the servicing coordinator.
Arkhai payments submissions are keyed by the deterministic transaction ID
and issue credits only after the exact accepted Agreement has a matching
signed receipt.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi_utils.cbv import cbv

import apicredits_storefront.container as _container
from apicredits_storefront.middleware import buyer_auth
from apicredits_storefront.middleware.admin_auth import require_admin_principal
from apicredits_storefront.domain_runtime import (
    serialize_api_credit_settlement,
    serialize_api_credit_settlement_start,
)
from core_storefront.models.settle_models import (
    SettleResponse,
    SettleStatusResponse,
    SettleWaitResponse,
)
from apicredits_storefront.settlement_models import ApiCreditsSettleRequest
from domains.apicredits.settlement import (
    CONFIG_KEY,
    MECHANISM_ID,
    mandate_policy_from_agreement,
)
from market_arkhai_payments import (
    PaymentsOptionParams,
    derive_mandate,
    transaction_id as derive_transaction_id,
    verify_receipt,
    PaymentsPollTimeout,
)
from market_core.schemas import Agreement
from market_identity import Identity


logger = logging.getLogger(__name__)

_payment_locks: dict[str, asyncio.Lock] = {}

router = APIRouter(prefix="/api/v1/settle", tags=["settle"])


@cbv(router)
class SettleController:
    def __init__(
        self,
        db=Depends(lambda: _container.resolved_sqlite_client),
        settlement_coordinator=Depends(
            lambda: _container.resolved_settlement_coordinator
        ),
    ) -> None:
        self._db = db
        self._settlement_coordinator = settlement_coordinator

    async def _settle_payment(
        self, negotiation_id: str, body: ApiCreditsSettleRequest, signer: Any
    ) -> Any:
        composition = _container.resolved_settlement_composition
        if composition is None:
            raise HTTPException(
                status_code=503, detail="settlement composition is not initialized"
            )
        if negotiation_id != body.negotiation_id:
            raise HTTPException(
                status_code=400, detail="payment settlement is keyed by negotiation ID"
            )
        thread = await self._db.load_negotiation_thread_row(
            negotiation_id=negotiation_id
        )
        if not thread or thread.get("terminal_state") != "success":
            raise HTTPException(
                status_code=409, detail="accepted negotiation is unavailable"
            )
        stored_bytes = thread.get("agreement_bytes")
        if isinstance(stored_bytes, memoryview):
            stored_bytes = stored_bytes.tobytes()
        if isinstance(stored_bytes, str):
            stored_bytes = stored_bytes.encode("utf-8")
        if not isinstance(stored_bytes, bytes):
            raise HTTPException(
                status_code=409, detail="accepted Agreement is unavailable"
            )
        try:
            agreement_json = json.loads(stored_bytes)
            agreement = Agreement.model_validate(agreement_json)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=409, detail="stored Agreement is invalid"
            ) from exc
        buyer = Identity.model_validate(thread.get("buyer_principal"))
        seller = Identity.model_validate(thread.get("seller_principal"))
        if buyer != body.buyer_principal or seller != signer.identity:
            raise HTTPException(
                status_code=403, detail="settlement parties do not match negotiation"
            )
        if (
            agreement.negotiation_id != negotiation_id
            or agreement.buyer != buyer
            or agreement.seller != seller
        ):
            raise HTTPException(
                status_code=409, detail="Agreement parties or negotiation do not match"
            )
        if (
            agreement.settlement is None
            or agreement.settlement.mechanism != MECHANISM_ID
        ):
            raise HTTPException(
                status_code=400, detail="Agreement does not select Arkhai payments"
            )
        settlement_data = thread.get("settlement_data")
        if not isinstance(settlement_data, Mapping):
            raise HTTPException(
                status_code=409, detail="accepted payment mandate is unavailable"
            )
        stored_mandate = settlement_data.get("mandate")
        if not isinstance(stored_mandate, Mapping):
            raise HTTPException(
                status_code=409, detail="accepted payment mandate is malformed"
            )
        stored_transaction_id = settlement_data.get("transaction_id")
        if not isinstance(stored_transaction_id, str) or not stored_transaction_id:
            raise HTTPException(
                status_code=409, detail="accepted payment transaction is unavailable"
            )
        payment_config = composition.settlement_config.mechanism_config(CONFIG_KEY)
        if payment_config is None or not getattr(payment_config, "enabled", False):
            raise HTTPException(
                status_code=503, detail="Arkhai payments is not enabled"
            )
        try:
            policy = mandate_policy_from_agreement(
                agreement_json,
                fee_bps=payment_config.fee_bps,
                dispute_authority=payment_config.dispute_authority,
            )
            expected_mandate = derive_mandate(agreement_json, policy)
            expected_transaction_id = derive_transaction_id(expected_mandate)
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=409, detail="Agreement cannot produce a payment mandate"
            ) from exc
        expected_wire = expected_mandate.model_dump(
            mode="json", by_alias=True, exclude_none=True
        )
        if (
            dict(stored_mandate) != expected_wire
            or stored_transaction_id != expected_transaction_id
        ):
            raise HTTPException(
                status_code=409,
                detail="stored payment mandate differs from the accepted Agreement",
            )
        if body.settlement_mechanism not in (None, MECHANISM_ID):
            raise HTTPException(
                status_code=400,
                detail="settlement mechanism conflicts with accepted Agreement",
            )
        existing = await self._db.load_escrow(escrow_uid=negotiation_id)
        if existing is not None and existing.get("status") in ("ready", "failed"):
            serialized = serialize_api_credit_settlement(existing)
            serialized["settlement_ref"] = expected_transaction_id
            serialized["buyer_principal"] = buyer.model_dump(mode="json")
            serialized["seller_principal"] = seller.model_dump(mode="json")
            return JSONResponse(content=serialized, status_code=200)
        terms = await self._db.load_credit_terms(negotiation_id=negotiation_id)
        listing_id = thread.get("our_listing_id")
        order = (
            await self._db.load_listing(listing_id=listing_id) if listing_id else None
        )
        if not terms or not order:
            raise HTTPException(
                status_code=409, detail="credit provisioning terms are unavailable"
            )
        fulfillment = composition.domain.fulfillment
        if fulfillment is None:
            raise HTTPException(
                status_code=503, detail="API-credit fulfillment is unavailable"
            )
        if existing is None:
            inserted = await self._db.insert_escrow(
                escrow_uid=negotiation_id,
                negotiation_id=negotiation_id,
                chain_name=None,
                escrow_address=None,
                is_primary=True,
                status="provisioning",
            )
            existing = await self._db.load_escrow(escrow_uid=negotiation_id)
            if not inserted and existing is None:
                raise HTTPException(
                    status_code=409, detail="payment settlement could not be reserved"
                )
        payments_client = composition.payments_client
        if payments_client is None:
            raise HTTPException(
                status_code=503, detail="Arkhai payments client is unavailable"
            )
        try:
            snapshot = await asyncio.to_thread(
                payments_client.poll,
                expected_transaction_id,
                timeout=30.0,
                interval=0.5,
            )
        except PaymentsPollTimeout:
            pending = await self._db.load_escrow(escrow_uid=negotiation_id)
            serialized = serialize_api_credit_settlement_start(
                pending
                or {
                    "escrow_uid": negotiation_id,
                    "negotiation_id": negotiation_id,
                    "status": "provisioning",
                }
            )
            serialized["settlement_ref"] = expected_transaction_id
            serialized["buyer_principal"] = buyer.model_dump(mode="json")
            serialized["seller_principal"] = seller.model_dump(mode="json")
            return JSONResponse(content=serialized, status_code=202)
        except Exception as exc:
            logger.warning(
                "Arkhai payments polling failed for %s: %s",
                expected_transaction_id,
                exc,
            )
            raise HTTPException(
                status_code=502, detail="payments service receipt is unavailable"
            ) from exc
        if not verify_receipt(
            snapshot.snapshot.receipt,
            payment_config.service_identity,
            mandate=expected_mandate,
            agreement_json=agreement_json,
        ):
            raise HTTPException(
                status_code=400, detail="payments receipt does not prove this Agreement"
            )
        option = PaymentsOptionParams.model_validate(agreement.settlement.params)
        try:
            await asyncio.to_thread(
                payments_client.ensure_agreement_attached,
                expected_transaction_id,
                agreement_json,
                option,
            )
        except Exception as exc:
            logger.warning(
                "Could not attach API-credit Agreement for %s: %s",
                expected_transaction_id,
                exc,
            )
            raise HTTPException(
                status_code=502, detail="payments Agreement attachment is unavailable"
            ) from exc
        try:
            result = await fulfillment.fulfill(
                client=None,
                escrow_uid=negotiation_id,
                order=order,
                quantity=int(terms["quantity"]),
                key_mode=str(terms.get("key_mode") or "new"),
                key_id=terms.get("key_id"),
                buyer_principal=buyer,
                listing_id=listing_id,
                negotiation_id=negotiation_id,
                mechanism=MECHANISM_ID,
                authoritative_gate="payments_receipt_verified",
            )
        except Exception as exc:
            logger.warning(
                "API-credit issuance for payment %s is retryable after error: %s",
                negotiation_id,
                exc,
            )
            result = {
                "status": "pending",
                "message": f"Credit issuance outcome is uncertain: {exc}",
            }
        if result.get("status") == "fulfilled":
            await self._db.update_escrow(
                escrow_uid=negotiation_id,
                status="ready",
                fulfillment_uid=result.get("fulfillment_uid"),
                connection_details=result.get("connection_details"),
                tenant_credentials=(
                    json.dumps(result["tenant_credentials"])
                    if isinstance(result.get("tenant_credentials"), Mapping)
                    else None
                ),
            )
        elif result.get("status") == "pending":
            pending = await self._db.load_escrow(escrow_uid=negotiation_id)
            serialized = serialize_api_credit_settlement_start(
                pending
                or {
                    "escrow_uid": negotiation_id,
                    "negotiation_id": negotiation_id,
                    "status": "provisioning",
                }
            )
            serialized["settlement_ref"] = expected_transaction_id
            serialized["buyer_principal"] = buyer.model_dump(mode="json")
            serialized["seller_principal"] = seller.model_dump(mode="json")
            serialized["reason"] = result.get("message")
            return JSONResponse(content=serialized, status_code=202)
        else:
            reason = str(result.get("message") or "credit issuance failed")
            await self._db.update_escrow(
                escrow_uid=negotiation_id, status="failed", reason=reason
            )
            try:
                await asyncio.to_thread(
                    payments_client.reverse, expected_transaction_id
                )
            except Exception:
                logger.exception(
                    "Could not reverse failed API-credit payment %s",
                    expected_transaction_id,
                )
        row = await self._db.load_escrow(escrow_uid=negotiation_id)
        serialized = serialize_api_credit_settlement(
            row
            or {
                "escrow_uid": negotiation_id,
                "negotiation_id": negotiation_id,
                "status": "failed",
            }
        )
        serialized["settlement_ref"] = expected_transaction_id
        serialized["buyer_principal"] = buyer.model_dump(mode="json")
        serialized["seller_principal"] = seller.model_dump(mode="json")
        return JSONResponse(
            content=serialized,
            status_code=200 if serialized.get("status") in ("ready", "failed") else 202,
        )

    @router.post(
        "/{escrow_uid}",
        response_model=SettleResponse,
        summary="Submit settlement / kick off token issuance",
        description="Buyer-facing. Requires marketplace request-signature version 2 headers.",
    )
    async def settle_escrow(
        self,
        escrow_uid: str,
        body: ApiCreditsSettleRequest,
        request: Request,
    ) -> Any:
        from market_alkahest.escrow_verification import EscrowVerificationError

        signer = _container.resolved_marketplace_signer
        if signer is None:
            raise HTTPException(status_code=503, detail="storefront is not initialized")
        await buyer_auth._verify(
            request,
            "settle_escrow",
            escrow_uid,
            expected_principal=body.buyer_principal,
            body=body,
        )
        thread = await self._db.load_negotiation_thread_row(
            negotiation_id=body.negotiation_id
        )
        mechanism = body.settlement_mechanism or "alkahest.v1"
        if thread is not None:
            raw_agreement = thread.get("agreement_bytes")
            if isinstance(raw_agreement, memoryview):
                raw_agreement = raw_agreement.tobytes()
            try:
                agreement = Agreement.model_validate(json.loads(raw_agreement))
            except (TypeError, ValueError):
                agreement = None
            if agreement is not None and agreement.settlement is not None:
                mechanism = agreement.settlement.mechanism
        if (
            body.settlement_mechanism is not None
            and body.settlement_mechanism != mechanism
        ):
            raise HTTPException(
                status_code=400,
                detail="settlement mechanism conflicts with accepted Agreement",
            )
        if mechanism == MECHANISM_ID:
            if escrow_uid != body.negotiation_id:
                raise HTTPException(
                    status_code=400,
                    detail="payments settlement is keyed by negotiation ID",
                )
            lock = _payment_locks.setdefault(body.negotiation_id, asyncio.Lock())
            async with lock:
                return await self._settle_payment(body.negotiation_id, body, signer)
        if mechanism != "alkahest.v1":
            raise HTTPException(
                status_code=400, detail="unsupported settlement mechanism"
            )

        alkahest = _container.get_alkahest_client(body.chain_name)
        if not body.chain_name:
            raise HTTPException(
                status_code=422, detail="chain_name is required for Alkahest"
            )
        if alkahest is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"chain {body.chain_name!r} not configured on this "
                    f"storefront — available chains: "
                    f"{sorted(_container.configured_chain_names())}"
                ),
            )
        try:
            result = await self._settlement_coordinator.start(
                escrow_uid=escrow_uid,
                negotiation_id=body.negotiation_id,
                mechanism_client=alkahest,
                chain_name=body.chain_name,
                request=body,
            )
        except EscrowVerificationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            logger.error(
                "[SETTLE] settlement coordinator failed: %s",
                exc,
                exc_info=True,
            )
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        serialized = (
            serialize_api_credit_settlement(result)
            if "created_at" in result
            else serialize_api_credit_settlement_start(result)
        )
        serialized["buyer_principal"] = body.buyer_principal.model_dump(mode="json")
        serialized["seller_principal"] = signer.identity.model_dump(mode="json")
        status_code = 200 if result.get("status") in ("ready", "failed") else 202
        return JSONResponse(content=serialized, status_code=status_code)

    @router.get(
        "/{escrow_uid}/status",
        response_model=SettleStatusResponse,
        summary="Poll settlement status",
        description="Buyer-facing. Requires marketplace request-signature version 2 headers.",
    )
    async def settle_status(
        self,
        escrow_uid: str,
        request: Request,
    ) -> SettleStatusResponse:
        job = await self._db.load_escrow(escrow_uid=escrow_uid)
        if not job:
            raise HTTPException(
                status_code=404,
                detail=f"No settlement job for settlement {escrow_uid}",
            )
        negotiation_id = str(job["negotiation_id"])
        thread = await self._db.load_negotiation_thread_row(
            negotiation_id=negotiation_id
        )
        if not thread:
            raise HTTPException(
                status_code=409, detail="settlement negotiation is missing"
            )
        buyer_principal = Identity.model_validate(thread.get("buyer_principal"))
        await buyer_auth._verify(
            request,
            "settle_status",
            escrow_uid,
            expected_principal=buyer_principal,
        )
        signer = _container.resolved_marketplace_signer
        if signer is None:
            raise HTTPException(status_code=503, detail="storefront is not initialized")
        agreement = None
        stored_bytes = thread.get("agreement_bytes")
        if isinstance(stored_bytes, memoryview):
            stored_bytes = stored_bytes.tobytes()
        if stored_bytes:
            try:
                agreement = Agreement.model_validate(json.loads(stored_bytes))
            except (TypeError, ValueError):
                agreement = None
        if (
            agreement is not None
            and agreement.settlement is not None
            and agreement.settlement.mechanism == MECHANISM_ID
            and job.get("status") not in ("ready", "failed")
        ):
            lock = _payment_locks.setdefault(negotiation_id, asyncio.Lock())
            async with lock:
                try:
                    await self._settle_payment(
                        negotiation_id,
                        ApiCreditsSettleRequest(
                            negotiation_id=negotiation_id,
                            buyer_principal=buyer_principal,
                        ),
                        signer,
                    )
                except HTTPException as exc:
                    if exc.status_code < 500:
                        raise
                    logger.warning(
                        "Payment settlement retry for %s is pending: %s",
                        negotiation_id,
                        exc.detail,
                    )
            job = await self._db.load_escrow(escrow_uid=escrow_uid) or job
        serialized = serialize_api_credit_settlement(job)
        if (
            agreement is not None
            and agreement.settlement is not None
            and agreement.settlement.mechanism == MECHANISM_ID
        ):
            settlement_data = thread.get("settlement_data")
            if isinstance(settlement_data, Mapping):
                serialized["settlement_ref"] = settlement_data.get("transaction_id")
        serialized["buyer_principal"] = buyer_principal.model_dump(mode="json")
        serialized["seller_principal"] = signer.identity.model_dump(mode="json")
        return SettleStatusResponse(**serialized)


admin_settle_router = APIRouter(prefix="/api/v1/admin/settle", tags=["admin-settle"])


@cbv(admin_settle_router)
class AdminSettleController:
    def __init__(
        self,
        db=Depends(lambda: _container.resolved_sqlite_client),
        _key=Depends(require_admin_principal),
    ) -> None:
        self._db = db

    @admin_settle_router.get(
        "/{escrow_uid}/wait",
        response_model=SettleWaitResponse,
        summary="Long-poll until settlement reaches a terminal state (admin)",
    )
    async def wait_for_settlement(
        self,
        escrow_uid: str,
        timeout: float = Query(
            default=60.0,
            gt=0,
            le=120,
            description="Maximum seconds to wait (server-enforced, max 120)",
        ),
    ) -> SettleWaitResponse:
        _terminal = {"ready", "failed"}
        start = time.monotonic()
        deadline = start + timeout

        while True:
            job = await self._db.load_escrow(escrow_uid=escrow_uid)
            elapsed_ms = int((time.monotonic() - start) * 1000)
            status = (job or {}).get("status", "")

            if status in _terminal:
                return SettleWaitResponse(
                    ready=True,
                    status=status,
                    elapsed_ms=elapsed_ms,
                )

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            await asyncio.sleep(min(1.0, remaining))

        elapsed_ms = int((time.monotonic() - start) * 1000)
        job = await self._db.load_escrow(escrow_uid=escrow_uid)
        return SettleWaitResponse(
            ready=False,
            status=(job or {}).get("status", "unknown"),
            elapsed_ms=elapsed_ms,
        )
