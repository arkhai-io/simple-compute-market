"""Seller agent configuration.

Load order for every value is:

    shell env var  >  $XDG_CONFIG_HOME/arkhai/config.toml  >  default

The TOML file is the same one `market` CLI uses; shared keys live under
[wallet], [chain], [registry] and map to the buyer-facing names. Seller-
only overrides live under [seller] and are all optional — a machine
running only the seller agent never needs to set more than the values
that differ from the defaults.

Env vars still win so docker-compose / .env files / ops shells behave
exactly as before. The TOML fill-in happens only when nothing is set.
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .zerotier import BaseUrlResolutionError, resolve_base_url_best_effort

# Load .env file if it exists (before loading any config values)
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# TOML fallback: read once at import, use for any env var that's unset.
# ---------------------------------------------------------------------------

try:
    from service.config_loader import get_dotted, load_user_config  # type: ignore[import-not-found]
    _USER_CFG: dict[str, Any] = load_user_config()
except Exception:  # module missing or path issues — degrade to env-only
    _USER_CFG = {}

    def get_dotted(_doc: dict, _path: str) -> Any | None:  # type: ignore[no-redef]
        return None


def _resolve(
    env_name: str,
    toml_path: str,
    default: Any = None,
    coerce: Callable[[str], Any] | None = None,
) -> Any:
    """Env var → TOML → default. Empty strings count as unset."""
    raw = os.environ.get(env_name)
    if raw is not None and raw != "":
        try:
            return coerce(raw) if coerce else raw
        except Exception:
            return default
    val = get_dotted(_USER_CFG, toml_path)
    if val is not None and val != "":
        return val
    return default


def _resolve_int(env_name: str, toml_path: str, default: int) -> int:
    v = _resolve(env_name, toml_path, default, coerce=int)
    try:
        return int(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _resolve_bool(env_name: str, toml_path: str, default: bool) -> bool:
    v = _resolve(env_name, toml_path, default)
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes")
    return bool(v)


# ---------------------------------------------------------------------------


DEFAULT_AGENT_ID = "root_agent"


def get_agent_name() -> str:
    """Display name for agent card / on-chain metadata.

    Prefers env AGENT_NAME, then [seller] agent_name in TOML, then
    falls back to agent_id. Can contain spaces / hyphens, unlike
    agent_id which must be a valid Python identifier.
    """
    name = _resolve("AGENT_NAME", "seller.agent_name", None)
    if name:
        return str(name)
    return get_agent_id()


def get_agent_id(env_value: str | None = None) -> str:
    """Validated agent ID. Must be a Python identifier.

    Source order:
        explicit `env_value` > AGENT_ID env > [seller].agent_id TOML > DEFAULT_AGENT_ID
    """
    if env_value is not None:
        agent_id = env_value
    else:
        agent_id = _resolve("AGENT_ID", "seller.agent_id", None)

    if not agent_id:
        return DEFAULT_AGENT_ID

    if not str(agent_id).isidentifier():
        raise ValueError(
            f"AGENT_ID '{agent_id}' is not a valid identifier. "
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
    chain_name: str
    chain_rpc_url: str
    agent_priv_key: str
    agent_wallet_address: str
    alkahest_address_config_path: str | None
    agent_db_path: str
    event_validation_mode: str
    enable_redis_ingest: bool
    redis_url: str
    redis_channels: str
    enable_event_queue: bool
    log_file_path: str | None
    log_level: str
    token_registry_path: str
    ssh_public_key: str
    # Indexer/Registry settings
    indexer_url: str
    identity_registry_address: str | None
    onchain_agent_id: str | None
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


DEFAULT_TOKEN_REGISTRY_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "token_registry_docker_compose.json"
)
_DEFAULT_SSH_PUBLIC_KEY = (
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDemoPublicKeyForComputeAccess demo@example"
)


def load_config() -> Config:
    agent_id = get_agent_id()
    if agent_id == DEFAULT_AGENT_ID and not os.getenv("AGENT_ID"):
        import warnings
        warnings.warn(
            f"AGENT_ID environment variable not set. Using default '{DEFAULT_AGENT_ID}'. "
            f"Please set AGENT_ID to a valid identifier (letters, digits, underscores only).",
            UserWarning,
        )
    agent_name = get_agent_name()

    # BASE_URL_OVERRIDE handling with optional ZeroTier placeholder.
    base_url_override_raw = str(
        _resolve("BASE_URL_OVERRIDE", "seller.base_url", "http://localhost:8000")
    )
    zerotier_network = _resolve("ZEROTIER_NETWORK", "seller.zerotier_network", None)

    try:
        base_url_override_resolved = resolve_base_url_best_effort(
            base_url_override_raw,
            zerotier_network,
        )
        if base_url_override_resolved != base_url_override_raw:
            logger.info(
                "[CONFIG] BASE_URL_OVERRIDE resolved to %s (network=%s)",
                base_url_override_resolved,
                zerotier_network,
            )
    except BaseUrlResolutionError as exc:
        logger.warning(
            "[CONFIG] BASE_URL_OVERRIDE is invalid (%s); using raw value",
            exc,
        )
        base_url_override_resolved = base_url_override_raw

    return Config(
        agent_id=agent_id,
        agent_name=agent_name,
        mcp_server_url=str(_resolve(
            "MCP_SERVER_URL", "seller.mcp_server_url", "http://localhost:8080/mcp",
        )),
        base_url_override_raw=base_url_override_raw,
        base_url_override=base_url_override_resolved,
        port=_resolve_int("PORT", "seller.port", 8000),

        # Shared with buyer via [chain].
        chain_name=str(_resolve("CHAIN_NAME", "chain.name", "ethereum_sepolia")),
        chain_rpc_url=_resolve("CHAIN_RPC_URL", "chain.rpc_url", None),
        alkahest_address_config_path=_resolve(
            "ALKAHEST_ADDRESS_CONFIG_PATH", "chain.alkahest_address_config_path", None,
        ),

        # Shared with buyer via [wallet].
        agent_priv_key=_resolve("AGENT_PRIV_KEY", "wallet.private_key", None),
        agent_wallet_address=_resolve("AGENT_WALLET_ADDRESS", "wallet.address", None),
        ssh_public_key=str(_resolve(
            "SSH_PUBLIC_KEY", "wallet.ssh_public_key", _DEFAULT_SSH_PUBLIC_KEY,
        )),

        # Shared with buyer via [registry].
        indexer_url=str(_resolve(
            "INDEXER_URL",
            "registry.url",
            os.getenv("REGISTRY_URL", "http://localhost:8080"),
        )),
        identity_registry_address=_resolve(
            "IDENTITY_REGISTRY_ADDRESS", "registry.identity_registry_address", None,
        ),

        # Seller-only bookkeeping.
        agent_db_path=str(_resolve("AGENT_DB_PATH", "seller.db_path", "/tmp/agent.db")),
        event_validation_mode=str(_resolve(
            "EVENT_VALIDATION_MODE", "seller.event_validation_mode", "warn",
        )),
        enable_event_queue=_resolve_bool(
            "ENABLE_EVENT_QUEUE", "seller.enable_event_queue", False,
        ),
        log_file_path=_resolve("LOG_FILE_PATH", "seller.log_file_path", None),
        log_level=str(_resolve("LOG_LEVEL", "seller.log_level", "INFO")),
        token_registry_path=str(_resolve(
            "TOKEN_REGISTRY_PATH",
            "seller.token_registry_path",
            str(DEFAULT_TOKEN_REGISTRY_PATH),
        )),

        onchain_agent_id=_resolve("ONCHAIN_AGENT_ID", "seller.onchain_agent_id", None),

        # Registry discovery settings (seller-side).
        enable_registry_discovery=_resolve_bool(
            "ENABLE_REGISTRY_DISCOVERY", "seller.enable_registry_discovery", True,
        ),
        registry_order_timeout=_resolve_int(
            "REGISTRY_ORDER_TIMEOUT", "seller.registry_order_timeout", 30,
        ),
        max_discovery_agents=_resolve_int(
            "MAX_DISCOVERY_AGENTS", "seller.max_discovery_agents", 10,
        ),
        enable_order_retry=_resolve_bool(
            "ENABLE_ORDER_RETRY", "seller.enable_order_retry", True,
        ),
        order_retry_interval=_resolve_int(
            "ORDER_RETRY_INTERVAL", "seller.order_retry_interval", 300,
        ),

        # Provisioning — sub-table [seller.provisioning].
        provisioning_service_url=str(_resolve(
            "PROVISIONING_SERVICE_URL",
            "seller.provisioning.service_url",
            "http://localhost:8085",
        )),
        provisioning_timeout=_resolve_int(
            "PROVISIONING_TIMEOUT", "seller.provisioning.timeout", 3600,
        ),
        provisioning_poll_interval=_resolve_int(
            "PROVISIONING_POLL_INTERVAL", "seller.provisioning.poll_interval", 15,
        ),
        frp_server_addr=(
            _resolve("FRP_SERVER_ADDR", "seller.provisioning.frp_server_addr", None)
            or os.getenv("frp_server_addr")
        ),
        frp_domain=(
            _resolve("FRP_DOMAIN", "seller.provisioning.frp_domain", None)
            or os.getenv("frp_domain")
        ),
        frp_dashboard_password=(
            _resolve(
                "FRP_DASHBOARD_PASSWORD",
                "seller.provisioning.frp_dashboard_password",
                None,
            )
            or os.getenv("frp_dashboard_password")
        ),

        # Resource poller.
        resource_check_interval=_resolve_int(
            "RESOURCE_CHECK_INTERVAL", "seller.resource_check_interval", 300,
        ),
        resource_lease_grace_seconds=_resolve_int(
            "RESOURCE_LEASE_GRACE_SECONDS", "seller.resource_lease_grace_seconds", 1800,
        ),

        # Negotiation watchdog.
        negotiation_timeout_seconds=_resolve_int(
            "NEGOTIATION_TIMEOUT_SECONDS", "seller.negotiation_timeout_seconds", 1800,
        ),
        negotiation_watchdog_interval=_resolve_int(
            "NEGOTIATION_WATCHDOG_INTERVAL", "seller.negotiation_watchdog_interval", 60,
        ),
        default_vm_host=str(_resolve(
            "DEFAULT_VM_HOST", "seller.default_vm_host", "ww1",
        )),

        # Redis — sub-table [seller.redis].
        enable_redis_ingest=_resolve_bool(
            "ENABLE_REDIS_INGEST", "seller.redis.enable", False,
        ),
        redis_url=str(_resolve(
            "REDIS_URL", "seller.redis.url", "redis://localhost:6379",
        )),
        redis_channels=str(_resolve(
            "REDIS_CHANNELS", "seller.redis.channels", "events:*",
        )),

        # Negotiation policy. Empty string (the default) means "use the
        # registered default", which today is the trained RL strategy
        # ("rl"). Set explicitly to "bisection" to opt out.
        negotiation_policy_mode=str(_resolve(
            "NEGOTIATION_POLICY_MODE", "seller.negotiation.policy_mode", "",
        )).lower(),
        arkhai_negotiator_seller_model_path=str(_resolve(
            "ARKHAI_NEGOTIATOR_SELLER_MODEL_PATH",
            "seller.negotiation.seller_model_path",
            "domain/compute/agent/app/policy/models/arkhai_negotiator_seller.pt",
        )),
        arkhai_negotiator_buyer_model_path=str(_resolve(
            "ARKHAI_NEGOTIATOR_BUYER_MODEL_PATH",
            "seller.negotiation.buyer_model_path",
            "domain/compute/agent/app/policy/models/arkhai_negotiator_buyer.pt",
        )),
    )


# Module-level singleton for convenience.
CONFIG = load_config()
