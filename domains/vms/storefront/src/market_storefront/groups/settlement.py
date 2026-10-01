"""Seller settlement status and mechanism-owned administration commands."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import typer
from market_settlement_runtime import MechanismReadiness, SettlementConfig

settlement_app = typer.Typer(no_args_is_help=True)
alkahest_app = typer.Typer(no_args_is_help=True, help="Alkahest readiness checks.")


def _settlement_context() -> tuple[Any, SettlementConfig, dict[str, Any]]:
    from market_storefront.settlement_composition import (
        build_storefront_settlement_registry,
    )
    from market_storefront.utils.config import (
        CHAINS,
        get_evm_wallet_address,
        get_evm_wallet_private_key,
        settings,
        settlement_config_mapping,
    )

    registry = build_storefront_settlement_registry()
    config = registry.resolve(settlement_config_mapping(), role="seller")
    resources: dict[str, Any] = {}
    alkahest = config.mechanism_config("alkahest")
    if alkahest is not None and alkahest.enabled:
        resources.update(
            {
                "chains": CHAINS,
                "default_chain": getattr(settings, "chain_name", None),
                "wallet": {
                    "address": get_evm_wallet_address(),
                    "private_key": get_evm_wallet_private_key(),
                },
            }
        )
    return registry, config, resources


def _readiness() -> tuple[SettlementConfig, tuple[MechanismReadiness, ...]]:
    registry, config, resources = _settlement_context()
    statuses = asyncio.run(
        registry.ordered_readiness(config, role="seller", resources=resources)
    )
    return config, statuses


def _status_payload(
    config: SettlementConfig,
    statuses: tuple[MechanismReadiness, ...],
) -> dict[str, Any]:
    return {
        "schema_version": config.schema_version,
        "priority": list(config.priority),
        "mechanisms": [status.safe_projection() for status in statuses],
    }


def _render_status(status: MechanismReadiness) -> None:
    state = "ready" if status.ready else "disabled" if not status.enabled else "unready"
    typer.echo(f"{status.mechanism}: {state}")
    for blocker in status.blockers:
        typer.echo(f"  {blocker.code}: {blocker.message}")


def _select_status(
    statuses: tuple[MechanismReadiness, ...], mechanism: str
) -> MechanismReadiness:
    for status in statuses:
        if status.mechanism == mechanism:
            return status
    raise typer.BadParameter(f"settlement mechanism {mechanism!r} is not installed")


def _finish_status(status: MechanismReadiness, *, as_json: bool) -> None:
    if as_json:
        typer.echo(
            json.dumps(status.safe_projection(), separators=(",", ":"), sort_keys=True)
        )
    else:
        _render_status(status)
    if not status.ready:
        raise typer.Exit(1)


@settlement_app.command("status")
def settlement_status(
    as_json: bool = typer.Option(False, "--json", help="Emit sanitized JSON."),
) -> None:
    """Observe every installed settlement mechanism without mutation."""
    config, statuses = _readiness()
    if as_json:
        typer.echo(
            json.dumps(
                _status_payload(config, statuses),
                separators=(",", ":"),
                sort_keys=True,
            )
        )
    else:
        for status in statuses:
            _render_status(status)
    if not any(status.ready for status in statuses):
        raise typer.Exit(1)


@alkahest_app.command("check")
def alkahest_check(
    as_json: bool = typer.Option(False, "--json", help="Emit sanitized JSON."),
) -> None:
    """Observe configured Alkahest wallet, chain, and deployment readiness."""
    _config, statuses = _readiness()
    _finish_status(_select_status(statuses, "alkahest.v1"), as_json=as_json)


def _mount_mechanism_command_groups() -> None:
    """Mount registration-owned command groups under their config keys."""
    from market_alkahest import create_alkahest_registration

    for registration in (create_alkahest_registration(command_group=alkahest_app),):
        if registration.command_group is None:
            continue
        settlement_app.add_typer(
            registration.command_group,
            name=registration.config_key,
        )


_mount_mechanism_command_groups()

__all__ = ["settlement_app"]
