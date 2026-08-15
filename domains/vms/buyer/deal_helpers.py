"""VM-owned deal recovery and concrete chain settlement resolution.

Core recovers mechanism-opaque run-log payloads. This adapter decodes
Alkahest proposal fields and settlement plans, resolves VM SSH credentials,
and materializes the selected chain and token metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import typer
from core_buyer.deal_helpers import (  # noqa: F401 — re-exports
    DealContext,
    NegotiationResumePoint,
    accepted_settlement_mechanism,
    is_negotiation_complete,
    open_run_log,
)
from core_buyer.deal_helpers import (
    load_deal_context as _core_load_deal_context,
)
from core_buyer.deal_helpers import (
    load_negotiation_resume_point as _core_load_negotiation_resume_point,
)

if TYPE_CHECKING:
    from market_config.config_loader import ChainConfig


def _publisher_trust_refresh(signer):
    from core_buyer.orchestrator import fetch_listing_dict
    from market_identity import TrustedIdentitySet

    from .common import (
        resolve_discovery_timeout,
        resolve_indexer_urls,
        resolve_registry_api_keys,
        resolve_registry_authorities,
    )

    urls = resolve_indexer_urls()
    authorities = resolve_registry_authorities(urls)
    api_keys = resolve_registry_api_keys()
    timeout = resolve_discovery_timeout()

    def refresh(
        listing_id: str,
        publisher_id: str,
        registry_url: str,
        authority: str,
    ):
        normalized_url = registry_url.rstrip("/")
        configured = authorities.get(normalized_url)
        if configured is None or configured.authority != authority:
            raise typer.BadParameter(
                "Recorded source registry is not bound by current configuration"
            )
        listing = fetch_listing_dict(
            normalized_url,
            listing_id,
            timeout=timeout,
            signer=signer,
            registry_authority=configured,
            api_key=api_keys.get(normalized_url),
        )
        if listing is None:
            raise typer.BadParameter("Recorded listing is no longer available")
        current_publisher_id = str(listing.get("publisher_id") or "").strip()
        if current_publisher_id != publisher_id:
            raise typer.BadParameter(
                "Signed listing refresh changed the recorded publisher"
            )
        try:
            return TrustedIdentitySet.model_validate(
                listing.get("publisher_principals")
            )
        except (TypeError, ValueError) as exc:
            raise typer.BadParameter(
                "Signed listing refresh carries malformed publisher principals"
            ) from exc

    return refresh


def load_deal_context(run_id: str, *, signer):
    deal = _core_load_deal_context(
        run_id,
        signer=signer,
        refresh_publisher_principals=_publisher_trust_refresh(signer),
    )
    if deal.accepted_escrow_proposal is not None:
        from market_alkahest.schemas import (
            accepted_recipient_address,
            accepted_token_address,
        )

        recipient = accepted_recipient_address(deal.accepted_escrow_proposal)
        if recipient:
            deal.seller_wallet_address = recipient
        token = accepted_token_address(deal.accepted_escrow_proposal)
        if token:
            deal.token_contract = token
    if deal.settlement_plan is not None and not deal.accepted_escrow_terms:
        from market_alkahest.plans import escrow_terms_from_settlement_plan

        deal.accepted_escrow_terms = [
            terms.model_dump()
            for terms in escrow_terms_from_settlement_plan(deal.settlement_plan)
        ]
    return deal


def make_publisher_trust_resolver(
    *,
    run_id: str,
    listing_id: str,
    publisher_id: str,
    source_registry_url: str,
    source_registry_authority: str,
    current,
    signer,
):
    from .run_log import RunLog, read_run_identity

    refresh = _publisher_trust_refresh(signer)

    def resolve():
        nonlocal current
        replacement = refresh(
            listing_id,
            publisher_id,
            source_registry_url,
            source_registry_authority,
        )
        if replacement != current:
            current = replacement
            RunLog.open(
                run_id,
                signer=signer,
                profile_id=read_run_identity(run_id).profile_id,
            ).event(
                "publisher_trust_refreshed",
                listing_id=listing_id,
                publisher_id=publisher_id,
                publisher_principals=current.model_dump(mode="json"),
                source_registry_url=source_registry_url,
                source_registry_authority=source_registry_authority,
            )
        return current

    return resolve


def make_deal_publisher_trust_resolver(run_id: str, deal, signer):
    return make_publisher_trust_resolver(
        run_id=run_id,
        listing_id=deal.listing_id,
        publisher_id=deal.publisher_id,
        source_registry_url=deal.source_registry_url,
        source_registry_authority=deal.source_registry_authority,
        current=deal.publisher_principals,
        signer=signer,
    )


def load_negotiation_resume_point(run_id: str, *, signer):
    return _core_load_negotiation_resume_point(
        run_id,
        signer=signer,
        refresh_publisher_principals=_publisher_trust_refresh(signer),
    )


@dataclass
class ChainSettings:
    """Resolved VM settlement credentials and Alkahest chain metadata."""

    buyer_address: str
    buyer_private_key: str
    ssh_public_key: str
    rpc_url: str
    chain_name: str
    alkahest_addr_config: str | None
    token_contract: str
    token_decimals: int


def resolve_chain_settings(
    *,
    buyer_address: str | None,
    buyer_private_key: str | None,
    ssh_public_key: str | None,
    chain: ChainConfig,
    token_contract: str | None,
    token_decimals: int | None,
    require_ssh: bool = True,
) -> ChainSettings:
    """Resolve wallet, SSH key, token metadata, and chain settings in-domain."""
    from .common import resolve_ssh_public_key

    ssh = resolve_ssh_public_key(override=ssh_public_key)
    if require_ssh and not ssh:
        typer.secho("Missing required config:", err=True, fg=typer.colors.RED)
        typer.secho(
            "  • ssh_public_key — set with: market config set provisioning.ssh_public_key <value>",
            err=True,
            fg=typer.colors.RED,
        )
        typer.secho(
            "Run `market config init-user` to scaffold a config file with the full set of keys.",
            err=True,
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(2)

    from .common import resolve_buyer_wallet

    addr, pk = resolve_buyer_wallet(
        override_addr=buyer_address,
        override_pk=buyer_private_key,
    )
    if not pk:
        typer.secho("Missing required config:", err=True, fg=typer.colors.RED)
        typer.secho(
            "  • buyer_priv_key — set with: market config set wallet.private_key <value>",
            err=True,
            fg=typer.colors.RED,
        )
        typer.secho(
            "Run `market config init-user` to scaffold a config file with the full set of keys.",
            err=True,
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(2)

    if not token_contract:
        typer.secho(
            "No --token-contract given and no token recorded on the run-log. "
            "Pass --token-contract or resume from a run-log that captured the "
            "negotiated token (`market buy` / `market negotiate` log it as "
            "part of round 0).",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(2)

    decimals = token_decimals
    if decimals is None:
        from market_alkahest.token import TokenResolutionError, resolve_token

        try:
            meta = resolve_token(
                token_contract,
                rpc_url=chain.rpc_url,
                chain_id=chain.chain_id,
            )
            decimals = meta.decimals
        except (TokenResolutionError, RuntimeError) as exc:
            typer.secho(
                f"Could not resolve token {token_contract} on chain {chain.name!r} "
                f"— pass --token-decimals or check the chain's rpc_url. ({exc})",
                err=True,
                fg=typer.colors.RED,
            )
            raise typer.Exit(2) from exc

    return ChainSettings(
        buyer_address=addr,
        buyer_private_key=pk,
        ssh_public_key=ssh,
        rpc_url=chain.rpc_url,
        chain_name=chain.name,
        alkahest_addr_config=chain.alkahest_address_config_path,
        token_contract=token_contract,
        token_decimals=decimals,
    )
