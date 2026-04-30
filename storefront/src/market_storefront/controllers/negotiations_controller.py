"""Negotiations controller — HTTP routing for the negotiations API.

This controller is intentionally thin: it extracts and validates HTTP
parameters, delegates all business logic to ``NegotiationService``, and
maps ``NegotiationServiceError`` to the appropriate HTTP status codes.

Business rules (precondition checks, DB orchestration, state machine
transitions) live in ``market_storefront.services.negotiation_service``.

Endpoints
---------
``GET  /api/v1/listings/{listing_id}/negotiations``
``GET  /api/v1/listings/{listing_id}/negotiations/{neg_id}``
``POST /api/v1/listings/{listing_id}/negotiations/{neg_id}/advance``       admin key
``POST /api/v1/listings/{listing_id}/negotiations/{neg_id}/force-accept``  admin key
"""

from __future__ import annotations

import logging

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from market_storefront.services.negotiation_service import (
    NegotiationService,
    NegotiationServiceError,
)

logger = logging.getLogger(__name__)


def _row_to_wire(row: dict) -> dict:
    """Translate negotiation DB rows to the wire vocabulary.

    DB-column ``our_order_id`` → JSON key ``our_listing_id``.
    DB-column ``order_id``     → JSON key ``listing_id``.
    """
    out = dict(row)
    if "our_order_id" in out and "our_listing_id" not in out:
        out["our_listing_id"] = out.pop("our_order_id")
    if "order_id" in out and "listing_id" not in out:
        out["listing_id"] = out.pop("order_id")
    return out


class NegotiationsController:
    def __init__(self, *, sqlite_client) -> None:
        self._service = NegotiationService(sqlite_client=sqlite_client)

    # ------------------------------------------------------------------
    # Pagination helper
    # ------------------------------------------------------------------

    @staticmethod
    def _pagination(request: Request) -> tuple[int, int]:
        try:
            limit = min(int(request.query_params.get("limit", 50)), 200)
        except (ValueError, TypeError):
            limit = 50
        try:
            offset = max(int(request.query_params.get("offset", 0)), 0)
        except (ValueError, TypeError):
            offset = 0
        return limit, offset

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def list_negotiations(self, request: Request) -> JSONResponse:
        """``GET /api/v1/listings/{listing_id}/negotiations``"""
        listing_id = request.path_params["listing_id"]
        limit, offset = self._pagination(request)
        try:
            threads = await self._service.list_for_order(
                order_id=listing_id,
                terminal_state=request.query_params.get("terminal_state") or None,
                buyer_address=request.query_params.get("buyer_address") or None,
                limit=limit,
                offset=offset,
            )
        except NegotiationServiceError as exc:
            return JSONResponse({"error": str(exc)}, status_code=exc.status_code)

        return JSONResponse({
            "listing_id": listing_id,
            "negotiations": [_row_to_wire(t) for t in threads],
            "count": len(threads),
            "limit": limit,
            "offset": offset,
        })

    async def get_negotiation(self, request: Request) -> JSONResponse:
        """``GET /api/v1/listings/{listing_id}/negotiations/{neg_id}``"""
        listing_id = request.path_params["listing_id"]
        neg_id = request.path_params["neg_id"]
        try:
            detail = await self._service.get_detail(
                order_id=listing_id, neg_id=neg_id
            )
        except NegotiationServiceError as exc:
            return JSONResponse({"error": str(exc)}, status_code=exc.status_code)
        return JSONResponse(_row_to_wire(detail))

    async def advance_negotiation(self, request: Request) -> JSONResponse:
        """``POST /api/v1/listings/{listing_id}/negotiations/{neg_id}/advance``"""
        listing_id = request.path_params["listing_id"]
        neg_id = request.path_params["neg_id"]

        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)

        action = body.get("action")
        price_raw = body.get("price")
        price: int | None = None
        if price_raw is not None:
            try:
                price = int(price_raw)
            except (TypeError, ValueError):
                return JSONResponse(
                    {"error": "'price' must be an integer"}, status_code=400
                )

        try:
            result = await self._service.advance(
                order_id=listing_id,
                neg_id=neg_id,
                action=action,
                price=price,
                reason=body.get("reason"),
            )
        except NegotiationServiceError as exc:
            return JSONResponse({"error": str(exc)}, status_code=exc.status_code)
        except Exception as exc:
            logger.error("[CONTROLLER] advance_negotiation unexpected: %s", exc, exc_info=True)
            return JSONResponse(
                {"error": "advance failed", "detail": str(exc)}, status_code=500
            )

        return JSONResponse(_row_to_wire(result))

    async def force_accept_negotiation(self, request: Request) -> JSONResponse:
        """``POST /api/v1/listings/{listing_id}/negotiations/{neg_id}/force-accept``"""
        listing_id = request.path_params["listing_id"]
        neg_id = request.path_params["neg_id"]

        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)

        try:
            price = int(body["price"])
        except (KeyError, TypeError, ValueError):
            return JSONResponse(
                {"error": "'price' (int) is required"}, status_code=400
            )

        try:
            result = await self._service.force_accept(
                order_id=listing_id, neg_id=neg_id, price=price
            )
        except NegotiationServiceError as exc:
            return JSONResponse({"error": str(exc)}, status_code=exc.status_code)
        except Exception as exc:
            logger.error(
                "[CONTROLLER] force_accept_negotiation unexpected: %s", exc, exc_info=True
            )
            return JSONResponse(
                {"error": "force-accept failed", "detail": str(exc)}, status_code=500
            )

        return JSONResponse(_row_to_wire(result))

    # ------------------------------------------------------------------
    # Route factory
    # ------------------------------------------------------------------

    def routes(self) -> list[Route]:
        return [
            Route(
                "/api/v1/listings/{listing_id}/negotiations",
                self.list_negotiations,
                methods=["GET"],
            ),
            Route(
                "/api/v1/listings/{listing_id}/negotiations/{neg_id}",
                self.get_negotiation,
                methods=["GET"],
            ),
            Route(
                "/api/v1/listings/{listing_id}/negotiations/{neg_id}/advance",
                self.advance_negotiation,
                methods=["POST"],
            ),
            Route(
                "/api/v1/listings/{listing_id}/negotiations/{neg_id}/force-accept",
                self.force_accept_negotiation,
                methods=["POST"],
            ),
        ]
