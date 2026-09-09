"""Authenticated contact finalization over the role-owned transaction seam."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from . import delivery_state as state
from .delivery_contract import (
    ContactDeliveryConfig,
    FinalizationCancel,
    IntroductionFinalize,
    IntroductionReview,
    finalization_resource,
)
from .introduction_routes import (
    IntroductionRouteError,
    IntroductionRouteService,
    IntroductionStart,
)


class ContactDeliveryRouteService(IntroductionRouteService):
    def __init__(
        self,
        *,
        transaction: Any,
        snapshot: Callable[[Any], tuple[dict[str, str], ContactDeliveryConfig | None]],
        **kwargs: Any,
    ) -> None:
        super().__init__(allow_missing_seller=True, **kwargs)
        self.transaction = transaction
        self.snapshot = snapshot

    def _snapshot(self, agreement: Any) -> tuple[dict[str, str], ContactDeliveryConfig]:
        contact, config = self.snapshot(agreement)
        if not contact or config is None:
            raise state.fail("delivery_configuration_unavailable", 503)
        return contact, config

    async def review(self, context: Any, request: IntroductionReview) -> Any:
        agreement = await self._prepare(request.negotiation_id, request.obligation_ref)
        auth = await self._callbacks.authorize(
            context,
            "introduction_review",
            agreement.obligation_ref,
            (agreement.buyer_principal,),
            request.model_dump(mode="json"),
        )
        if (replay := self._replay(auth)) is not None:
            return replay

        def capture(conn: Any) -> Any:
            contact, config = self._snapshot(agreement)
            return state.review(
                conn, request, agreement, contact, config.seller_route, int(time.time())
            )

        return await self.transaction(capture)

    async def start(
        self, context: Any, request: IntroductionStart | IntroductionFinalize
    ) -> Any:
        if isinstance(request, IntroductionStart):
            return await super().start(context, request)
        agreement = await self._prepare(request.negotiation_id, request.obligation_ref)
        auth = await self._callbacks.authorize(
            context,
            "introduction_start",
            agreement.obligation_ref,
            (agreement.buyer_principal,),
            request.model_dump(mode="json"),
        )
        if (replay := self._replay(auth)) is not None:
            return replay

        def capture(conn: Any) -> Any:
            committed_retry = (
                state.outcome(conn, request.obligation_ref, request.finalization_id)[
                    "status"
                ]
                == "committed"
            )
            contact, config = (
                ({}, None) if committed_retry else self.snapshot(agreement)
            )
            record = state.finalize(
                conn,
                request,
                agreement,
                contact,
                config.seller_route if config is not None else None,
                int(time.time()),
            )
            return record, committed_retry

        record, committed_retry = await self.transaction(capture)
        # Terminal rejection is committed before surfacing the error. A committed
        # retry observes capture, not permission to race the completion owner.
        if isinstance(record, IntroductionRouteError):
            raise record
        if not committed_retry:
            try:
                await self._callbacks.complete(agreement)
            except Exception as exc:
                raise state.fail("delivery_configuration_unavailable", 503) from exc
            await self.transaction(
                lambda conn: conn.execute(
                    "UPDATE contact_delivery_intents SET status='pending' WHERE obligation_ref=? AND status='awaiting_completion'",
                    (agreement.obligation_ref,),
                )
            )
        result = self._projection(
            record, viewer=auth.principal, buyer_principal=agreement.buyer_principal
        )
        result["finalization"] = {
            "schema_version": 2,
            "finalization_id": request.finalization_id,
            "status": "committed",
        }
        return result

    async def finalization_read(self, context: Any, ref: str, fid: str) -> Any:
        agreement = await self._prepare(None, ref)
        auth = await self._callbacks.authorize(
            context,
            "introduction_finalization_read",
            finalization_resource(ref, fid),
            (agreement.buyer_principal,),
            None,
        )
        if (replay := self._replay(auth)) is not None:
            return replay
        state.policy(agreement)
        return await self.transaction(lambda conn: state.outcome(conn, ref, fid))

    async def cancel(self, context: Any, request: FinalizationCancel) -> Any:
        agreement = await self._prepare(None, request.obligation_ref)
        auth = await self._callbacks.authorize(
            context,
            "introduction_finalization_cancel",
            finalization_resource(request.obligation_ref, request.finalization_id),
            (agreement.buyer_principal,),
            request.model_dump(mode="json"),
        )
        if (replay := self._replay(auth)) is not None:
            return replay
        return await self.transaction(
            lambda conn: state.cancel(conn, agreement, request.finalization_id)
        )

    async def delivery_read(self, context: Any, ref: str) -> Any:
        agreement = await self._prepare(None, ref)
        auth = await self._callbacks.authorize(
            context,
            "introduction_delivery_read",
            ref,
            (agreement.buyer_principal, agreement.seller_principal),
            None,
        )
        if (replay := self._replay(auth)) is not None:
            return replay
        role = "buyer" if auth.principal == agreement.buyer_principal else "seller"
        return await self.transaction(
            lambda conn: state.delivery_projection(conn, ref, role)
        )
