"""Exact, read-only Stripe test-mode retrieval for protected evidence."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Literal, Mapping, TypeVar
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .evidence import (
    CollectionEvidence,
    PaymentOutcomeEvidence,
    RefundEvidence,
    opaque_ref,
)

JsonObject = dict[str, Any]
Transport = Callable[[str, Mapping[str, str]], JsonObject]
T = TypeVar("T")


class StripeUnavailable(RuntimeError):
    """Stripe could not be reached or returned a non-contract response."""


class ProviderInvariantError(AssertionError):
    """Authoritative Stripe objects violate the expected exactly-once effect."""


class ProviderNotConverged(RuntimeError):
    """An exact related resource is not authoritative yet."""


class ProviderConvergenceTimeout(TimeoutError):
    """Exact Stripe resources did not converge within the selected bound."""


@dataclass(frozen=True)
class ExpectedEffect:
    operation_ref: str
    checkout_session_id: str
    amount: int
    currency: str
    destination_account: str
    transfer_group: str


@dataclass(frozen=True)
class TerminalProjection:
    marketplace_state: str
    authority_state: str
    fulfillment_state: str


class StripeApi:
    """Read-only client whose secret and returned provider IDs never leave memory."""

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

    def wait_for_collection(
        self,
        expected: ExpectedEffect,
        terminal: TerminalProjection,
        *,
        timeout: float,
        poll_interval: float,
    ) -> CollectionEvidence:
        return self._wait(
            lambda: self.inspect_collection(expected, terminal),
            timeout=timeout,
            poll_interval=poll_interval,
        )

    def inspect_collection(
        self, expected: ExpectedEffect, terminal: TerminalProjection
    ) -> CollectionEvidence:
        session = self._exact_checkout(expected)
        payment_intent = self._payment_intent(session)
        charge = self._charge(payment_intent)
        transfers = self._related_transfers(expected)
        if not transfers:
            raise ProviderNotConverged("related transfer is not visible")
        if len(transfers) != 1:
            raise ProviderInvariantError("expected exactly one related transfer")
        transfer = transfers[0]

        amount_ok = (
            session.get("amount_total") == expected.amount
            and payment_intent.get("amount_received") == expected.amount
            and charge.get("amount_captured") == expected.amount
            and transfer.get("amount") == expected.amount
        )
        currency_ok = all(
            item.get("currency") == expected.currency
            for item in (session, payment_intent, charge, transfer)
        )
        destination_matches = (
            _object_id(transfer.get("destination"), "destination") == expected.destination_account
        )
        group_matches = transfer.get("transfer_group") == expected.transfer_group
        charge_id = _object_id(charge, "charge")
        source_matches = (
            _object_id(transfer.get("source_transaction"), "source transaction") == charge_id
        )
        checkout_ref = _provider_ref("checkout", expected.transfer_group)
        metadata_matches = all(
            _escrow_metadata_matches(item, expected.transfer_group)
            and _metadata_matches(item, checkout_ref)
            for item in (session, payment_intent)
        ) and _metadata_matches(transfer, _provider_ref("collect", expected.transfer_group))
        if (
            session.get("livemode") is not False
            or payment_intent.get("livemode") is not False
            or transfer.get("livemode") is not False
            or session.get("mode") != "payment"
            or session.get("status") != "complete"
            or session.get("payment_status") != "paid"
            or payment_intent.get("status") != "succeeded"
            or charge.get("paid") is not True
            or not amount_ok
            or not currency_ok
            or not destination_matches
            or not group_matches
            or not source_matches
            or not metadata_matches
        ):
            raise ProviderInvariantError(
                "Checkout or destination transfer did not match accepted terms"
            )
        operation_ref = opaque_ref("op", expected.operation_ref)
        return CollectionEvidence(
            operation_ref=operation_ref,
            checkout_count=1,
            payment_intent_count=1,
            charge_count=1,
            transfer_count=1,
            amount=expected.amount,
            currency=expected.currency,
            destination_matches=True,
            transfer_group_matches=True,
            source_transaction_matches=True,
            operation_metadata_matches=True,
            marketplace_state=_collected_state(terminal.marketplace_state),
            authority_state=_collected_state(terminal.authority_state),
            fulfillment_state=_fulfilled_state(terminal.fulfillment_state),
        )

    def wait_for_refund(
        self,
        expected: ExpectedEffect,
        terminal: TerminalProjection,
        *,
        timeout: float,
        poll_interval: float,
    ) -> RefundEvidence:
        return self._wait(
            lambda: self.inspect_refund(expected, terminal),
            timeout=timeout,
            poll_interval=poll_interval,
        )

    def inspect_refund(
        self, expected: ExpectedEffect, terminal: TerminalProjection
    ) -> RefundEvidence:
        session = self._exact_checkout(expected)
        payment_intent = self._payment_intent(session)
        charge = self._charge(payment_intent)
        charge_id = _object_id(charge, "charge")
        refunds = self._list_all("/v1/refunds", {"charge": charge_id, "limit": "100"})
        refunds = [
            item
            for item in refunds
            if _metadata_matches(
                item,
                _provider_ref("refund", expected.transfer_group, _hash_text(charge_id)),
            )
        ]
        transfers = self._related_transfers(expected)
        if not refunds:
            raise ProviderNotConverged("related refund is not visible")
        if (len(refunds), len(transfers)) != (1, 0):
            raise ProviderInvariantError("expected one related refund and no transfer")
        refund = refunds[0]
        if (
            session.get("livemode") is not False
            or refund.get("livemode") is not False
            or session.get("amount_total") != expected.amount
            or session.get("currency") != expected.currency
            or refund.get("amount") != expected.amount
            or refund.get("currency") != expected.currency
            or refund.get("status") != "succeeded"
            or not all(
                _escrow_metadata_matches(item, expected.transfer_group)
                and _metadata_matches(item, _provider_ref("checkout", expected.transfer_group))
                for item in (session, payment_intent)
            )
            or not _metadata_matches(
                refund, _provider_ref("refund", expected.transfer_group, _hash_text(charge_id))
            )
        ):
            raise ProviderInvariantError("refund did not match the accepted pre-transfer operation")
        operation_ref = opaque_ref("op", expected.operation_ref)
        return RefundEvidence(
            operation_ref=operation_ref,
            checkout_count=1,
            payment_intent_count=1,
            charge_count=1,
            refund_count=1,
            transfer_count=0,
            amount=expected.amount,
            currency=expected.currency,
            operation_metadata_matches=True,
            marketplace_state=_reclaimed_state(terminal.marketplace_state),
            authority_state=_refunded_state(terminal.authority_state),
        )

    def wait_for_payment_outcome(
        self,
        expected: ExpectedEffect,
        outcome: Literal["decline", "insufficient_funds", "authentication"],
        *,
        timeout: float,
        poll_interval: float,
    ) -> PaymentOutcomeEvidence:
        return self._wait(
            lambda: self.inspect_payment_outcome(expected, outcome),
            timeout=timeout,
            poll_interval=poll_interval,
        )

    def inspect_payment_outcome(
        self,
        expected: ExpectedEffect,
        outcome: Literal["decline", "insufficient_funds", "authentication"],
    ) -> PaymentOutcomeEvidence:
        session = self._exact_checkout(expected)
        payment_intent = self._payment_intent(session)
        charge = self._optional_charge(payment_intent)
        checkout_ref = _provider_ref("checkout", expected.transfer_group)
        if not all(
            _escrow_metadata_matches(item, expected.transfer_group)
            and _metadata_matches(item, checkout_ref)
            for item in (session, payment_intent)
        ):
            raise ProviderInvariantError("payment outcome metadata did not match the operation")
        if self._related_transfers(expected):
            raise ProviderInvariantError("payment-outcome-only scenario created a transfer")
        refunds = (
            self._list_all(
                "/v1/refunds",
                {"charge": _object_id(charge, "charge"), "limit": "100"},
            )
            if charge is not None
            else []
        )
        if refunds:
            raise ProviderInvariantError("payment-outcome-only scenario created a refund")

        if outcome == "authentication":
            if charge is None:
                raise ProviderNotConverged("authenticated charge is not visible")
            three_d_secure = _nested(charge, "payment_method_details", "card", "three_d_secure")
            if (
                session.get("payment_status") != "paid"
                or payment_intent.get("status") != "succeeded"
                or not isinstance(three_d_secure, dict)
                or three_d_secure.get("result") not in {"authenticated", "attempt_acknowledged"}
            ):
                raise ProviderInvariantError("Stripe authentication outcome did not match")
            normalized = "authentication_succeeded"
        else:
            error = payment_intent.get("last_payment_error")
            if not isinstance(error, dict):
                raise ProviderNotConverged("documented decline is not visible")
            decline_code = error.get("decline_code")
            expected_code = (
                "insufficient_funds" if outcome == "insufficient_funds" else "generic_decline"
            )
            if (
                session.get("payment_status") == "paid"
                or error.get("code") != "card_declined"
                or decline_code != expected_code
            ):
                raise ProviderInvariantError(
                    "Stripe decline outcome did not match the selected test card"
                )
            normalized = "insufficient_funds" if outcome == "insufficient_funds" else "declined"
        return PaymentOutcomeEvidence(
            operation_ref=opaque_ref("op", expected.operation_ref),
            outcome=normalized,
            checkout_count=1,
            payment_intent_count=1,
            charge_count=int(charge is not None),
            transfer_count=0,
            refund_count=0,
            operation_metadata_matches=True,
        )

    def _exact_checkout(self, expected: ExpectedEffect) -> JsonObject:
        session = self._transport(
            f"/v1/checkout/sessions/{expected.checkout_session_id}",
            {"expand[]": "payment_intent.latest_charge"},
        )
        checkout_ref = _provider_ref("checkout", expected.transfer_group)
        if (
            _object_id(session, "Checkout session") != expected.checkout_session_id
            or not _escrow_metadata_matches(session, expected.transfer_group)
            or not _metadata_matches(session, checkout_ref)
            or session.get("client_reference_id") != expected.transfer_group
        ):
            raise ProviderInvariantError("exact Checkout session did not match the operation")
        query = f"metadata['operation_ref']:'{_search_literal(checkout_ref)}'"
        matches = self._list_all("/v1/checkout/sessions/search", {"query": query, "limit": "100"})
        matching_ids = {
            _object_id(item, "Checkout search result")
            for item in matches
            if _metadata_matches(item, checkout_ref)
            and _escrow_metadata_matches(item, expected.transfer_group)
            and item.get("client_reference_id") == expected.transfer_group
        }
        if expected.checkout_session_id not in matching_ids:
            raise ProviderNotConverged("exact Checkout metadata search is not visible")
        if matching_ids != {expected.checkout_session_id}:
            raise ProviderInvariantError("operation metadata identifies multiple Checkout sessions")
        return session

    def _payment_intent(self, session: JsonObject) -> JsonObject:
        value = session.get("payment_intent")
        if isinstance(value, dict):
            return value
        payment_intent_id = _object_id(value, "payment intent")
        return self._transport(
            f"/v1/payment_intents/{payment_intent_id}",
            {"expand[]": "latest_charge"},
        )

    def _charge(self, payment_intent: JsonObject) -> JsonObject:
        value = self._optional_charge(payment_intent)
        if value is None:
            raise ProviderNotConverged("related charge is not visible")
        return value

    def _optional_charge(self, payment_intent: JsonObject) -> JsonObject | None:
        value = payment_intent.get("latest_charge")
        if value is None:
            return None
        if isinstance(value, dict):
            return value
        charge_id = _object_id(value, "latest charge")
        return self._transport(f"/v1/charges/{charge_id}", {})

    def _related_transfers(self, expected: ExpectedEffect) -> list[JsonObject]:
        transfers = self._list_all(
            "/v1/transfers",
            {"transfer_group": expected.transfer_group, "limit": "100"},
        )
        operation_ref = _provider_ref("collect", expected.transfer_group)
        return [item for item in transfers if _metadata_matches(item, operation_ref)]

    def _wait(
        self,
        inspect: Callable[[], T],
        *,
        timeout: float,
        poll_interval: float,
    ) -> T:
        if timeout <= 0 or poll_interval <= 0:
            raise ValueError("provider polling bounds must be positive")
        deadline = time.monotonic() + timeout
        while True:
            try:
                return inspect()
            except ProviderNotConverged as exc:
                if time.monotonic() >= deadline:
                    raise ProviderConvergenceTimeout("Stripe resources did not converge") from exc
                time.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))

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
            request_params["starting_after"] = _object_id(page[-1], "page cursor")
        raise StripeUnavailable("Stripe pagination exceeded the protected inspection bound")

    def _request(self, path: str, params: Mapping[str, str]) -> JsonObject:
        query = urlencode(params)
        url = f"{self._base_url}{path}" + (f"?{query}" if query else "")
        request = Request(
            url,
            headers={
                "Authorization": f"Bearer {self._secret}",
                "Stripe-Version": "2025-08-27.basil",
                "User-Agent": "arkhai-protected-hosted-stripe-test/2",
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


def _hash_text(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode()).hexdigest()


def _escrow_metadata_matches(obj: JsonObject, escrow_ref: str) -> bool:
    metadata = obj.get("metadata")
    return isinstance(metadata, dict) and metadata.get("escrow_ref") == escrow_ref


def _provider_ref(prefix: str, *parts: str) -> str:
    import hashlib

    digest = hashlib.sha256("\x00".join(parts).encode()).hexdigest()
    return f"{prefix}_{digest[:40]}"


def _object_id(value: object, name: str) -> str:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, dict) and isinstance(value.get("id"), str) and value["id"]:
        return value["id"]
    raise ProviderInvariantError(f"Stripe {name} relation is missing")


def _nested(value: JsonObject, *keys: str) -> object:
    current: object = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _search_literal(value: str) -> str:
    if not value or any(character in value for character in ("'", "\\", "\n", "\r")):
        raise ProviderInvariantError("operation metadata is not safe for exact retrieval")
    return value


def _collected_state(value: str) -> Literal["collected"]:
    if value != "collected":
        raise ProviderInvariantError("terminal collection state is incorrect")
    return "collected"


def _fulfilled_state(value: str) -> Literal["fulfilled"]:
    if value not in {"ready", "fulfilled", "completed"}:
        raise ProviderInvariantError("terminal fulfillment state is incorrect")
    return "fulfilled"


def _reclaimed_state(value: str) -> Literal["reclaimed"]:
    if value != "reclaimed":
        raise ProviderInvariantError("terminal marketplace refund state is incorrect")
    return "reclaimed"


def _refunded_state(value: str) -> Literal["refunded"]:
    if value != "refunded":
        raise ProviderInvariantError("terminal authority refund state is incorrect")
    return "refunded"
