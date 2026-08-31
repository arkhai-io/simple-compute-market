"""Send each event as one plain-text mail message."""

from __future__ import annotations

import smtplib
from collections.abc import Mapping
from email.message import EmailMessage
from typing import Any

from pydantic import Field

from ..events import DeliveryEvent
from ..sinks import DeliveryError, DeliverySink, SinkSettings


class SmtpSinkSettings(SinkSettings):
    host: str = Field(min_length=1)
    port: int = Field(default=587, ge=1, le=65535)
    sender: str = Field(min_length=1)
    recipients: tuple[str, ...] = Field(min_length=1)
    start_tls: bool = True
    username: str | None = Field(default=None, repr=False)
    password: str | None = Field(
        default=None,
        repr=False,
        json_schema_extra={"secret": True},
    )
    subject_prefix: str = "Introduction revealed"


def build_smtp_sink(settings: Mapping[str, Any]) -> DeliverySink:
    """Configure the send-one-message sink."""

    config = SmtpSinkSettings.model_validate(dict(settings))
    if config.password is not None and config.username is None:
        raise ValueError("smtp sink password requires a username")
    timeout = config.timeout_seconds

    def deliver_by_mail(event: DeliveryEvent) -> None:
        message = EmailMessage()
        message["Subject"] = f"{config.subject_prefix}: {event.obligation_ref}"
        message["From"] = config.sender
        message["To"] = ", ".join(config.recipients)
        message.set_content(event.rendered)
        try:
            with smtplib.SMTP(config.host, config.port, timeout=timeout) as client:
                if config.start_tls:
                    client.starttls()
                if config.username is not None:
                    client.login(config.username, config.password or "")
                client.send_message(message)
        except smtplib.SMTPAuthenticationError as exc:
            raise DeliveryError("the mail server rejected the configured login") from exc
        except smtplib.SMTPException as exc:
            raise DeliveryError(
                f"the mail server refused the message ({type(exc).__name__})"
            ) from exc
        except OSError as exc:
            raise DeliveryError(
                f"the mail server could not be reached ({type(exc).__name__})"
            ) from exc

    return deliver_by_mail


__all__ = ["SmtpSinkSettings", "build_smtp_sink"]
