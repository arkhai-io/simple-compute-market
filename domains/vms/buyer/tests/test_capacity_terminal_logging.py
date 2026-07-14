"""Durable, typed terminal records for pinned capacity buys."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from domains.vms.buyer.cli import app
from market_config.config_loader import ChainConfig


BUYER_ADDRESS = "0x" + "11" * 20
BUYER_PRIVATE_KEY = "0x" + "22" * 32
TOKEN = "0x" + "33" * 20


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture(autouse=True)
def isolated_buyer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(
        "domains.vms.buyer.common.resolve_buyer_wallet",
        lambda **_kwargs: (BUYER_ADDRESS, BUYER_PRIVATE_KEY),
    )
    monkeypatch.setattr(
        "domains.vms.buyer.common.resolve_ssh_public_key",
        lambda **_kwargs: "ssh-ed25519 AAAA capacity@test",
    )
    monkeypatch.setattr(
        "domains.vms.buyer.common.resolve_indexer_urls_for_schema",
        lambda *_args, **_kwargs: ["http://registry.test"],
    )
    monkeypatch.setattr(
        "domains.vms.buyer.common.resolve_discovery_timeout",
        lambda **_kwargs: 1.0,
    )
    monkeypatch.setattr(
        "domains.vms.buyer.common.resolve_indexer_auth",
        lambda: {},
    )
    monkeypatch.setattr(
        "domains.vms.buyer.common.select_chain_for_listing",
        lambda **_kwargs: ChainConfig(
            name="anvil",
            rpc_url="http://rpc.test",
            chain_id=31337,
            alkahest_address_config_path="/tmp/alkahest.json",
        ),
    )
    monkeypatch.setattr(
        "core_buyer.escrow_client.make_buyer_payment_escrow_terms_fn",
        lambda **_kwargs: lambda *_args, **_inner: [],
    )
    monkeypatch.setattr(
        "core_buyer.escrow_client.make_create_escrow_fn",
        lambda **_kwargs: lambda _escrows: [],
    )


def _pinned_args(*, explicit_prices: bool = True) -> list[str]:
    args = [
        "buy",
        "--duration-hours",
        "1",
        "--listing-id",
        "listing-1",
        "--seller",
        "http://seller.test",
        "--chain",
        "anvil",
        "--yes",
    ]
    if explicit_prices:
        args.extend(
            [
                "--initial-price",
                "1",
                "--max-price",
                "1",
                "--token-contract",
                TOKEN,
                "--token-decimals",
                "0",
            ]
        )
    return args


def _only_run_events(tmp_path: Path) -> list[dict]:
    paths = list((tmp_path / "state" / "arkhai" / "buy-runs").glob("*.jsonl"))
    assert len(paths) == 1
    return [json.loads(line) for line in paths[0].read_text().splitlines() if line]


def test_exact_pin_absent_from_registry_ends_as_capacity_exhausted(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "domains.vms.buyer.buy_cli.query_registry_for_matches_multi",
        lambda *_args, **_kwargs: [],
    )

    result = runner.invoke(app, _pinned_args())

    assert result.exit_code == 0, result.output
    events = _only_run_events(tmp_path)
    assert [item["event"] for item in events] == ["run_started", "run_ended"]
    assert events[0]["listing_id"] == "listing-1"
    assert events[0]["seller_url"] == "http://seller.test"
    assert events[-1]["status"] == "capacity_exhausted"
    assert events[-1]["reason"] == "capacity_exhausted"
    assert events[-1]["reason_code"] == "pinned_listing_not_discoverable"


def test_pinned_registry_error_still_has_terminal_log(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_registry(*_args, **_kwargs):
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr(
        "domains.vms.buyer.buy_cli.query_registry_for_matches_multi",
        fail_registry,
    )

    result = runner.invoke(app, _pinned_args())

    assert result.exit_code == 3
    events = _only_run_events(tmp_path)
    assert events[-1]["status"] == "error"
    assert events[-1]["reason_code"] == "registry_query_failed"
    assert "registry unavailable" in events[-1]["error"]


def test_pinned_price_selection_exit_is_not_capacity_exhaustion(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    listing = {
        "listing_id": "listing-1",
        "seller": "http://seller.test",
        "accepted_escrows": [],
    }
    monkeypatch.setattr(
        "domains.vms.buyer.buy_cli.query_registry_for_matches_multi",
        lambda *_args, **_kwargs: [listing],
    )
    monkeypatch.setattr(
        "domains.vms.buyer.buy_cli._resolve_prices_from_matches",
        lambda **_kwargs: (None, None),
    )

    result = runner.invoke(app, _pinned_args(explicit_prices=False))

    assert result.exit_code == 2
    terminal = _only_run_events(tmp_path)[-1]
    assert terminal["status"] == "exited"
    assert terminal["reason_code"] == "price_selection_unavailable_or_declined"
