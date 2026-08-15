"""Schema-invariant buyer profile, generic config, and optional wallet resolution."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

import typer
from market_config.config_loader import derive_wallet_address, get_dotted, load_user_config
from market_identity import Identity, Signer

from core_buyer.profile_service import BuyerProfileService
from core_buyer.run_log import read_run_identity


@dataclass(frozen=True, slots=True)
class ResolvedBuyerIdentity:
    """One exact signer plus public immutable profile context."""

    profile_id: uuid.UUID
    principal: Identity
    signer: Signer
    source: Literal["fresh", "recovery"]

    def safe_context(self) -> dict[str, str]:
        return {
            "buyer_profile_id": str(self.profile_id),
            "buyer_principal": (
                f"{self.principal.scheme.value}:{self.principal.identifier}"
            ),
            "signature_version": "2",
            "source": self.source,
        }

    def __repr__(self) -> str:
        return (
            "ResolvedBuyerIdentity("
            f"profile_id={str(self.profile_id)!r}, "
            f"principal={self.principal!r}, source={self.source!r})"
        )


class BuyerProfileResolver:
    """Resolve selected-primary fresh work or exact recorded recovery history."""

    def __init__(self, service: BuyerProfileService | None = None) -> None:
        self.service = service or BuyerProfileService()

    def fresh(self) -> ResolvedBuyerIdentity:
        reject_legacy_buyer_identity_config()
        profile, signer = self.service.resolve_fresh_signer()
        return ResolvedBuyerIdentity(
            profile_id=profile.profile_id,
            principal=signer.identity,
            signer=signer,
            source="fresh",
        )

    def recovery(self, run_id: str) -> ResolvedBuyerIdentity:
        reject_legacy_buyer_identity_config()
        recorded = read_run_identity(
            run_id,
            directory=self.service.run_logs_directory,
        )
        profile, signer = self.service.resolve_recovery_signer(
            profile_id=recorded.profile_id,
            principal=recorded.principal,
        )
        return ResolvedBuyerIdentity(
            profile_id=profile.profile_id,
            principal=recorded.principal,
            signer=signer,
            source="recovery",
        )


def resolve_fresh_buyer_identity() -> ResolvedBuyerIdentity:
    """Resolve the selected active profile exactly once for fresh work."""

    return BuyerProfileResolver().fresh()


def resolve_recovery_buyer_identity(run_id: str) -> ResolvedBuyerIdentity:
    """Resolve the run-recorded profile/principal, ignoring current selection."""

    return BuyerProfileResolver().recovery(run_id)


def reject_legacy_buyer_identity_config() -> None:
    """Reject removed direct marketplace identity fields with an import action."""

    config = load_user_config()
    forbidden = {
        "Identity",
        "identity_credential",
        "buyer_private_key",
        "marketplace_private_key",
        "marketplace_seed",
        "marketplace_mnemonic",
    }
    present = sorted(key for key in forbidden if key in config)
    if present:
        raise RuntimeError(
            "Direct buyer identity configuration is no longer accepted ("
            + ", ".join(present)
            + "); run `market profile import --check`, import explicitly, "
            "then remove the legacy fields."
        )


def resolve_config_value(
    *,
    override: str | None = None,
    toml_path: str | None = None,
    default: str = "",
) -> str:
    """Lookup a scalar config value: CLI override > config.toml > default.

    The TOML file location is whatever ``market_config.config_loader.load_user_config``
    resolves to (XDG default, or the override set by ``--config``).
    """
    if override:
        return override
    if toml_path:
        v = get_dotted(load_user_config(), toml_path)
        if v not in (None, ""):
            return str(v)
    return default


def resolve_negotiation_config() -> tuple[object | None, str | None]:
    """Resolve negotiation policy config without flattening TOML lists."""
    cfg = load_user_config()
    raw_policies = get_dotted(cfg, "negotiation.policies")
    policies: object | None = None
    if isinstance(raw_policies, list):
        policies = [str(p).strip() for p in raw_policies if str(p).strip()]
    elif isinstance(raw_policies, str) and raw_policies.strip():
        policies = [p.strip() for p in raw_policies.split(",") if p.strip()]
    elif hasattr(raw_policies, "items") or isinstance(raw_policies, dict):
        policies = raw_policies

    raw_policy_mode = get_dotted(cfg, "negotiation.policy_mode")
    policy_mode = str(raw_policy_mode).strip() if raw_policy_mode else None
    return policies, policy_mode


def resolve_buyer_wallet(
    *,
    override_addr: str | None = None,
    override_pk: str | None = None,
) -> tuple[str, str]:
    """Resolve ``(wallet.address, wallet.private_key)`` with derivation.

    Both default to the user config when overrides aren't given. If the
    address is empty but the private key is set, the address is derived
    from the key — addresses are a deterministic function of the key, so
    there's no reason to require both in config. If both are set and
    disagree, a warning is emitted but the configured address is kept
    (lets a user delegate signing for an alternate address while
    surfacing the mismatch loudly).
    """
    addr = resolve_config_value(override=override_addr, toml_path="wallet.address")
    pk = resolve_config_value(override=override_pk, toml_path="wallet.private_key")
    if pk:
        derived = derive_wallet_address(pk)
        if derived:
            if not addr:
                addr = derived
            elif addr.lower() != derived.lower():
                typer.secho(
                    f"warning: wallet.address ({addr}) does not match address "
                    f"derived from wallet.private_key ({derived}); using the "
                    f"configured address.",
                    err=True,
                    fg=typer.colors.YELLOW,
                )
    return addr, pk


def resolve_storefront_url(
    agent_url: str | None,
    default_port: int = 8000,
) -> str:
    """Resolve the URL the CLI should dial to reach the agent.

    Precedence: explicit ``agent_url`` > ``seller.base_url`` from
    config.toml > ``http://localhost:{default_port}``.
    """
    if agent_url:
        return agent_url
    cfg = load_user_config()
    base_url = get_dotted(cfg, "seller.base_url")
    if isinstance(base_url, str) and base_url:
        return base_url
    return f"http://localhost:{default_port}"
