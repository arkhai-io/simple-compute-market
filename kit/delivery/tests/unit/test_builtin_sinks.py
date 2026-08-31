"""The built-in sinks are protocol-thin, bounded, and safe with opaque input."""

from __future__ import annotations

import json
import smtplib
import sys
import urllib.error
from pathlib import Path

import pytest

from market_delivery import DeliveryError, introduction_delivery_event
from market_delivery.builtin.command_sink import build_command_sink
from market_delivery.builtin.file_sink import build_file_sink
from market_delivery.builtin.smtp_sink import build_smtp_sink
from market_delivery.builtin.webhook_sink import build_webhook_sink

HOSTILE = "; rm -rf / #$(whoami)`id`"


def _event(contact=None):
    return introduction_delivery_event(
        {
            "obligation_ref": "d" * 64,
            "revealed": True,
            "introduction": {"channel": "telegram"},
            "counterparty_contact": contact or {"telegram": "@seller"},
        },
        role="buyer",
    )


def test_file_sink_appends_one_json_line_per_event(tmp_path) -> None:
    target = tmp_path / "introductions.jsonl"
    sink = build_file_sink({"path": str(target)})

    sink(_event())
    sink(_event())

    lines = target.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["contact"] == {"telegram": "@seller"}


def test_file_sink_reports_an_unwritable_path(tmp_path) -> None:
    sink = build_file_sink({"path": str(tmp_path / "missing" / "out.jsonl")})

    with pytest.raises(DeliveryError, match="could not append"):
        sink(_event())


def test_file_sink_requires_a_path() -> None:
    with pytest.raises(Exception):
        build_file_sink({})


def test_command_sink_passes_hostile_content_on_stdin_unevaluated(tmp_path) -> None:
    captured = tmp_path / "captured"
    sink = build_command_sink(
        {
            "argv": [
                sys.executable,
                "-c",
                "import sys,pathlib;"
                f"pathlib.Path({str(captured)!r}).write_bytes(sys.stdin.buffer.read())",
            ]
        }
    )

    sink(_event({"telegram": HOSTILE}))

    payload = json.loads(captured.read_text(encoding="utf-8"))
    assert payload["contact"]["telegram"] == HOSTILE
    # Nothing the shell would have expanded ran: the marker file is the only
    # artifact, and the hostile text arrived intact rather than interpreted.
    assert not list(Path(tmp_path).glob("*whoami*"))


def test_command_sink_can_send_the_rendered_text(tmp_path) -> None:
    captured = tmp_path / "text"
    sink = build_command_sink(
        {
            "argv": [
                sys.executable,
                "-c",
                "import sys,pathlib;"
                f"pathlib.Path({str(captured)!r}).write_text(sys.stdin.read())",
            ],
            "send": "text",
        }
    )

    sink(_event())

    assert captured.read_text(encoding="utf-8").startswith("Introduction revealed")


def test_command_sink_reports_a_failing_program() -> None:
    sink = build_command_sink({"argv": [sys.executable, "-c", "raise SystemExit(3)"]})

    with pytest.raises(DeliveryError, match="status 3"):
        sink(_event())


def test_command_sink_reports_a_missing_program() -> None:
    sink = build_command_sink({"argv": ["definitely-not-a-real-program-xyz"]})

    with pytest.raises(DeliveryError, match="not found"):
        sink(_event())


def test_command_sink_bounds_a_slow_program() -> None:
    sink = build_command_sink(
        {
            "argv": [sys.executable, "-c", "import time; time.sleep(30)"],
            "timeout_seconds": 0.3,
        }
    )

    with pytest.raises(DeliveryError, match="timed out"):
        sink(_event())


def test_command_sink_rejects_an_empty_or_shell_shaped_command() -> None:
    with pytest.raises(Exception):
        build_command_sink({"argv": []})
    with pytest.raises(Exception):
        build_command_sink({"argv": ["echo hi"], "send": "shell"})


