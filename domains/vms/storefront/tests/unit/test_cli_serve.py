"""Unit tests for the ``market-storefront serve`` CLI boundary."""

from __future__ import annotations

from typer.testing import CliRunner


def test_serve_passes_only_supported_arguments_to_run_serve(monkeypatch):
    from market_storefront.cli import app
    import market_storefront.server as server_mod

    calls: list[dict] = []

    def fake_run_serve(*, host: str = "0.0.0.0", port: int | None = None) -> None:
        calls.append({"host": host, "port": port})

    monkeypatch.setattr(server_mod, "run_serve", fake_run_serve)

    result = CliRunner().invoke(app, ["serve", "--host", "127.0.0.1", "--port", "9001"])

    assert result.exit_code == 0, result.output
    assert calls == [{"host": "127.0.0.1", "port": 9001}]


def test_serve_help_does_not_advertise_removed_publish_loop_options():
    from market_storefront.cli import app

    result = CliRunner().invoke(app, ["serve", "--help"])

    assert result.exit_code == 0
    assert "--no-publish" not in result.output
    assert "--publish-poll-interval" not in result.output
