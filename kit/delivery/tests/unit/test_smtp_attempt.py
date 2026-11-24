"""Synthetic SMTP protocol outcomes; no network or provider access."""

import multiprocessing
import signal
import smtplib
import ssl
import threading
import time
from email.message import EmailMessage
from functools import partial

import pytest
from market_delivery.builtin.smtp_attempt import send_bounded_smtp, smtp_attempt

CONFIG = dict(
    host="smtp.example.invalid",
    port=587,
    sender="sender@example.invalid",
    username="test",
    password="synthetic-test-only",
)


class FakeSMTP:
    def __init__(self, host=None, port=None, timeout=None):
        self.calls = []
        self.sock = self
        self.tls = True
        self.error = None
        self.rcpt_code = 250
        self.data_code = 250
        self.quit_error = False

    def settimeout(self, timeout):
        assert 0 < timeout <= 10

    def ehlo(self):
        self.calls.append("ehlo")

    def has_extn(self, name):
        assert name == "starttls"
        return self.tls

    def starttls(self, *, context):
        assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
        self.calls.append("tls")
        if self.error == "cert":
            raise ssl.SSLCertVerificationError("synthetic certificate mismatch")

    def login(self, username, password):
        assert "tls" in self.calls
        self.calls.append("auth")
        if self.error == "auth":
            raise smtplib.SMTPAuthenticationError(535, b"private-provider-error")

    def mail(self, sender):
        self.calls.append("mail")
        return 250, b"ok"

    def rcpt(self, address):
        self.calls.append("rcpt")
        self.recipient = address
        return self.rcpt_code, b"private-provider-error"

    def data(self, message):
        self.calls.append("data")
        self.message = message
        if self.error == "lost-ack":
            raise OSError("private-provider-error")
        return self.data_code, b"private-provider-error"

    def quit(self):
        self.calls.append("quit")
        if self.quit_error:
            raise OSError("private-provider-error")

    def close(self):
        self.calls.append("close")


def attempt(fake, **kwargs):
    message = EmailMessage()
    message.set_content("Synthetic contact only")
    return smtp_attempt(
        CONFIG,
        "recipient@example.invalid",
        message,
        deadline=120,
        clock=lambda: 0,
        smtp_factory=lambda *a, **k: fake,
        **kwargs,
    )


@pytest.mark.parametrize(
    "error,expected",
    [
        ("cert", ("failed", "tls_verification_failed")),
        ("auth", ("failed", "authentication_rejected")),
        ("lost-ack", ("needs_review", "acceptance_unknown")),
    ],
)
def test_failures_are_bounded_and_no_provider_text(error, expected):
    fake = FakeSMTP()
    fake.error = error
    assert attempt(fake) == expected
    if error == "cert":
        assert "auth" not in fake.calls and "data" not in fake.calls


def test_missing_tls_never_authenticates_or_sends():
    fake = FakeSMTP()
    fake.tls = False
    assert attempt(fake) == ("failed", "tls_required")
    assert fake.calls == ["ehlo", "close"]


def test_positive_data_ack_dominates_quit_failure():
    fake = FakeSMTP()
    fake.quit_error = True
    acks = []
    assert attempt(fake, on_accepted=lambda: acks.append(True)) == ("accepted", None)
    assert acks == [True]
    assert fake.calls[-2:] == ["quit", "close"]


@pytest.mark.parametrize(
    "code,expected",
    [
        (450, ("retry_wait", "provider_temporary")),
        (550, ("failed", "recipient_rejected")),
    ],
)
def test_recipient_refusal_is_not_ignored(code, expected):
    fake = FakeSMTP()
    fake.rcpt_code = code
    assert attempt(fake) == expected
    assert "data" not in fake.calls


def test_lost_ownership_cannot_initiate_data():
    fake = FakeSMTP()
    assert attempt(fake, before_data=lambda: False) == (
        "needs_review",
        "attempt_abandoned",
    )
    assert "data" not in fake.calls


def test_pause_beyond_deadline_cannot_initiate_data():
    fake = FakeSMTP()
    clock = [0]

    def pause():
        clock[0] = 121
        return True

    assert smtp_attempt(
        CONFIG,
        "recipient@example.invalid",
        EmailMessage(),
        deadline=120,
        clock=lambda: clock[0],
        smtp_factory=lambda *a, **k: fake,
        before_data=pause,
    ) == ("needs_review", "attempt_abandoned")
    assert "data" not in fake.calls


class HungSMTP:
    def __init__(self, *args, **kwargs):
        # Model a resolver/provider operation that does not respond to Python's
        # alarm. The supervising process must kill and join this sole owner.
        signal.signal(signal.SIGALRM, signal.SIG_IGN)
        threading.Event().wait(30)
        raise AssertionError("must be stopped before any SMTP operation")


def owns_attempt():
    return True


def test_hard_deadline_kills_and_joins_the_network_owner():
    before = {child.pid for child in multiprocessing.active_children()}
    start = time.monotonic()
    result = send_bounded_smtp(
        CONFIG,
        "recipient@example.invalid",
        "Synthetic contact",
        "a" * 64,
        "synthetic-message",
        deadline=start + 0.5,
        before_data=owns_attempt,
        smtp_factory=HungSMTP,
    )
    assert result == ("needs_review", "acceptance_unknown")
    assert time.monotonic() - start < 3
    assert {child.pid for child in multiprocessing.active_children()} == before


class BlockedQuitSMTP(FakeSMTP):
    def __init__(self, *args, quit_entered, close_called, **kwargs):
        super().__init__(*args, **kwargs)
        self.quit_entered = quit_entered
        self.close_called = close_called

    def quit(self):
        assert self.calls[-1] == "data"
        signal.signal(signal.SIGALRM, signal.SIG_IGN)
        self.quit_entered.set()
        threading.Event().wait(30)
        raise AssertionError("supervisor must stop blocked cleanup")

    def close(self):
        self.close_called.set()


def test_spawned_positive_data_ack_survives_blocked_quit_and_killed_child():
    context = multiprocessing.get_context("spawn")
    quit_entered, close_called = context.Event(), context.Event()
    before = {child.pid for child in multiprocessing.active_children()}
    start = time.monotonic()
    result = send_bounded_smtp(
        CONFIG,
        "recipient@example.invalid",
        "Synthetic contact",
        "a" * 64,
        "synthetic-message",
        deadline=start + 2,
        before_data=owns_attempt,
        smtp_factory=partial(
            BlockedQuitSMTP, quit_entered=quit_entered, close_called=close_called
        ),
    )
    assert quit_entered.is_set() and not close_called.is_set()
    assert result == ("accepted", None)
    assert time.monotonic() - start < 3
    assert {child.pid for child in multiprocessing.active_children()} == before
