"""One verified-TLS SMTP attempt with bounded, isolated network ownership.

The child owns DNS and the socket. Killing and joining it bounds DNS as well as
SMTP; a timed-out sending thread would not provide that guarantee.
"""

from __future__ import annotations

import multiprocessing
import signal
import smtplib
import ssl
import time
from collections.abc import Callable, Mapping
from email.message import EmailMessage
from typing import Any

# Outcomes contain no provider text, credentials, route, or rendered message.
Outcome = tuple[str, str | None]


def smtp_attempt(
    config: Mapping[str, Any],
    address: str,
    message: EmailMessage,
    *,
    deadline: float,
    smtp_factory: Callable[..., Any] = smtplib.SMTP,
    clock: Callable[[], float] = time.monotonic,
    before_data: Callable[[], bool] = lambda: True,
    on_accepted: Callable[[], None] = lambda: None,
) -> Outcome:
    client = None
    data_started = False
    accepted = False

    def budget() -> float:
        remaining = deadline - clock()
        if remaining <= 0:
            raise TimeoutError()
        timeout = min(10.0, remaining)
        if client is not None and client.sock is not None:
            client.sock.settimeout(timeout)
        return timeout

    try:
        client = smtp_factory(config["host"], config["port"], timeout=budget())
        budget()
        client.ehlo()
        if not client.has_extn("starttls"):
            return "failed", "tls_required"
        budget()
        client.starttls(context=ssl.create_default_context())
        budget()
        client.ehlo()
        budget()
        client.login(config["username"], config["password"])
        budget()
        code, _ = client.mail(config["sender"])
        if code != 250:
            return (
                ("retry_wait", "provider_temporary")
                if 400 <= code < 500
                else ("failed", "message_rejected")
            )
        budget()
        code, _ = client.rcpt(address)
        if code not in (250, 251):
            return (
                ("retry_wait", "provider_temporary")
                if 400 <= code < 500
                else ("failed", "recipient_rejected")
            )
        budget()
        if not before_data():
            return "needs_review", "attempt_abandoned"
        budget()
        data_started = True
        code, _ = client.data(message.as_bytes())
        if code == 250:
            accepted = True
            on_accepted()
            return "accepted", None
        return (
            ("retry_wait", "provider_temporary")
            if 400 <= code < 500
            else ("failed", "message_rejected")
        )
    except ssl.SSLCertVerificationError:
        return "failed", "tls_verification_failed"
    except smtplib.SMTPAuthenticationError:
        return "failed", "authentication_rejected"
    except smtplib.SMTPDataError as exc:
        return (
            ("retry_wait", "provider_temporary")
            if 400 <= exc.smtp_code < 500
            else ("failed", "message_rejected")
        )
    except (OSError, smtplib.SMTPException):
        if clock() >= deadline:
            return (
                "needs_review",
                "acceptance_unknown" if data_started else "attempt_abandoned",
            )
        return (
            ("needs_review", "acceptance_unknown")
            if data_started
            else ("retry_wait", "transport_unavailable")
        )
    finally:
        if client is not None:
            # DATA acceptance is authoritative even if QUIT/close fails.
            if accepted:
                try:
                    budget()
                    client.quit()
                except Exception:
                    pass
            try:
                client.close()
            except Exception:
                pass


def _child(
    pipe: Any,
    config: dict[str, Any],
    address: str,
    rendered: str,
    ref: str,
    message_id: str,
    deadline: float,
    before_data: Callable[[], bool],
    smtp_factory: Callable[..., Any],
) -> None:
    def timeout(_signum: int, _frame: Any) -> None:
        raise TimeoutError()

    signal.signal(signal.SIGALRM, timeout)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        pipe.send(("needs_review", "attempt_abandoned"))
        return
    signal.setitimer(signal.ITIMER_REAL, remaining)
    message = EmailMessage()
    message["Subject"] = f"Introduction revealed: {ref}"
    message["From"] = config["sender"]
    message["To"] = address
    message["Message-ID"] = f"<{message_id}@contact-delivery.invalid>"
    message.set_content(rendered)
    try:
        result = smtp_attempt(
            config,
            address,
            message,
            deadline=deadline,
            smtp_factory=smtp_factory,
            before_data=before_data,
            on_accepted=lambda: pipe.send(("accepted", None)),
        )
        pipe.send(result)
    except Exception:
        pipe.send(("needs_review", "acceptance_unknown"))
    finally:
        pipe.close()


def send_bounded_smtp(
    config: Mapping[str, Any],
    address: str,
    rendered: str,
    ref: str,
    message_id: str,
    *,
    deadline: float,
    before_data: Callable[[], bool],
    smtp_factory: Callable[..., Any] = smtplib.SMTP,
) -> Outcome:
    """Return only after the sole socket-owning process has stopped."""
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(
        target=_child,
        args=(
            child,
            dict(config),
            address,
            rendered,
            ref,
            message_id,
            deadline,
            before_data,
            smtp_factory,
        ),
    )
    try:
        process.start()
        child.close()
        process.join(max(0.0, deadline - time.monotonic()))
        if process.is_alive():
            process.kill()
            process.join()
        if parent.poll():
            try:
                return parent.recv()
            except EOFError:
                pass
        return "needs_review", "acceptance_unknown"
    finally:
        child.close()
        parent.close()
        if process.pid is not None:
            if process.is_alive():
                process.kill()
                process.join()
            process.close()
