"""Schema-invariant buyer config resolution.

Marketplace identity is resolved from public configuration and separately
injected secret material. Generic scalar and wallet values remain here;
domain packages own concrete chain selection and mechanism interpretation.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

import typer
from market_identity import Identity, IdentityScheme, Signer, create_signer

IDENTITY_CREDENTIAL_ENV = "ARKHAI_IDENTITY_CREDENTIAL"


@dataclass(frozen=True, slots=True)
class IdentityConfig:
    """Public buyer identity configuration, separate from signer credentials."""

    principal: Identity


def resolve_identity_config(
    *,
    override_scheme: str | None = None,
    override_identifier: str | None = None,
) -> IdentityConfig:
    """Resolve the buyer's public ``[Identity]`` principal."""

    scheme = resolve_config_value(
        override=override_scheme,
        toml_path="Identity.scheme",
    )
    identifier = resolve_config_value(
        override=override_identifier,
        toml_path="Identity.identifier",
    )
    missing = [
        name
        for name, value in (
            ("Identity.scheme", scheme),
            ("Identity.identifier", identifier),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(
            "Missing required public identity config: " + ", ".join(missing)
        )
    return IdentityConfig(
        principal=Identity(
            scheme=IdentityScheme(scheme),
            identifier=identifier,
        )
    )


def resolve_identity_credential(
    environ: Mapping[str, str] | None = None,
) -> str:
    """Read signer material from the buyer's secret-only environment boundary."""

    credential = (environ if environ is not None else os.environ).get(
        IDENTITY_CREDENTIAL_ENV
    )
    if not credential:
        raise RuntimeError(
            f"Missing required signer credential in {IDENTITY_CREDENTIAL_ENV}"
        )
    return credential


def resolve_buyer_signer(
    config: IdentityConfig,
    credential: bytes | str,
) -> Signer:
    """Build the configured signer and fail closed on principal mismatch."""

    signer = create_signer(config.principal.scheme, credential)
    if signer.identity != config.principal:
        raise ValueError("resolved signer identity does not match configured principal")
    return signer


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
        from market_config.config_loader import get_dotted, load_user_config

        v = get_dotted(load_user_config(), toml_path)
        if v not in (None, ""):
            return str(v)
    return default


def resolve_negotiation_config() -> tuple[object | None, str | None]:
    """Resolve negotiation policy config without flattening TOML lists."""
    from market_config.config_loader import get_dotted, load_user_config

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
        from market_config.config_loader import derive_wallet_address

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
    from market_config.config_loader import get_dotted, load_user_config

    cfg = load_user_config()
    base_url = get_dotted(cfg, "seller.base_url")
    if isinstance(base_url, str) and base_url:
        return base_url
    return f"http://localhost:{default_port}"
