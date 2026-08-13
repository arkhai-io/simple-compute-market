"""Narrow Stripe test-mode retrieval used only by protected E2E evidence."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .evidence import CollectionEvidence, RefundEvidence

JsonObject = dict[str, Any]
Transport = Callable[[str, Mapping[str, str]], JsonObject]


class StripeUnavailable(RuntimeError):
    """Stripe could not be reached or returned a non-contract response."""


class ProviderInvariantError(AssertionError):
    """Authoritative Stripe objects violate the expected exactly-once effect."""


@dataclass(frozen=True)
class ExpectedEffect:
    operation_ref: str
    amount: int
    currency: str
    destination_account: str
    transfer_group: str
    created_after: int


@dataclass(frozen=True)
class TerminalProjection:
    marketplace_state: str
    authority_state: str
    fulfillment_state: str


class StripeApi:
    """Read-only client whose secret is never formatted into commands or errors."""

    def __init__(
        self,
        secret: str,
        *,
        base_url: str = "https://api.stripe.com",
        transport: Transport | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._secret = secret
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._transport = transport or self._request

    def retrieve_account(self, account_id: str) -> JsonObject:
        return self._transport(f"/v1/accounts/{account_id}", {})

    def inspect_collection(
        self, expected: ExpectedEffect, terminal: TerminalProjection
    ) -> CollectionEvidence:
        sessions = self._matching_objects(
            "/v1/checkout/sessions",
            expected,
            require_transfer_group=False,
        )
        transfers = self._matching_objects("/v1/transfers", expected)
        if len(sessions) != 1 or len(transfers) != 1:
            raise ProviderInvariantError("expected exactly one matching Checkout and transfer")
        session, transfer = sessions[0], transfers[0]
        payment_intent_id = _object_id(session.get("payment_intent"), "payment intent")
        payment_intent = self._transport(f"/v1/payment_intents/{payment_intent_id}", {})
        latest_charge = _object_id(payment_intent.get("latest_charge"), "latest charge")

        amount_ok = session.get("amount_total") == expected.amount and transfer.get("amount") == expected.amount
        currency_ok = session.get("currency") == expected.currency and transfer.get("currency") == expected.currency
        destination_matches = _object_id(transfer.get("destination"), "destination") == expected.destination_account
        group_matches = transfer.get("transfer_group") == expected.transfer_group
        source_matches = _object_id(transfer.get("source_transaction"), "source transaction") == latest_charge
        metadata_matches = _metadata_matches(session, expected.operation_ref) and _metadata_matches(
            transfer, expected.operation_ref
        )
        if (
            session.get("mode") != "payment"
            or session.get("status") != "complete"
            or session.get("payment_status") != "paid"
            or not amount_ok
            or not currency_ok
            or not destination_matches
            or not group_matches
            or not source_matches
            or not metadata_matches
        ):
            raise ProviderInvariantError("Checkout or destination transfer did not match accepted terms")
        return CollectionEvidence(
            operation_ref=expected.operation_ref,
            checkout_count=1,
            transfer_count=1,
            amount=expected.amount,
            currency=expected.currency,
            destination_matches=True,
            transfer_group_matches=True,
            source_transaction_matches=True,
            operation_metadata_matches=True,
            marketplace_state=terminal.marketplace_state,
            authority_state=terminal.authority_state,
            fulfillment_state=terminal.fulfillment_state,
        )

    def inspect_refund(
        self, expected: ExpectedEffect, terminal: TerminalProjection
    ) -> RefundEvidence:
        sessions = self._matching_objects(
            "/v1/checkout/sessions",
            expected,
            require_transfer_group=False,
        )
        transfers = self._matching_objects("/v1/transfers", expected)
        refunds = self._matching_objects(
            "/v1/refunds",
            expected,
            require_transfer_group=False,
        )
        if (len(sessions), len(refunds), len(transfers)) != (1, 1, 0):
            raise ProviderInvariantError("expected one matching Checkout/refund and no transfer")
        session, refund = sessions[0], refunds[0]
        if (
            session.get("amount_total") != expected.amount
            or session.get("currency") != expected.currency
            or refund.get("amount") != expected.amount
            or refund.get("currency") != expected.currency
            or refund.get("status") != "succeeded"
            or not _metadata_matches(session, expected.operation_ref)
            or not _metadata_matches(refund, expected.operation_ref)
        ):
            raise ProviderInvariantError("refund did not match the accepted pre-transfer operation")
        return RefundEvidence(
            outcome="passed",
            operation_ref=expected.operation_ref,
            checkout_count=1,
            refund_count=1,
            transfer_count=0,
            amount=expected.amount,
            currency=expected.currency,
            operation_metadata_matches=True,
            marketplace_state=terminal.marketplace_state,
            authority_state=terminal.authority_state,
        )

    def _matching_objects(
        self,
        path: str,
        expected: ExpectedEffect,
        *,
        require_transfer_group: bool = True,
    ) -> list[JsonObject]:
        params = {"created[gte]": str(expected.created_after), "limit": "100"}
        if require_transfer_group:
            params["transfer_group"] = expected.transfer_group
        objects = self._list_all(path, params)
        return [item for item in objects if _metadata_matches(item, expected.operation_ref)]

    def _list_all(self, path: str, params: dict[str, str]) -> list[JsonObject]:
        collected: list[JsonObject] = []
        request_params = dict(params)
        for _page in range(20):
            body = self._transport(path, request_params)
            data = body.get("data")
            if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
                raise StripeUnavailable("Stripe list response was malformed")
            page = list(data)
            collected.extend(page)
            if body.get("has_more") is not True:
                return collected
            if not page:
                raise StripeUnavailable("Stripe pagination did not advance")
            request_params["starting_after"] = _object_id(page[-1].get("id"), "page cursor")
        raise StripeUnavailable("Stripe pagination exceeded the protected inspection bound")

    def _request(self, path: str, params: Mapping[str, str]) -> JsonObject:
        query = urlencode(params)
        url = f"{self._base_url}{path}" + (f"?{query}" if query else "")
        request = Request(
            url,
            headers={
                "Authorization": f"Bearer {self._secret}",
                "Stripe-Version": "2025-08-27.basil",
                "User-Agent": "arkhai-protected-hosted-e2e/1",
            },
        )
        try:
            with urlopen(request, timeout=self._timeout) as response:
                value = json.load(response)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            raise StripeUnavailable("Stripe API retrieval was unavailable") from exc
        if not isinstance(value, dict):
            raise StripeUnavailable("Stripe API response was malformed")
        return value


def _metadata_matches(obj: JsonObject, operation_ref: str) -> bool:
    metadata = obj.get("metadata")
    return isinstance(metadata, dict) and metadata.get("operation_ref") == operation_ref


def _object_id(value: object, name: str) -> str:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, dict) and isinstance(value.get("id"), str) and value["id"]:
        return value["id"]
    raise ProviderInvariantError(f"Stripe {name} relation is missing")
