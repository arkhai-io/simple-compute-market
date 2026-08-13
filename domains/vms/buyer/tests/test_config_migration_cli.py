from __future__ import annotations

from pathlib import Path

import typer
from market_config.settlement_migration import (
    BUYER_MIGRATION_COMMAND,
    MigrationAction,
    SettlementMigrationResult,
)
from typer.testing import CliRunner


def _app() -> typer.Typer:
    from domains.vms.buyer.config_cli import config_app

    app = typer.Typer()
    app.add_typer(config_app, name="config")
    return app


def test_buyer_registers_settlement_migration_check(monkeypatch, tmp_path: Path) -> None:
    from domains.vms.buyer import config_cli

    path = tmp_path / "buyer.toml"
    path.write_text("[settlement]\nmechanism_priority = ['alkahest.v1']\n")
    captured: dict[str, object] = {}

    def migrate(received: Path, **kwargs: object) -> SettlementMigrationResult:
        captured.update(kwargs)
        return SettlementMigrationResult(
            path=received,
            changed=True,
            written=False,
            actions=(
                MigrationAction(
                    "move",
                    "settlement.mechanism_priority",
                    "Settlement.priority",
                ),
            ),
        )

    monkeypatch.setattr(config_cli, "user_config_file", lambda: path)
    monkeypatch.setattr(config_cli, "migrate_settlement_config", migrate)

    result = CliRunner().invoke(
        _app(), ["config", "migrate", "--scope", "settlement", "--check"]
    )

    assert result.exit_code == 0
    assert captured["role"] == "buyer"
    assert captured["check"] is True
    assert captured["write"] is False
    assert captured["backup"] is False
    assert callable(captured["validator"])
    assert "value redacted" in result.output
    assert "Settlement.priority" in result.output


def test_buyer_config_set_rejects_legacy_path_with_exact_command(
    monkeypatch,
) -> None:
    from domains.vms.buyer import config_cli

    monkeypatch.setattr(
        config_cli,
        "write_user_config",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("legacy edit reached writer")
        ),
    )

    result = CliRunner().invoke(
        _app(),
        ["config", "set", "settlement.mechanism_priority", "alkahest.v1"],
    )

    assert result.exit_code == 2
    assert BUYER_MIGRATION_COMMAND in result.output
