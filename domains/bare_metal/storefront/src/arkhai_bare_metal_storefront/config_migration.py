"""Explicit, atomic settlement configuration migration for bare-metal sellers."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import typer
from market_alkahest import ALKAHEST_CONFIG_KEY, require_deliverable_release_models
from market_config.settlement_migration import (
    SettlementMigrationError,
    format_migration_result,
    migrate_settlement_config,
)
from market_settlement_runtime import SettlementRole

from .settlement_composition import SELLER_STAGES, build_bare_metal_settlement_registry

config_app = typer.Typer(no_args_is_help=True)


def _validate_candidate(document: Mapping[str, Any], role: SettlementRole) -> None:
    registry = build_bare_metal_settlement_registry()
    config = registry.resolve(document.get("Settlement", {}), role=role)
    require_deliverable_release_models(
        config.mechanism_config(ALKAHEST_CONFIG_KEY),
        SELLER_STAGES["alkahest.v1"].release_models,
    )


@config_app.command("migrate")
def migrate(
    config: Path = typer.Option(..., "--config", help="The seller TOML file to migrate."),
    scope: str = typer.Option(..., "--scope", help="Configuration scope: settlement."),
    check: bool = typer.Option(False, "--check", help="Preview redacted changes only."),
    write: bool = typer.Option(False, "--write", help="Validate and atomically replace."),
    backup: bool = typer.Option(False, "--backup", help="Keep a restrictive backup."),
) -> None:
    """Migrate one configuration file without starting the storefront."""
    if scope != "settlement":
        raise typer.BadParameter("only --scope settlement is supported")
    registry = build_bare_metal_settlement_registry()
    installed = {item.mechanism_id: item.config_key for item in registry.registrations}
    try:
        result = migrate_settlement_config(
            config, role="seller", check=check, write=write, backup=backup,
            installed=installed, validator=_validate_candidate,
        )
    except SettlementMigrationError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    for line in format_migration_result(result):
        typer.echo(line)