def test_webhook_sink_posts_the_event_as_json(monkeypatch) -> None:
    seen = {}

    class Response:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout=None):
        seen["url"] = request.full_url
        seen["body"] = json.loads(request.data.decode("utf-8"))
        seen["headers"] = request.headers
        seen["timeout"] = timeout
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    sink = build_webhook_sink(
        {
            "url": "https://example.invalid/hook",
            "headers": {"X-Token": "secret-token"},
            "timeout_seconds": 3.0,
        }
    )

    sink(_event())

    assert seen["url"] == "https://example.invalid/hook"
    assert seen["body"]["obligation_ref"] == "d" * 64
    assert seen["timeout"] == 3.0
    assert seen["headers"]["X-token"] == "secret-token"


def test_webhook_sink_reports_a_rejecting_endpoint_without_the_url(monkeypatch) -> None:
    def fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError(
            "https://example.invalid/hook?token=secret", 500, "boom", {}, None
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    sink = build_webhook_sink({"url": "https://example.invalid/hook?token=secret"})

    with pytest.raises(DeliveryError) as failure:
        sink(_event())

    assert "status 500" in str(failure.value)
    assert "secret" not in str(failure.value)


def test_webhook_sink_reports_an_unreachable_endpoint(monkeypatch) -> None:
    def fake_urlopen(request, timeout=None):
        raise urllib.error.URLError(TimeoutError("timed out"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    sink = build_webhook_sink({"url": "https://example.invalid/hook"})

    with pytest.raises(DeliveryError, match="unreachable"):
        sink(_event())


def test_webhook_sink_requires_an_http_url() -> None:
    with pytest.raises(ValueError, match="http"):
        build_webhook_sink({"url": "file:///etc/passwd"})


def test_webhook_settings_keep_the_url_and_headers_out_of_their_repr() -> None:
    from market_delivery.builtin.webhook_sink import WebhookSinkSettings

    settings = WebhookSinkSettings(
        url="https://example.invalid/hook?token=secret",
        headers={"X-Token": "secret-token"},
    )

    assert "secret" not in repr(settings)


def test_smtp_sink_sends_one_rendered_message(monkeypatch) -> None:
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            sent["endpoint"] = (host, port, timeout)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self):
            sent["starttls"] = True

        def login(self, username, password):
            sent["login"] = username

        def send_message(self, message):
            sent["subject"] = message["Subject"]
            sent["to"] = message["To"]
            sent["body"] = message.get_content()

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    sink = build_smtp_sink(
        {
            "host": "mail.example.invalid",
            "sender": "me@example.invalid",
            "recipients": ["me@example.invalid"],
            "username": "me",
            "password": "hunter2",
            "timeout_seconds": 6.0,
        }
    )

    sink(_event())

    assert sent["endpoint"] == ("mail.example.invalid", 587, 6.0)
    assert sent["starttls"] is True
    assert sent["login"] == "me"
    assert sent["subject"] == f"Introduction revealed: {'d' * 64}"
    assert sent["body"].startswith("Introduction revealed")


def test_smtp_sink_reports_a_refusing_server_without_the_password(monkeypatch) -> None:
    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self):
            pass

        def login(self, username, password):
            raise smtplib.SMTPAuthenticationError(535, b"bad hunter2")

        def send_message(self, message):
            pass

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    sink = build_smtp_sink(
        {
            "host": "mail.example.invalid",
            "sender": "me@example.invalid",
            "recipients": ["me@example.invalid"],
            "username": "me",
            "password": "hunter2",
        }
    )

    with pytest.raises(DeliveryError) as failure:
        sink(_event())

    assert "hunter2" not in str(failure.value)


def test_smtp_settings_require_a_username_with_a_password() -> None:
    with pytest.raises(ValueError, match="username"):
        build_smtp_sink(
            {
                "host": "mail.example.invalid",
                "sender": "me@example.invalid",
                "recipients": ["me@example.invalid"],
                "password": "hunter2",
            }
        )
