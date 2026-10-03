"""POST each event as JSON to one configured endpoint.

Covers a chat webhook, an automation runner, a seller's own API, or a personal
bot without the marketplace learning any of their formats. Failures report a
status code and never the URL, which commonly carries the operator's own token.

With ``sign = true`` the request is signed with the process's marketplace
signer as a v2 marketplace request, so the receiving API can verify the sender
against the storefront principal it already trusts rather than relying on the
secrecy of its URL. The signed body is the canonical JSON of the event, the
bytes the signature's body hash covers.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Mapping
from typing import Any

from market_identity import (
    RequestEnvelope,
    Signer,
    canonical_body_hash,
    canonical_json,
    sign_request,
)
from pydantic import Field

from ..events import DeliveryEvent
from ..sinks import DeliveryError, DeliverySink, SinkSettings


class WebhookSinkSettings(SinkSettings):
    url: str = Field(
        min_length=1,
        repr=False,
        json_schema_extra={"secret": True},
    )
    headers: dict[str, str] = Field(
        default_factory=dict,
        repr=False,
        json_schema_extra={"secret": True},
    )
    send: str = "json"
    sign: bool = False


#: The marketplace v2 request-authentication headers, as every signed
#: marketplace request carries them.
SIGNED_DELIVERY_ROLE = "seller"
SIGNED_DELIVERY_OPERATION = "introduction_delivery"
_SIGNATURE_VERSION_HEADER = "X-Market-Signature-Version"
_IDENTITY_SCHEME_HEADER = "X-Market-Identity-Scheme"
_IDENTITY_IDENTIFIER_HEADER = "X-Market-Identity-Identifier"
_ROLE_HEADER = "X-Market-Role"
_REQUEST_ID_HEADER = "X-Market-Request-ID"
_TIMESTAMP_HEADER = "X-Market-Timestamp"
_SIGNATURE_HEADER = "X-Market-Signature"


def _signed_request(
    signer: Signer, body: Any, resource: str
) -> tuple[bytes, dict[str, str]]:
    authenticated = sign_request(
        signer=signer,
        envelope=RequestEnvelope(
            role=SIGNED_DELIVERY_ROLE,
            principal=signer.identity,
            method="POST",
            operation=SIGNED_DELIVERY_OPERATION,
            resource=resource,
            request_id=uuid.uuid4().hex,
            timestamp=int(time.time()),
            body_hash=canonical_body_hash(body),
        ),
    )
    return canonical_json(body), {
        _SIGNATURE_VERSION_HEADER: authenticated.protocol,
        _IDENTITY_SCHEME_HEADER: authenticated.principal.scheme.value,
        _IDENTITY_IDENTIFIER_HEADER: authenticated.principal.identifier,
        _ROLE_HEADER: authenticated.role,
        _REQUEST_ID_HEADER: authenticated.request_id,
        _TIMESTAMP_HEADER: str(authenticated.timestamp),
        _SIGNATURE_HEADER: authenticated.proof.value,
    }


def build_webhook_sink(
    settings: Mapping[str, Any],
    *,
    signer: Signer | None = None,
) -> DeliverySink:
    """Configure the POST-to-an-endpoint sink."""

    config = WebhookSinkSettings.model_validate(dict(settings))
    if config.sign and signer is None:
        raise ValueError("a signing webhook requires the process's marketplace signer")
    if not config.url.startswith(("http://", "https://")):
        raise ValueError("webhook sink url must be an http or https URL")
    if config.send not in {"json", "text"}:
        raise ValueError("webhook sink send must be 'json' or 'text'")
    timeout = config.timeout_seconds

    def deliver_to_webhook(event: DeliveryEvent) -> None:
        if config.send == "text":
            body = {"text": event.rendered}
        else:
            body = event.payload()
        signed_headers: dict[str, str] = {}
        if config.sign and signer is not None:
            data, signed_headers = _signed_request(signer, body, event.obligation_ref)
        else:
            data = json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")
        request = urllib.request.Request(  # noqa: S310 - scheme checked above
            config.url,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                **config.headers,
                **signed_headers,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                status = getattr(response, "status", 200)
        except urllib.error.HTTPError as exc:
            # The URL is deliberately absent: a webhook URL is usually the
            # credential, and this string is written to an operator's log.
            raise DeliveryError(
                f"the configured endpoint returned status {exc.code}"
            ) from exc
        except urllib.error.URLError as exc:
            raise DeliveryError(
                f"the configured endpoint was unreachable ({type(exc.reason).__name__})"
            ) from exc
        except OSError as exc:
            raise DeliveryError(
                f"the configured endpoint could not be reached ({type(exc).__name__})"
            ) from exc
        if status is not None and int(status) >= 400:
            raise DeliveryError(f"the configured endpoint returned status {status}")

    return deliver_to_webhook


__all__ = ["WebhookSinkSettings", "build_webhook_sink"]
