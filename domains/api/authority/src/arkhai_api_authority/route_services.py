"""Framework-free route services; a binding maps each refusal's status and body to a response."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from importlib.metadata import PackageNotFoundError, version as _distribution_version
from typing import Any

from arkhai_api_contracts.models import IssuanceRequest

from arkhai_api_authority.keys_service import (
    FULFILLMENT_CONFLICT,
    INSUFFICIENT_CREDITS,
    KEY_NOT_FOUND,
    KEY_NOT_OWNED,
    KEY_REVOKED,
    QUOTA_EXHAUSTED,
    IssuanceError,
    KeysService,
)

logger = logging.getLogger(__name__)

# HTTP status per machine-readable refusal reason. The reason rides the body
# either way; clients dispatch on it, not the status.
_ISSUANCE_STATUS = {
    KEY_NOT_FOUND: 404,
    KEY_NOT_OWNED: 403,
    KEY_REVOKED: 409,
    QUOTA_EXHAUSTED: 409,
    FULFILLMENT_CONFLICT: 409,
}
_CONSUME_STATUS = {
    KEY_NOT_FOUND: 404,
    KEY_REVOKED: 403,
    INSUFFICIENT_CREDITS: 402,
}


class RouteRefusal(Exception):
    """A route refused; ``status_code`` and ``body`` are the response as served."""

    def __init__(self, status_code: int, body: Mapping[str, Any]) -> None:
        super().__init__(f"{status_code}: {dict(body)}")
        self.status_code = status_code
        self.body = dict(body)


def _not_found(key_id: str) -> RouteRefusal:
    return RouteRefusal(404, {"detail": f"key {key_id!r} not found"})


class AuthorityRouteService:
    """Every authority route over the key service, one method per route."""

    def __init__(self, keys: KeysService) -> None:
        self._keys = keys

    def issue(self, request: IssuanceRequest) -> dict[str, Any]:
        try:
            result = self._keys.issue(
                fulfillment_id=request.fulfillment_id,
                negotiation_id=request.negotiation_id,
                owner_scheme=request.owner.scheme.value,
                owner_id=request.owner.identifier,
                service=request.service,
                resource_id=request.resource_id,
                quantity=request.quantity,
                key_mode=request.key.mode,
                key_id=request.key.key_id,
                request_digest=request.request_digest,
                capacity_reservation_id=request.capacity_reservation_id,
            )
        except IssuanceError as exc:
            logger.info("[ISSUANCE] refused fulfillment=%s: %s", request.fulfillment_id, exc.reason)
            raise RouteRefusal(
                _ISSUANCE_STATUS.get(exc.reason, 409), {"error": exc.reason, "detail": exc.message}
            ) from exc
        except ValueError as exc:
            raise RouteRefusal(422, {"detail": str(exc)}) from exc
        logger.info(
            "[ISSUANCE] fulfillment=%s key=%s quantity=%d replay=%s",
            request.fulfillment_id,
            result["key_id"],
            request.quantity,
            result["already_issued"],
        )
        return result

    def get_issuance(self, fulfillment_id: str) -> dict[str, Any]:
        result = self._keys.get_credit_issuance(fulfillment_id)
        if result is None:
            raise RouteRefusal(404, {"detail": "issuance not found"})
        return result

    def consume(self, key_id: str, *, amount: int, idempotency_key: str | None) -> dict[str, Any]:
        try:
            outcome = self._keys.consume(key_id=key_id, amount=amount, idempotency_key=idempotency_key)
        except ValueError as exc:
            raise RouteRefusal(422, {"detail": str(exc)}) from exc
        if outcome.get("ok"):
            return outcome
        reason = outcome.get("reason")
        raise RouteRefusal(
            _CONSUME_STATUS.get(reason, 402), {"error": reason, "balance": outcome.get("balance", 0)}
        )

    def consume_batch(self, items: list[Mapping[str, Any]]) -> dict[str, Any]:
        """Items are independent; a failed item is an outcome in order, not a refusal."""
        return {"results": self._keys.consume_batch(items)}

    def verify(self, key_id: str, *, secret: str) -> dict[str, Any]:
        return self._keys.verify(key_id=key_id, secret=secret)

    def list_keys(self, *, status: str | None, owner_id: str | None) -> dict[str, Any]:
        keys = self._keys.list_keys(status=status, owner_id=owner_id)
        return {"keys": keys, "total": len(keys)}

    def get_key(self, key_id: str) -> dict[str, Any]:
        key = self._keys.get_key(key_id)
        if key is None:
            raise _not_found(key_id)
        return key

    def revoke(self, key_id: str) -> dict[str, Any]:
        key = self._keys.revoke(key_id)
        if key is None:
            raise _not_found(key_id)
        return key

    def adjust(self, key_id: str, *, delta: int, reason: str | None) -> dict[str, Any]:
        try:
            key = self._keys.adjust(key_id=key_id, delta=delta, reason=reason)
        except ValueError as exc:
            raise RouteRefusal(409, {"detail": str(exc)}) from exc
        if key is None:
            raise _not_found(key_id)
        return key

    def list_grants(self, key_id: str) -> dict[str, Any]:
        grants = self._keys.list_grants(key_id)
        return {"grants": grants, "total": len(grants)}

    def list_usage(self, key_id: str, *, after_id: int, limit: int) -> dict[str, Any]:
        events = self._keys.list_usage(key_id, after_id=after_id, limit=limit)
        return {"events": events, "total": len(events)}


class SystemRouteService:
    """The version route: the composing distribution's name and installed version."""

    def __init__(self, distribution: str) -> None:
        self._distribution = distribution

    def version(self) -> dict[str, str]:
        try:
            installed = _distribution_version(self._distribution)
        except PackageNotFoundError:
            installed = "dev"
        return {"service": self._distribution, "version": installed}
