from __future__ import annotations

import pytest

from core_buyer.action_policy import (
    BuyerActionHandler,
    BuyerActionPolicy,
    BuyerActionRequired,
    resolve_buyer_action_policy,
)


def _action() -> dict[str, object]:
    return {
        "kind": "browser_redirect",
        "url": "https://checkout.invalid/secret-token",
        "expires_at_unix": 1_800_000_000,
    }


def test_action_default_is_terminal_sensitive_and_yes_independent() -> None:
    assert resolve_buyer_action_policy(None, interactive=True) is BuyerActionPolicy.OPEN
    assert (
        resolve_buyer_action_policy(None, interactive=False) is BuyerActionPolicy.PRINT
    )
    assert (
        resolve_buyer_action_policy("fail", interactive=True) is BuyerActionPolicy.FAIL
    )


def test_open_records_only_public_metadata_and_deduplicates() -> None:
    opened: list[str] = []
    events: list[dict[str, str | int | None]] = []
    handler = BuyerActionHandler(
        BuyerActionPolicy.OPEN,
        open_url=opened.append,
        on_required=lambda metadata: events.append(metadata.as_event()),
    )

    handler.handle(_action())
    handler.handle(_action())

    assert opened == ["https://checkout.invalid/secret-token"]
    assert events == [
        {
            "action_kind": "browser_redirect",
            "action_expires_at_unix": 1_800_000_000,
        }
    ]
    assert "checkout.invalid" not in repr(handler)


def test_print_displays_url_without_putting_it_in_metadata() -> None:
    printed: list[str] = []
    metadata = BuyerActionHandler(
        BuyerActionPolicy.PRINT,
        print_url=printed.append,
    ).handle(_action())

    assert printed == ["https://checkout.invalid/secret-token"]
    assert metadata is not None
    assert metadata.as_event() == {
        "action_kind": "browser_redirect",
        "action_expires_at_unix": 1_800_000_000,
    }


def test_fail_preserves_sanitized_action_context_without_opening() -> None:
    opened: list[str] = []
    with pytest.raises(BuyerActionRequired) as caught:
        BuyerActionHandler(
            BuyerActionPolicy.FAIL,
            open_url=opened.append,
        ).handle(_action())

    assert opened == []
    assert caught.value.metadata.kind == "browser_redirect"
    assert "checkout.invalid" not in str(caught.value)
