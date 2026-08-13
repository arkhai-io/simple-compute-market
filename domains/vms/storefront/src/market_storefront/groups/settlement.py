"""Seller settlement status and mechanism-owned administration commands."""

from __future__ import annotations

import asyncio
import json
import webbrowser
from collections.abc import Mapping
from typing import Any

import typer
from hosted_settlement_client import (
    ClientConfig,
    HostedSettlementClient,
    SellerOnboarding,
)
from market_hosted_settlement import (
    MarketplaceSignerAdapter,
    adapt_expected_authorities,
)
from market_settlement_runtime import MechanismReadiness, SettlementConfig

settlement_app = typer.Typer(no_args_is_help=True)
stripe_app = typer.Typer(no_args_is_help=True)
alkahest_app = typer.Typer(no_args_is_help=True)


def _settlement_context() -> tuple[Any, SettlementConfig, dict[str, Any]]:
    from market_storefront.settlement_composition import (
        build_storefront_settlement_registry,
    )
    from market_storefront.utils.config import (
        CHAINS,
        get_evm_wallet_address,
        get_evm_wallet_private_key,
        resolve_marketplace_signer,
        settings,
        settlement_config_mapping,
    )

    registry = build_storefront_settlement_registry()
    config = registry.resolve(settlement_config_mapping(), role="seller")
    resources: dict[str, Any] = {}
    stripe = config.mechanism_config("stripe")
    if stripe is not None and stripe.enabled:
        resources["marketplace_signer"] = resolve_marketplace_signer()
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
        typer.echo(json.dumps(status.safe_projection(), separators=(",", ":"), sort_keys=True))
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


@stripe_app.command("status")
def stripe_status(
    as_json: bool = typer.Option(False, "--json", help="Emit sanitized JSON."),
) -> None:
    """Observe hosted authority and seller-account readiness."""
    _config, statuses = _readiness()
    _finish_status(_select_status(statuses, "fiat.stripe.v1"), as_json=as_json)


def _stripe_client(config: SettlementConfig, resources: Mapping[str, Any]) -> HostedSettlementClient:
    stripe = config.mechanism_config("stripe")
    if stripe is None or not stripe.enabled:
        raise typer.BadParameter("Settlement.stripe is not enabled")
    signer = resources.get("marketplace_signer")
    if signer is None or stripe.authority is None or not stripe.base_url:
        raise typer.BadParameter("Settlement.stripe client configuration is incomplete")
    return HostedSettlementClient(
        ClientConfig(
            base_url=stripe.base_url,
            signer=MarketplaceSignerAdapter(signer),
            caller_role="seller",
            authority_id=stripe.authority_id or "",
            environment=stripe.environment or "",
            expected_authorities=adapt_expected_authorities(stripe.authority.as_trusted_set()),
            timeout_seconds=stripe.request_timeout_seconds,
            allow_insecure_loopback=stripe.allow_insecure_loopback,
        )
    )


@stripe_app.command("onboard")
def stripe_onboard(
    no_browser: bool = typer.Option(
        False,
        "--no-browser",
        help="Print the transient Account Link instead of opening a browser.",
    ),
) -> None:
    """Create one owner-authorized transient hosted Account Link."""
    _registry, config, resources = _settlement_context()
    stripe = config.mechanism_config("stripe")
    if stripe is None or not stripe.account_ref:
        raise typer.BadParameter("Settlement.stripe.account_ref is required")
    client = _stripe_client(config, resources)
    try:
        workflow = SellerOnboarding(client, open_url=webbrowser.open)
        result = workflow.onboard(stripe.account_ref, open_browser=not no_browser)
        if no_browser:
            typer.echo(str(result.url))
        else:
            typer.echo("Opened a transient Stripe onboarding link in the browser.")
        typer.echo(f"expires_at_unix={result.expires_at_unix}")
    finally:
        client.close()


@alkahest_app.command("check")
def alkahest_check(
    as_json: bool = typer.Option(False, "--json", help="Emit sanitized JSON."),
) -> None:
    """Observe configured Alkahest wallet, chain, and deployment readiness."""
    _config, statuses = _readiness()
    _finish_status(_select_status(statuses, "alkahest.v1"), as_json=as_json)


settlement_app.add_typer(stripe_app, name="stripe", help="Hosted Stripe seller workflow.")
settlement_app.add_typer(alkahest_app, name="alkahest", help="Alkahest readiness checks.")

__all__ = ["settlement_app"]
