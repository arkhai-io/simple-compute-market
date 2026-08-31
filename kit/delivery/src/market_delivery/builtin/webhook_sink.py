"""POST each event as JSON to one configured endpoint.

Covers a chat webhook, an automation runner, or a personal bot without the
marketplace learning any of their formats. Failures report a status code and
never the URL, which commonly carries the operator's own token.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any

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


def build_webhook_sink(settings: Mapping[str, Any]) -> DeliverySink:
    """Configure the POST-to-an-endpoint sink."""

    config = WebhookSinkSettings.model_validate(dict(settings))
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
        data = json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")
        request = urllib.request.Request(  # noqa: S310 - scheme checked above
            config.url,
            data=data,
            method="POST",
            headers={"Content-Type": "application/json", **config.headers},
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
