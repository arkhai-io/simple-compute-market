"""Synchronous, stateless HTTP client for the Arkhai payments service."""

from __future__ import annotations

import ipaddress
import re
import time
from collections.abc import Mapping
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from market_arkhai_payments.canonical import agreement_hash
from market_arkhai_payments.errors import (
    PaymentsAPIError,
    PaymentsPollTimeout,
    PaymentsProtocolError,
    PaymentsTransportError,
)
from market_arkhai_payments.mandates import PaymentsOptionParams
from market_arkhai_payments.models import (
    ApiError,
    ApprovalRequest,
    DealAttachment,
    EventCommand,
    Mandate,
    SignedReceipt,
    SignedTransactionSnapshot,
    StoredDealAttachment,
    StoredEvent,
    AccountId,
)

_TRANSACTION_ID = re.compile(r"^[0-9a-f]{64}$")
_ModelT = TypeVar("_ModelT", bound=BaseModel)


class PaymentsClient:
    """Authenticated HTTP client with no local transaction or servicing state.

    Use a WorkOS user-scoped API key for normal service calls. The explicit
    ``development_account`` mode sends the service's development-only account
    header and is intended for local integration runs.
    """

    def __init__(
        self,
        service_url: str,
        *,
        api_key: str | None = None,
        development_account: str | None = None,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if (api_key is None) == (development_account is None):
            raise ValueError("provide exactly one of api_key or development_account")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        url = httpx.URL(service_url)
        if (
            url.scheme not in {"http", "https"}
            or not url.host
            or url.path not in {"", "/"}
            or url.query
            or url.fragment
        ):
            raise ValueError("service_url must be an HTTP(S) origin without path, query, or fragment")
        if url.username or url.password:
            raise ValueError("service_url must not embed credentials")
        if url.scheme != "https" and not _is_loopback(url.host):
            raise ValueError("WorkOS credentials require HTTPS outside loopback development")
        headers: dict[str, str] = {}
        if api_key is not None:
            if not api_key.strip() or "\r" in api_key or "\n" in api_key:
                raise ValueError("api_key must be a nonempty HTTP header value")
            headers["Authorization"] = f"Bearer {api_key}"
        else:
            parsed_account = AccountId.model_validate(development_account).root
            headers["X-Account-ID"] = parsed_account
        self._http = httpx.Client(
            base_url=url,
            headers=headers,
            timeout=timeout,
            follow_redirects=False,
            trust_env=not _is_loopback(url.host),
            transport=transport,
        )

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""

        self._http.close()

    def __enter__(self) -> PaymentsClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def approve(
        self,
        mandate: Mandate | Mapping[str, Any],
        *,
        agreement: dict[str, Any] | None = None,
    ) -> SignedReceipt:
        """Approve the same deterministic mandate; exact retries reuse its ID."""

        parsed = Mandate.model_validate(mandate)
        attachments = None
        if agreement is not None:
            if agreement_hash(agreement) != parsed.deal.root.root:
                raise ValueError("agreement hash does not match mandate.deal")
            attachments = [DealAttachment.model_validate({"kind": "deal", "content": agreement})]
        body = ApprovalRequest(mandate=parsed, attachments=attachments)
        return _validated(SignedReceipt, self._request("POST", "/transactions", json=_json(body)))

    def get_transaction(self, transaction: str) -> SignedTransactionSnapshot:
        """Read one signed point-in-time transaction snapshot by its mandate ID."""

        identifier = _transaction_id(transaction)
        payload = self._request("GET", f"/transactions/{identifier}")
        return _validated(SignedTransactionSnapshot, payload)

    def poll(
        self,
        transaction: str,
        *,
        timeout: float = 300.0,
        interval: float = 1.0,
    ) -> SignedTransactionSnapshot:
        """Poll until the service has an approval snapshot for this transaction."""

        identifier = _transaction_id(transaction)
        if timeout < 0 or interval <= 0:
            raise ValueError("timeout must be nonnegative and interval must be positive")
        deadline = time.monotonic() + timeout
        while True:
            try:
                snapshot = self.get_transaction(identifier)
            except PaymentsAPIError as exc:
                if exc.code != "transaction_not_found":
                    raise
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise PaymentsPollTimeout(identifier) from exc
                time.sleep(min(interval, remaining))
                continue
            if snapshot.snapshot.transaction.root != identifier:
                raise PaymentsProtocolError("service returned a snapshot for another transaction")
            return snapshot

    def attach_agreement(
        self, transaction: str, agreement_json: dict[str, Any]
    ) -> StoredDealAttachment:
        """Attach the opaque Agreement for the service's dispute record."""

        identifier = _transaction_id(transaction)
        request = DealAttachment.model_validate({"kind": "deal", "content": agreement_json})
        payload = self._request(
            "POST",
            f"/transactions/{identifier}/attachments",
            json=_json(request),
        )
        return _validated(StoredDealAttachment, payload)

    def ensure_agreement_attached(
        self,
        transaction: str,
        agreement_json: dict[str, Any],
        option: PaymentsOptionParams,
    ) -> StoredDealAttachment | None:
        """Deposit the Agreement when the seller option advertises that setting."""

        if not option.deposit_agreement:
            return None
        identifier = _transaction_id(transaction)
        expected_deal = agreement_hash(agreement_json)
        snapshot = self.get_transaction(identifier).snapshot
        if snapshot.transaction.root != identifier or snapshot.receipt.receipt.deal.root.root != expected_deal:
            raise PaymentsProtocolError("transaction does not commit to the supplied Agreement")
        # Every attachment is a deal attachment the service checked against the
        # deal hash, so any other hash means the service broke its contract.
        existing = None
        for attachment in snapshot.attachments:
            if attachment.sha256.root != expected_deal:
                raise PaymentsProtocolError("transaction contains an unexpected deal attachment")
            existing = existing or attachment
        if existing is not None:
            return existing
        return self.attach_agreement(identifier, agreement_json)

    def reverse(self, transaction: str) -> StoredEvent:
        """Reverse all still-held parts with a stable transaction-scoped retry ID."""

        identifier = _transaction_id(transaction)
        event = EventCommand.model_validate({"kind": "reverse"})
        payload = self._request(
            "POST",
            f"/transactions/{identifier}/events",
            headers={"Idempotency-Key": f"reverse-{identifier}"},
            json=_json(event),
        )
        return _validated(StoredEvent, payload)

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx.RequestError as exc:
            raise PaymentsTransportError("payments service request failed") from exc
        if not response.is_success:
            if response.status_code < 400:
                raise PaymentsProtocolError("payments service returned an unexpected redirect")
            try:
                error = ApiError.model_validate(response.json())
                code = error.error.value
            except (ValueError, ValidationError, AttributeError):
                code = "invalid_error_response"
            raise PaymentsAPIError(response.status_code, code)
        try:
            return response.json()
        except ValueError as exc:
            raise PaymentsProtocolError("payments service returned invalid JSON") from exc


def _validated(model: type[_ModelT], value: Any) -> _ModelT:
    try:
        return model.model_validate(value)
    except ValidationError as exc:
        raise PaymentsProtocolError("payments service response violates the published schema") from exc


def _json(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json", by_alias=True, exclude_none=True)


def _transaction_id(value: str) -> str:
    if not isinstance(value, str) or not _TRANSACTION_ID.fullmatch(value):
        raise ValueError("transaction must be a lowercase SHA-256 hex ID")
    return value


def _is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
