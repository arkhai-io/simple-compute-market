"""Seller agent configuration.

Loaded from `$XDG_CONFIG_HOME/arkhai/config.toml`. Shared keys live
under [wallet], [chain], [registry] (matching the buyer-facing names);
seller-only knobs live under [seller] and are all optional. The
storefront CLI (`market-storefront`) and the buyer CLI (`market`) read
the same TOML file.

Config is the single source of truth — nothing here reads env vars.
Callers that today still consume env vars (CLI fallbacks, the service
client library, the watchdog ZeroTier setup) will migrate to receive a
typed config in their constructor or call signature; until that's done
they call into the legacy env reads themselves, not through this
module.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from web3 import Web3
from web3.providers import HTTPProvider
from service.clients.erc8004.blockchain import (  # type: ignore[import-not-found]
    build_erc8004_canonical_id,
    rpc_url_for_http_provider,
)

from .zerotier import BaseUrlResolutionError, resolve_base_url_best_effort

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# TOML loader (single read at import; tests monkeypatch _USER_CFG directly).
# ---------------------------------------------------------------------------

try:
    from service.config_loader import get_dotted, load_user_config  # type: ignore[import-not-found]
    _USER_CFG: dict[str, Any] = load_user_config()
except Exception:  # module missing or path issues — degrade to defaults-only
    _USER_CFG = {}

    def get_dotted(_doc: dict, _path: str) -> Any | None:  # type: ignore[no-redef]
        return None


def _resolve(
    toml_path: str,
    default: Any = None,
    coerce: Callable[[Any], Any] | None = None,
) -> Any:
    """TOML → default. Empty strings count as unset."""
    val = get_dotted(_USER_CFG, toml_path)
    if val is None or val == "":
        return default
    if coerce is None:
        return val
    try:
        return coerce(val)
    except Exception:
        return default


def _resolve_int(toml_path: str, default: int) -> int:
    v = _resolve(toml_path, default, coerce=int)
    try:
        return int(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _resolve_bool(toml_path: str, default: bool) -> bool:
    v = _resolve(toml_path, default)
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes")
    return bool(v)


# ---------------------------------------------------------------------------


DEFAULT_AGENT_ID = "root_agent"


def get_agent_name() -> str:
    """Display name for agent card / on-chain metadata.

    [seller].agent_name in TOML; falls back to agent_id. Can contain
    spaces / hyphens, unlike agent_id which must be a valid Python
    identifier.
    """
    name = _resolve("seller.agent_name", None)
    if name:
        return str(name)
    return get_agent_id()


def get_agent_id(explicit_value: str | None = None) -> str:
    """Validated agent ID. Must be a Python identifier.

    Source order:
        explicit `explicit_value` arg > [seller].agent_id TOML > DEFAULT_AGENT_ID
    """
    if explicit_value is not None:
        agent_id = explicit_value
    else:
        agent_id = _resolve("seller.agent_id", None)

    if not agent_id:
        return DEFAULT_AGENT_ID

    if not str(agent_id).isidentifier():
        raise ValueError(
            f"agent_id '{agent_id}' is not a valid identifier. "
            f"Must start with a letter or underscore, and only contain letters, digits, and underscores. "
            f"Examples: 'my_agent', 'agent_123', '_internal_agent'"
        )
    return str(agent_id)


@dataclass(frozen=True)
class Config:
    agent_id: str
    agent_name: str
    mcp_server_url: str
    base_url_override_raw: str
    base_url_override: str
    port: int
    # root_path: gateway path prefix for this agent (e.g. "/storefront").
    # Used by FastAPI to generate correct OpenAPI schema URLs when behind a
    # reverse proxy. Set via ROOT_PATH env var from the ops repo values overlay.
    root_path: str
    chain_name: str
    chain_rpc_url: str
    agent_priv_key: str
    agent_wallet_address: str
    alkahest_address_config_path: str | None
    agent_db_path: str
    log_file_path: str | None
    log_level: str
    ssh_public_key: str
    zerotier_network: str | None
    # Chain identity
    chain_id: int
    # Indexer/Registry settings — list because "registry" is a role
    # rather than a canonical service. Reads fan in across every URL
    # (union); writes fan out (best-effort). One entry is the common
    # case; private-registry deployments append their own URL.
    indexer_urls: list[str]
    # Per-call deadline applied to every fan-in request the
    # MultiRegistryClient sends. A registry that doesn't respond in
    # this window is skipped (with a log line) so the merge proceeds
    # with whoever beat the deadline. This is the budget knob — there
    # is no separate circuit-breaker.
    discovery_timeout: float
    # Optional per-registry bearer tokens, keyed by URL. Private
    # registries gate access behind an API key; public ones omit
    # their entry. The MultiRegistryClient passes each URL's token
    # (or ``None``) into the underlying RegistryClient.
    indexer_auth: dict[str, str]
    identity_registry_address: str | None
    onchain_agent_id: str | None
    # Registration behaviour
    auto_register: bool
    # Registry discovery settings
    enable_registry_discovery: bool
    registry_order_timeout: int
    max_discovery_agents: int
    # Order retry settings
    enable_order_retry: bool
    order_retry_interval: int
    # Provisioning settings
    provisioning_service_url: str
    provisioning_timeout: int
    provisioning_poll_interval: int
    # Preflight: how long to wait for /health to come up at startup, and
    # whether to crash the process on failure. fail_on_unreachable=true is
    # the prod-correct default (orchestrator restarts surface the misconfig);
    # set false in dev/CI when the service comes up later in the same pod.
    provisioning_preflight_timeout: int
    provisioning_fail_on_unreachable: bool
    frp_server_addr: str | None
    frp_domain: str | None
    frp_dashboard_password: str | None
    resource_check_interval: int
    resource_lease_grace_seconds: int
    # Negotiation watchdog
    negotiation_timeout_seconds: int
    negotiation_watchdog_interval: int
    default_vm_host: str
    # Negotiation policy settings
    negotiation_policy_mode: str
    arkhai_negotiator_seller_model_path: str
    arkhai_negotiator_buyer_model_path: str
    # Extra directories to scan for file-based policies, in addition to
    # $XDG_CONFIG_HOME/arkhai/policies/. Each immediate subdirectory is
    # treated as a policy named after the folder, loaded via its
    # ``policy.py`` exposing ``factory(cfg) -> NegotiationStrategy``.
    extra_policy_paths: list[str]
    # Pricing defaults — fallback for resources whose CSV row leaves
    # min_price / token blank. None means "no default; rows must set it
    # or they're skipped at publish time."
    default_min_price: str | None
    # 0x ERC-20 contract address used when a CSV row has no token column.
    # Also the demand-side token used by the resource-imbalance policy's
    # synthesized MAKE_OFFER (where there's no CSV row at all). None means
    # no default; per-row token is required.
    default_token_address: str | None
    # Default max-duration ceiling (seconds) advertised on listings whose
    # CSV row leaves max_duration_seconds blank. None = unlimited.
    default_max_duration_seconds: int | None
    # When True, resources without a configured per-row min_price (and no
    # default_min_price either) are published anyway with demand.amount=0
    # — a "price-less listing" buyers can negotiate against by proposing
    # their own price. The seller's negotiation strategy falls back to
    # default_min_price for the floor on these listings; if that's also
    # unset, the strategy exits. Default False preserves the skip-on-missing
    # behavior.
    publish_priceless: bool
    # Resource auto-seeding — two delivery mechanisms, checked in priority order:
    #   1. resources_csv_inline: raw CSV content injected via config (Helm Secret).
    #      Used when the CSV is operator-supplied and must not be baked into the image.
    #   2. default_resources_csv_path: path to a CSV file on disk (compose / local dev).
    #      Skipped when resources_csv_inline is set.
    # Seeding is skipped entirely when the resources table is already populated.
    # Use POST /api/v1/admin/portfolio/resources/import to force a clobber.
    resources_csv_inline: str | None
    default_resources_csv_path: str | None
    # Admin API key — protects /admin/* routes and admin-only resource actions.
    # None means unprotected (local dev).  Set via [seller].admin_api_key in
    # config.toml, or injected via the Helm provisioning-secrets profile.
    admin_api_key: str | None


_DEFAULT_SSH_PUBLIC_KEY = (
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDemoPublicKeyForComputeAccess demo@example"
)


def _resolve_indexer_auth(resolve) -> dict[str, str]:
    """Pull per-registry bearer tokens out of TOML.

    Shape:
      [registry.auth]
      "http://private:8080" = "secret123"

    Returns ``{url: token}``; URLs without an entry get no
    Authorization header at the underlying RegistryClient. An empty
    or missing ``[registry.auth]`` table yields ``{}``.
    """
    raw = resolve("registry.auth", None)
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for url, token in raw.items():
        if isinstance(url, str) and isinstance(token, str) and url.strip() and token.strip():
            out[url.strip()] = token.strip()
    return out


def _resolve_extra_policy_paths(resolve) -> list[str]:
    """Pull extra file-policy search directories out of TOML.

    Accepts either a TOML array (``extra_policy_paths = [".../a", ".../b"]``)
    or a single string (``extra_policy_paths = "..."``). Empty / unset →
    empty list. Paths are returned verbatim; existence is checked at
    load time in the strategy loader.
    """
    raw = resolve("seller.negotiation.extra_policy_paths", None)
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw.strip()] if raw.strip() else []
    if isinstance(raw, list):
        return [str(p).strip() for p in raw if str(p).strip()]
    return []


def _resolve_indexer_urls(resolve) -> list[str]:
    """Pull the configured registry URL(s) out of TOML.

    Only ``[registry] urls = [...]`` is recognised — single-URL
    deployments express that as a one-element list. Falls back to a
    one-URL localhost default when ``urls`` is unset.
    """
    urls = resolve("registry.urls", None)
    if isinstance(urls, list) and urls:
        cleaned = [str(u).strip() for u in urls if str(u).strip()]
        if cleaned:
            return cleaned
    return ["http://localhost:8080"]


def load_config() -> Config:
    agent_id = get_agent_id()
    if agent_id == DEFAULT_AGENT_ID and not _resolve("seller.agent_id", None):
        import warnings
        warnings.warn(
            f"agent_id not set in config.toml. Using default '{DEFAULT_AGENT_ID}'. "
            f"Set [seller].agent_id to a valid identifier (letters, digits, underscores only).",
            UserWarning,
        )
    agent_name = get_agent_name()

    # BASE_URL_OVERRIDE handling with optional ZeroTier placeholder.
    base_url_override_raw = str(_resolve("seller.base_url", "http://localhost:8000"))
    zerotier_network = _resolve("seller.zerotier_network", None)

    try:
        base_url_override_resolved = resolve_base_url_best_effort(
            base_url_override_raw,
            zerotier_network,
        )
        if base_url_override_resolved != base_url_override_raw:
            logger.info(
                "[CONFIG] base_url resolved to %s (network=%s)",
                base_url_override_resolved,
                zerotier_network,
            )
    except BaseUrlResolutionError as exc:
        logger.warning(
            "[CONFIG] base_url is invalid (%s); using raw value",
            exc,
        )
        base_url_override_resolved = base_url_override_raw

    return Config(
        agent_id=agent_id,
        agent_name=agent_name,
        mcp_server_url=str(_resolve(
            "seller.mcp_server_url", "http://localhost:8080/mcp",
        )),
        base_url_override_raw=base_url_override_raw,
        base_url_override=base_url_override_resolved,
        port=_resolve_int("seller.port", 8000),
        root_path=_resolve("gateway.root_path", ""),

        # Shared with buyer via [chain].
        chain_name=str(_resolve("chain.name", "ethereum_sepolia")),
        chain_rpc_url=_resolve("chain.rpc_url", None),
        alkahest_address_config_path=_resolve(
            "chain.alkahest_address_config_path", None,
        ),

        # Shared with buyer via [wallet].
        agent_priv_key=_resolve("wallet.private_key", None),
        agent_wallet_address=_resolve("wallet.address", None),
        ssh_public_key=str(_resolve(
            "wallet.ssh_public_key", _DEFAULT_SSH_PUBLIC_KEY,
        )),

        zerotier_network=_resolve("seller.zerotier_network", None),

        # Shared with buyer via [registry].
        indexer_urls=_resolve_indexer_urls(_resolve),
        discovery_timeout=float(_resolve("registry.discovery_timeout", 5.0) or 5.0),
        indexer_auth=_resolve_indexer_auth(_resolve),
        identity_registry_address=_resolve(
            "registry.identity_registry_address", None,
        ),

        # Chain identity (explicit in TOML; 0 means unset — callers that need
        # a live value should use _resolve_chain_id() which falls back to RPC).
        chain_id=_resolve_int("chain.chain_id", 0),

        # Seller-only bookkeeping.
        agent_db_path=str(_resolve("seller.db_path", "/tmp/agent.db")),
        log_file_path=_resolve("seller.log_file_path", None),
        log_level=str(_resolve("seller.log_level", "INFO")),

        onchain_agent_id=_resolve("seller.onchain_agent_id", None),

        # Registration behaviour.
        # auto_register=True  → if onchain_agent_id is absent, register at
        #                       startup and hold the resolved ID in memory.
        # auto_register=False → if onchain_agent_id is absent, crash loudly.
        #                       Use this when an agent has already been
        #                       registered and a missing ID should be caught
        #                       immediately rather than silently creating a
        #                       new on-chain identity.
        auto_register=_resolve_bool("seller.auto_register", True),

        # Registry discovery settings (seller-side).
        enable_registry_discovery=_resolve_bool(
            "seller.enable_registry_discovery", True,
        ),
        registry_order_timeout=_resolve_int(
            "seller.registry_order_timeout", 30,
        ),
        max_discovery_agents=_resolve_int(
            "seller.max_discovery_agents", 10,
        ),
        enable_order_retry=_resolve_bool(
            "seller.enable_order_retry", True,
        ),
        order_retry_interval=_resolve_int(
            "seller.order_retry_interval", 300,
        ),

        # Provisioning — sub-table [seller.provisioning].
        provisioning_service_url=str(_resolve(
            "seller.provisioning.service_url", "http://localhost:8085",
        )),
        provisioning_timeout=_resolve_int(
            "seller.provisioning.timeout", 3600,
        ),
        provisioning_poll_interval=_resolve_int(
            "seller.provisioning.poll_interval", 15,
        ),
        provisioning_preflight_timeout=_resolve_int(
            "seller.provisioning.preflight_timeout", 30,
        ),
        provisioning_fail_on_unreachable=_resolve_bool(
            "seller.provisioning.fail_on_unreachable", True,
        ),
        frp_server_addr=_resolve("seller.provisioning.frp_server_addr", None),
        frp_domain=_resolve("seller.provisioning.frp_domain", None),
        frp_dashboard_password=_resolve(
            "seller.provisioning.frp_dashboard_password", None,
        ),

        # Resource poller.
        resource_check_interval=_resolve_int(
            "seller.resource_check_interval", 300,
        ),
        resource_lease_grace_seconds=_resolve_int(
            "seller.resource_lease_grace_seconds", 1800,
        ),

        # Negotiation watchdog.
        negotiation_timeout_seconds=_resolve_int(
            "seller.negotiation_timeout_seconds", 1800,
        ),
        negotiation_watchdog_interval=_resolve_int(
            "seller.negotiation_watchdog_interval", 60,
        ),
        default_vm_host=str(_resolve("seller.default_vm_host", "ww1")),

        # Negotiation strategy. "bisection" is the safe default — no ML
        # dependencies required. Set to "rl" to use the trained Arkhai
        # pufferlib checkpoint (requires torch; exits every round if unavailable).
        negotiation_policy_mode=str(_resolve(
            "seller.negotiation.policy_mode", "bisection",
        )).lower(),
        arkhai_negotiator_seller_model_path=str(_resolve(
            "seller.negotiation.seller_model_path",
            "domain/compute/agent/app/policy/models/arkhai_negotiator_seller.pt",
        )),
        arkhai_negotiator_buyer_model_path=str(_resolve(
            "seller.negotiation.buyer_model_path",
            "domain/compute/agent/app/policy/models/arkhai_negotiator_buyer.pt",
        )),
        extra_policy_paths=_resolve_extra_policy_paths(_resolve),
        admin_api_key=_resolve("seller.admin_api_key", None) or None,

        # Pricing defaults — applied to resources whose CSV row leaves
        # min_price / token / max_duration_seconds blank.
        default_min_price=_resolve("seller.pricing.default_min_price", None) or None,
        default_token_address=_resolve("seller.pricing.default_token_address", None) or None,
        default_max_duration_seconds=_resolve_int(
            "seller.pricing.default_max_duration_seconds", 0
        ) or None,
        publish_priceless=_resolve_bool(
            "seller.pricing.publish_priceless", False,
        ),

        # Resource auto-seeding: inline content takes priority over file path.
        resources_csv_inline=_resolve("seller.resources_csv_inline", None) or None,
        default_resources_csv_path=_resolve("seller.resources_csv_path", None) or None,
    )


# Module-level singleton for convenience.
CONFIG = load_config()


def _resolve_chain_id() -> int:
    """Return the effective EVM chain ID.

    Resolution order:
      1. ``CONFIG.chain_id`` — pinned in ``[chain].chain_id`` in config.toml.
         This is the fast path and the expected state for all deployments.
      2. Live ``eth_chainId`` RPC call against ``CONFIG.chain_rpc_url`` —
         fallback when chain_id is 0 (unset in config).

    Raises ``RuntimeError`` when chain_id is 0 and the RPC call fails, so
    that callers that depend on a correct chain ID surface the misconfiguration
    loudly rather than silently using a wrong value.

    Not cached — the value is stable for the process lifetime once the RPC
    node is reachable, but caching here would complicate test isolation.
    Callers that invoke this frequently should cache the result themselves.
    """
    if CONFIG.chain_id:
        return CONFIG.chain_id
    if not CONFIG.chain_rpc_url:
        raise RuntimeError(
            "chain.chain_id is not set in config.toml and chain.rpc_url is "
            "absent — cannot determine chain ID. Add chain_id = <N> under "
            "[chain] in config.toml."
        )
    try:
        w3 = Web3(HTTPProvider(
            rpc_url_for_http_provider(CONFIG.chain_rpc_url),
            request_kwargs={"timeout": 5},
        ))
        return w3.eth.chain_id
    except Exception as exc:
        raise RuntimeError(
            f"chain.chain_id is not set in config.toml and the RPC fallback "
            f"failed ({exc}). Add chain_id = <N> under [chain] in config.toml."
        ) from exc
