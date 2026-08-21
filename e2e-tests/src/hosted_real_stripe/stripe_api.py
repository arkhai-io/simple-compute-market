"""Exact Stripe test-mode retrieval and allowlisted test funding."""

from __future__ import annotations

import hashlib
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
MutationTransport = Callable[[str, Mapping[str, str]], JsonObject]
T = TypeVar("T")

#: Stripe's documented test-mode bank, and the deposits it always makes. A
#: payer reads these off their own statement; the run reads them off the
#: provider's published test behavior, which is where every other provider
#: assertion in this harness comes from.
_TEST_BANK_ROUTING_NUMBER = "110000000"
_TEST_BANK_MICRODEPOSIT_ACCOUNT = "000123456789"
MICRODEPOSIT_AMOUNTS = (32, 45)


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
    marketplace_operation_id: str
    funding_profile: str
    checkout_session_id: str | None
    amount: int
    currency: str
    destination_account: str
    transfer_group: str


@dataclass(frozen=True)
class TerminalProjection:
    marketplace_state: str
    authority_state: str
    fulfillment_state: str
    effect_operation_ref: str


class StripeApi:
    """Constrained test-mode client whose provider IDs never leave memory."""

    def __init__(
        self,
        secret: str,
        *,
        base_url: str = "https://api.stripe.com",
        transport: Transport | None = None,
        mutation_transport: MutationTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._secret = secret
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._transport = transport or self._request
        self._mutation_transport = mutation_transport or self._post

    def retrieve_account(self, account_id: str) -> JsonObject:
        return self._transport(f"/v1/accounts/{account_id}", {})

    def fund_test_cash_balance(self, expected: ExpectedEffect) -> None:
        """Fund one exact push-transfer intent through Stripe's test helper."""

        if expected.funding_profile != "us_bank_transfer.v1":
            raise ProviderInvariantError(
                "cash-balance test funding requires the push-transfer profile"
            )
        _session, payment_intent = self._exact_funding(expected)
        customer = _object_id(payment_intent.get("customer"), "customer")
        result = self._mutation_transport(
            f"/v1/test_helpers/customers/{customer}/fund_cash_balance",
            {
                "amount": str(expected.amount),
                "currency": expected.currency,
                "reference": _bank_transfer_reference(payment_intent),
            },
        )
        if (
            result.get("livemode") is not False
            or result.get("net_amount") != expected.amount
            or result.get("currency") != expected.currency
        ):
            raise ProviderInvariantError(
                "Stripe cash-balance test helper did not fund the exact accepted amount"
            )

    def create_microdeposit_bank_instrument(self) -> str:
        """Create the documented test bank instrument a payer would hold.

        The token is transient. It exists so the setup can be started from an
        instrument rather than from a hosted page, and it is handed straight to
        the authority without being stored or reported.
        """

        result = self._mutation_transport(
            "/v1/payment_methods",
            {
                "type": "us_bank_account",
                "us_bank_account[account_number]": _TEST_BANK_MICRODEPOSIT_ACCOUNT,
                "us_bank_account[routing_number]": _TEST_BANK_ROUTING_NUMBER,
                "us_bank_account[account_holder_type]": "individual",
                "us_bank_account[account_type]": "checking",
                "billing_details[name]": "Arkhai Test Payer",
                "billing_details[email]": "payer@example.invalid",
            },
        )
        if result.get("livemode") is not False:
            raise ProviderInvariantError(
                "a test-mode instrument may not be created outside test mode"
            )
        return _object_id(result, "payment method")

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
        session, payment_intent = self._exact_funding(expected)
        charge = self._charge(payment_intent)
        transfers = self._related_transfers(expected, terminal.effect_operation_ref)
        if not transfers:
            raise ProviderNotConverged("related transfer is not visible")
        if len(transfers) != 1:
            raise ProviderInvariantError("expected exactly one related transfer")
        transfer = transfers[0]

        provider_objects = (payment_intent, charge, transfer)
        amount_ok = (
            payment_intent.get("amount_received") == expected.amount
            and charge.get("amount_captured") == expected.amount
            and transfer.get("amount") == expected.amount
            and (session is None or session.get("amount_total") == expected.amount)
        )
        currency_ok = all(
            item.get("currency") == expected.currency for item in provider_objects
        ) and (session is None or session.get("currency") == expected.currency)
        destination_matches = (
            _object_id(transfer.get("destination"), "destination") == expected.destination_account
        )
        group_matches = transfer.get("transfer_group") == expected.transfer_group
        source = transfer.get("source_transaction")
        source_matches = source is None or _object_id(source, "source transaction") == _object_id(
            charge, "charge"
        )
        metadata_matches = _funding_metadata_matches(
            payment_intent, expected
        ) and _has_operation_metadata(transfer)
        if session is not None:
            metadata_matches = metadata_matches and _funding_metadata_matches(session, expected)
        if (
            payment_intent.get("livemode") is not False
            or transfer.get("livemode") is not False
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
                "funding or destination transfer did not match accepted terms"
            )
        return CollectionEvidence(
            operation_ref=opaque_ref("op", expected.marketplace_operation_id),
            checkout_count=int(session is not None),
            payment_intent_count=1,
            charge_count=1,
            transfer_count=1,
            amount=expected.amount,
            currency=expected.currency,
            destination_matches=True,
            transfer_group_matches=True,
            source_transaction_matches=source_matches,
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
        session, payment_intent = self._exact_funding(expected)
        charge = self._charge(payment_intent)
        charge_id = _object_id(charge, "charge")
        refunds = self._list_all("/v1/refunds", {"charge": charge_id, "limit": "100"})
        refunds = [
            item
            for item in refunds
            if _has_operation_metadata(item)
            and _profile_metadata_matches(item, expected.funding_profile)
        ]
        transfers = self._related_transfers(expected, terminal.effect_operation_ref)
        if not refunds:
            raise ProviderNotConverged("related refund is not visible")
        if (len(refunds), len(transfers)) != (1, 0):
            raise ProviderInvariantError("expected one related refund and no transfer")
        refund = refunds[0]
        # Named individually on purpose. A single or-chain reports that the
        # refund did not match without saying which of seven things differed,
        # which is the whole diagnosis. Amounts, currency, and status are safe
        # to state; identifiers are named as fields and never as values.
        mismatch = (
            "funding is not test-mode"
            if payment_intent.get("livemode") is not False
            else f"funding received {payment_intent.get('amount_received')!r},"
            f" accepted {expected.amount!r}"
            if payment_intent.get("amount_received") != expected.amount
            else f"funding currency {payment_intent.get('currency')!r},"
            f" accepted {expected.currency!r}"
            if payment_intent.get("currency") != expected.currency
            else f"refund amount {refund.get('amount')!r}, accepted {expected.amount!r}"
            if refund.get("amount") != expected.amount
            else f"refund currency {refund.get('currency')!r},"
            f" accepted {expected.currency!r}"
            if refund.get("currency") != expected.currency
            else f"refund status {refund.get('status')!r}, expected 'succeeded'"
            if refund.get("status") != "succeeded"
            else "funding metadata does not bind the accepted operation,"
            " profile, and authorization"
            if not _funding_metadata_matches(payment_intent, expected)
            else ""
        )
        if mismatch:
            raise ProviderInvariantError(
                f"refund did not match the accepted pre-transfer operation: {mismatch}"
            )
        return RefundEvidence(
            operation_ref=opaque_ref("op", expected.marketplace_operation_id),
            checkout_count=int(session is not None),
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
        session, payment_intent = self._exact_funding(expected)
        charge = self._optional_charge(payment_intent)
        if not _funding_metadata_matches(payment_intent, expected):
            raise ProviderInvariantError("payment outcome metadata did not match the operation")
        if self._related_transfers(expected, ""):
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

        normalized: Literal[
            "declined",
            "insufficient_funds",
            "authentication_succeeded",
        ]
        if outcome == "authentication":
            if charge is None:
                raise ProviderNotConverged("authenticated charge is not visible")
            three_d_secure = _nested(charge, "payment_method_details", "card", "three_d_secure")
            if (
                payment_intent.get("status") != "succeeded"
                or not isinstance(three_d_secure, dict)
                or three_d_secure.get("result") not in {"authenticated", "attempt_acknowledged"}
            ):
                raise ProviderInvariantError("Stripe authentication outcome did not match")
            normalized = "authentication_succeeded"
        else:
            error = payment_intent.get("last_payment_error")
            if not isinstance(error, dict):
                raise ProviderNotConverged("documented decline is not visible")
            expected_code = (
                "insufficient_funds" if outcome == "insufficient_funds" else "generic_decline"
            )
            if (
                payment_intent.get("status") == "succeeded"
                or error.get("code") != "card_declined"
                or error.get("decline_code") != expected_code
            ):
                raise ProviderInvariantError(
                    "Stripe decline outcome did not match the selected test card"
                )
            normalized = "insufficient_funds" if outcome == "insufficient_funds" else "declined"
        return PaymentOutcomeEvidence(
            operation_ref=opaque_ref("op", expected.marketplace_operation_id),
            outcome=normalized,
            checkout_count=int(session is not None),
            payment_intent_count=1,
            charge_count=int(charge is not None),
            transfer_count=0,
            refund_count=0,
            operation_metadata_matches=True,
        )

    def _exact_funding(self, expected: ExpectedEffect) -> tuple[JsonObject | None, JsonObject]:
        session: JsonObject | None = None
        if expected.checkout_session_id is not None:
            session = self._transport(
                f"/v1/checkout/sessions/{expected.checkout_session_id}",
                {"expand[]": "payment_intent.latest_charge"},
            )
            metadata = session.get("metadata")
            if (
                _object_id(session, "Checkout session") != expected.checkout_session_id
                or not isinstance(metadata, dict)
                or session.get("client_reference_id") != metadata.get("operation_ref")
                or not _funding_metadata_matches(session, expected)
            ):
                raise ProviderInvariantError("exact Checkout session did not match the operation")
            payment_intent = self._payment_intent(session)
        else:
            matches = [
                item
                for item in self._list_all(
                    "/v1/payment_intents",
                    {"limit": "100", "expand[]": "data.latest_charge"},
                )
                if _funding_metadata_matches(item, expected)
            ]
            if not matches:
                raise ProviderNotConverged("operation funding is not visible")
            if len(matches) != 1:
                raise ProviderInvariantError(
                    "operation metadata identifies multiple funding intents"
                )
            payment_intent = matches[0]
        if (
            payment_intent.get("amount") != expected.amount
            or payment_intent.get("currency") != expected.currency
            or payment_intent.get("transfer_group") != expected.transfer_group
            or not _funding_metadata_matches(payment_intent, expected)
        ):
            raise ProviderInvariantError("funding intent does not match immutable accepted terms")
        return session, payment_intent

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

    def _related_transfers(
        self, expected: ExpectedEffect, _effect_operation_ref: str
    ) -> list[JsonObject]:
        transfers = self._list_all(
            "/v1/transfers",
            {"transfer_group": expected.transfer_group, "limit": "100"},
        )
        return [
            item
            for item in transfers
            if _has_operation_metadata(item)
            and _profile_metadata_matches(item, expected.funding_profile)
        ]

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
            except (ProviderNotConverged, StripeUnavailable) as exc:
                if time.monotonic() >= deadline:
                    if isinstance(exc, StripeUnavailable):
                        raise
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

    def _post(self, path: str, params: Mapping[str, str]) -> JsonObject:
        encoded = urlencode(params).encode()
        request = Request(
            f"{self._base_url}{path}",
            data=encoded,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._secret}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Stripe-Version": "2025-08-27.basil",
                "User-Agent": "arkhai-protected-hosted-stripe-test/2",
            },
        )
        try:
            with urlopen(request, timeout=self._timeout) as response:
                value = json.load(response)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            raise StripeUnavailable("Stripe API mutation was unavailable") from exc
        if not isinstance(value, dict):
            raise StripeUnavailable("Stripe API mutation response was malformed")
        return value


def _metadata_matches(obj: JsonObject, operation_ref: str) -> bool:
    metadata = obj.get("metadata")
    return isinstance(metadata, dict) and metadata.get("operation_ref") == operation_ref


def _has_operation_metadata(obj: JsonObject) -> bool:
    metadata = obj.get("metadata")
    return (
        isinstance(metadata, dict)
        and isinstance(metadata.get("operation_ref"), str)
        and bool(metadata["operation_ref"])
    )


def _profile_metadata_matches(obj: JsonObject, funding_profile: str) -> bool:
    metadata = obj.get("metadata")
    return isinstance(metadata, dict) and metadata.get("funding_profile") == funding_profile


def _funding_metadata_matches(obj: JsonObject, expected: ExpectedEffect) -> bool:
    metadata = obj.get("metadata")
    return (
        _has_operation_metadata(obj)
        and isinstance(metadata, dict)
        and metadata.get("marketplace_operation_id") == expected.marketplace_operation_id
        and metadata.get("funding_profile") == expected.funding_profile
        and isinstance(metadata.get("funding_authorization_ref"), str)
        and bool(metadata["funding_authorization_ref"])
    )


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _escrow_metadata_matches(obj: JsonObject, escrow_ref: str) -> bool:
    metadata = obj.get("metadata")
    return isinstance(metadata, dict) and metadata.get("escrow_ref") == escrow_ref


def _provider_ref(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x00".join(parts).encode()).hexdigest()
    return f"{prefix}_{digest[:40]}"


def _bank_transfer_reference(payment_intent: JsonObject) -> str:
    """Return the reference a payer must quote on the incoming bank transfer.

    A push transfer is attributed by the reference Stripe issues with the
    funding instructions, not by the customer it lands on. Funding the test
    cash balance without it simulates an unreferenced deposit, which the
    authority is right to treat as an attribution incident.
    """

    action = payment_intent.get("next_action")
    instructions = (
        action.get("display_bank_transfer_instructions")
        if isinstance(action, dict)
        else None
    )
    reference = (
        instructions.get("reference") if isinstance(instructions, dict) else None
    )
    if not isinstance(reference, str) or not reference:
        raise ProviderInvariantError(
            "push-transfer funding instructions carry no payer reference"
        )
    return reference


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
