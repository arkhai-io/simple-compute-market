"""Deliver each event through Apprise to the services its URLs name.

Apprise reaches email, chat, SMS, and push services from one URL each
(``mailto://``, ``slack://``, ``tgram://``, ``sns://``, and many more), so an
operator can be told about a reveal wherever they read things without the
marketplace implementing any of those services. The URLs routinely embed the
service's own token, so they are secret settings, and a failure names neither
a URL nor what was being carried.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import apprise
from market_delivery import (
    DeclaredSink,
    DeliveryError,
    DeliveryEvent,
    DeliverySink,
    SinkSettings,
)
from pydantic import Field


class AppriseSinkSettings(SinkSettings):
    urls: tuple[str, ...] = Field(
        min_length=1,
        repr=False,
        json_schema_extra={"secret": True},
    )
    title: str = "Introduction revealed"


def build_apprise_sink(settings: Mapping[str, Any]) -> DeliverySink:
    """Configure the Apprise sink, refusing a URL Apprise does not recognise."""

    config = AppriseSinkSettings.model_validate(dict(settings))
    notifier = apprise.Apprise()
    for index, url in enumerate(config.urls):
        if not notifier.add(url):
            # The position, never the URL: the URL is usually the credential.
            raise ValueError(f"apprise sink url {index} is not a URL Apprise recognises")

    def deliver_through_apprise(event: DeliveryEvent) -> None:
        try:
            delivered = notifier.notify(title=config.title, body=event.rendered)
        except Exception as exc:  # noqa: BLE001 - reported by class alone
            raise DeliveryError(
                f"apprise delivery raised {type(exc).__name__}"
            ) from exc
        if not delivered:
            raise DeliveryError("apprise reported that a configured service was not notified")

    return deliver_through_apprise


#: The installed sink: its factory with the settings model it declares.
APPRISE_SINK = DeclaredSink(build_apprise_sink, AppriseSinkSettings)


__all__ = ["APPRISE_SINK", "AppriseSinkSettings", "build_apprise_sink"]
