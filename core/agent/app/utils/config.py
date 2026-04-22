import logging
import os
from dataclasses import dataclass
from pathlib import Path

from .zerotier import BaseUrlResolutionError, resolve_base_url_best_effort

# Load .env file if it exists (before loading any config values)
try:
    from dotenv import load_dotenv
    # Load .env from the project root (parent of app directory)
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    # python-dotenv not available, skip
    pass


logger = logging.getLogger(__name__)


def _get_bool_env(var_name: str, default: bool = False) -> bool:
    value = os.getenv(var_name)
    if value is None:
        return default
    return value.lower() in ("true", "1", "yes")


def _get_int_env(var_name: str, default: int) -> int:
    value = os.getenv(var_name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


# Default agent ID used when AGENT_ID env var is not set
DEFAULT_AGENT_ID = "root_agent"


def get_agent_name() -> str:
    """
    Get agent display name from AGENT_NAME env var, falling back to AGENT_ID if not set.
    
    AGENT_NAME is the user-friendly display name used in:
    - Agent card name (A2A protocol)
    - On-chain metadata (agentName field)
    
    Unlike AGENT_ID, AGENT_NAME can contain spaces, hyphens, and other characters.
    
    Returns:
        Agent name string (from AGENT_NAME env var, or AGENT_ID if not set, or DEFAULT_AGENT_ID)
    """
    agent_name = os.getenv("AGENT_NAME")
    if agent_name:
        return agent_name
    
    # Fallback to AGENT_ID if AGENT_NAME not set
    return get_agent_id()


def get_agent_id(env_value: str | None = None) -> str:
    """
    Get and validate agent ID from environment variable or provided value.
    
    Agent ID must be a valid Python identifier:
    - Must start with a letter (a-z, A-Z) or underscore (_)
    - Can only contain letters, digits, and underscores
    - Cannot be empty
    
    This restriction exists because:
    - Agent ID is used as BaseAgent.name parameter (may need to be valid identifier)
    - Used in database queries and as identifiers throughout the codebase
    - Prevents issues with special characters in URLs, filenames, SQL queries, etc.
    
    Args:
        env_value: Optional value to use (if None, reads from AGENT_ID env var)
    
    Returns:
        Validated agent ID string (defaults to DEFAULT_AGENT_ID if not set)
    
    Raises:
        ValueError: If agent_id contains invalid characters or doesn't start with letter/underscore
    """
    agent_id = env_value if env_value is not None else os.getenv("AGENT_ID")
    
    if not agent_id:
        return DEFAULT_AGENT_ID
    
    # Validate: must be a valid Python identifier
    if not agent_id.isidentifier():
        raise ValueError(
            f"AGENT_ID '{agent_id}' is not a valid identifier. "
            f"Must start with a letter or underscore, and only contain letters, digits, and underscores. "
            f"Examples: 'my_agent', 'agent_123', '_internal_agent'"
        )
    
    return agent_id


@dataclass(frozen=True)
class Config:
    agent_id: str  # Internal identifier (must be valid Python identifier)
    agent_name: str  # Display name (can be any string, used in agent card and on-chain metadata)
    mcp_server_url: str
    base_url_override_raw: str
    base_url_override: str
    port: int
    chain_name: str  # anvil, ethereum_sepolia, base_sepolia, ethereum_mainnet
    chain_rpc_url: str
    agent_priv_key: str
    agent_wallet_address: str
    alkahest_address_config_path: str | None
    agent_db_path: str
    event_validation_mode: str  # "warn" or "strict"
    enable_redis_ingest: bool
    redis_url: str
    redis_channels: str  # comma-separated
    enable_event_queue: bool
    log_file_path: str | None  # Path to log file, None for default
    log_level: str  # Logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL
    token_registry_path: str
    ssh_public_key: str
    # Indexer/Registry settings
    indexer_url: str  # INDEXER_URL - ERC-8004 Indexer API URL
    identity_registry_address: str | None  # IDENTITY_REGISTRY_ADDRESS - contract address (on-chain)
    onchain_agent_id: str | None  # ONCHAIN_AGENT_ID - Explicit on-chain agent ID (set by make register)
    # Registry discovery settings
    enable_registry_discovery: bool  # ENABLE_REGISTRY_DISCOVERY - enable registry-based agent discovery
    registry_order_timeout: int  # REGISTRY_ORDER_TIMEOUT - timeout for registry API calls in seconds
    max_discovery_agents: int  # MAX_DISCOVERY_AGENTS - maximum number of agents to contact
    # Order retry settings
    enable_order_retry: bool  # ENABLE_ORDER_RETRY - enable periodic retry of unmatched orders
    order_retry_interval: int  # ORDER_RETRY_INTERVAL - interval between retry attempts in seconds
    # Provisioning settings
    provisioning_mode: str  # PROVISIONING_MODE - "http" | "ansible" | "mock"
    provisioning_service_url: str  # PROVISIONING_SERVICE_URL
    provisioning_timeout: int  # PROVISIONING_TIMEOUT
    provisioning_poll_interval: int  # PROVISIONING_POLL_INTERVAL
    frp_server_addr: str | None  # FRP_SERVER_ADDR - FRP server address for direct provisioning
    frp_domain: str | None  # FRP_DOMAIN - FRP domain for direct provisioning
    frp_dashboard_password: str | None  # FRP_DASHBOARD_PASSWORD - FRP dashboard password
    resource_check_interval: int  # RESOURCE_CHECK_INTERVAL - seconds between availability polls
    resource_lease_grace_seconds: int  # RESOURCE_LEASE_GRACE_SECONDS - force-free a leased
    # resource this many seconds after lease_end_utc if the provisioning check
    # keeps failing/returning "not available". Prevents a transient outage of
    # the provisioning service from stranding leases forever.
    negotiation_timeout_seconds: int  # NEGOTIATION_TIMEOUT_SECONDS - mark an
    # active negotiation thread as terminal_state='abandoned' after this many
    # seconds with no activity (updated_at not touched). Default 1800 = 30 min.
    negotiation_watchdog_interval: int  # NEGOTIATION_WATCHDOG_INTERVAL - how
    # often the watchdog scans the thread table. Default 60s.
    default_vm_host: str  # DEFAULT_VM_HOST - KVM host name from ansible inventory
    # Negotiation policy settings
    negotiation_policy_mode: str  # NEGOTIATION_POLICY_MODE - "bisection" | "rl"
    arkhai_negotiator_seller_model_path: str  # ARKHAI_NEGOTIATOR_SELLER_MODEL_PATH
    arkhai_negotiator_buyer_model_path: str  # ARKHAI_NEGOTIATOR_BUYER_MODEL_PATH

DEFAULT_TOKEN_REGISTRY_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "token_registry_docker_compose.json"
)


def _resolve_provisioning_mode() -> str:
    """Resolve PROVISIONING_MODE: "http" | "ansible" | "mock". Defaults to "http"."""
    mode = os.getenv("PROVISIONING_MODE", "").lower()
    if mode in ("http", "ansible", "mock"):
        return mode
    return "http"


def load_config() -> Config:
    # Get agent_id from environment variable with validation
    agent_id = get_agent_id()
    
    if agent_id == DEFAULT_AGENT_ID and not os.getenv("AGENT_ID"):
        # Only warn if using default (not if user explicitly set it to "root_agent")
        import warnings
        warnings.warn(
            f"AGENT_ID environment variable not set. Using default '{DEFAULT_AGENT_ID}'. "
            f"Please set AGENT_ID to a valid identifier (letters, digits, underscores only).",
            UserWarning
        )
    
    # Get agent_name (display name) - can be any string, falls back to agent_id
    agent_name = get_agent_name()

    # BASE_URL_OVERRIDE handling with optional ZeroTier placeholder
    base_url_override_raw = os.getenv("BASE_URL_OVERRIDE", "http://localhost:8000")
    zerotier_network = os.getenv("ZEROTIER_NETWORK")

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
            "[CONFIG] BASE_URL_OVERRIDE is invalid (%s); using raw value from env",
            exc,
        )
        base_url_override_resolved = base_url_override_raw

    return Config(
        agent_id=agent_id,
        agent_name=agent_name,
        mcp_server_url=os.getenv("MCP_SERVER_URL", "http://localhost:8080/mcp"),
        base_url_override_raw=base_url_override_raw,
        base_url_override=base_url_override_resolved,
        port=_get_int_env("PORT", 8000),
        chain_name=os.getenv("CHAIN_NAME", "ethereum_sepolia"),
        chain_rpc_url=os.getenv("CHAIN_RPC_URL"),
        agent_priv_key=os.getenv("AGENT_PRIV_KEY"),
        agent_wallet_address=os.getenv("AGENT_WALLET_ADDRESS"),
        alkahest_address_config_path=os.getenv("ALKAHEST_ADDRESS_CONFIG_PATH"),
        agent_db_path=os.getenv("AGENT_DB_PATH", "/tmp/agent.db"),
        event_validation_mode=os.getenv("EVENT_VALIDATION_MODE", "warn"),
        enable_redis_ingest=_get_bool_env("ENABLE_REDIS_INGEST", False),
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379"),
        redis_channels=os.getenv("REDIS_CHANNELS", "events:*"),
        enable_event_queue=_get_bool_env("ENABLE_EVENT_QUEUE", False),
        log_file_path=os.getenv("LOG_FILE_PATH"),  # None if not set
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        token_registry_path=os.getenv(
            "TOKEN_REGISTRY_PATH", str(DEFAULT_TOKEN_REGISTRY_PATH)
        ),
        ssh_public_key=os.getenv(
            "SSH_PUBLIC_KEY",
            "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDemoPublicKeyForComputeAccess demo@example",
        ),
        # Indexer/Registry settings
        indexer_url=os.getenv("INDEXER_URL", os.getenv("REGISTRY_URL", "http://localhost:8080")),  # Support both for backward compatibility
        identity_registry_address=os.getenv("IDENTITY_REGISTRY_ADDRESS"),
        onchain_agent_id=os.getenv("ONCHAIN_AGENT_ID"),  # Explicit on-chain agent ID (optional)
        # Registry discovery settings
        enable_registry_discovery=_get_bool_env("ENABLE_REGISTRY_DISCOVERY", True),
        registry_order_timeout=_get_int_env("REGISTRY_ORDER_TIMEOUT", 30),
        max_discovery_agents=_get_int_env("MAX_DISCOVERY_AGENTS", 10),
        # Order retry settings
        enable_order_retry=_get_bool_env("ENABLE_ORDER_RETRY", True),
        order_retry_interval=_get_int_env("ORDER_RETRY_INTERVAL", 300),  # Default: 5 minutes
        # Provisioning settings
        provisioning_mode=_resolve_provisioning_mode(),
        provisioning_service_url=os.getenv("PROVISIONING_SERVICE_URL", "http://localhost:8085"),
        provisioning_timeout=_get_int_env("PROVISIONING_TIMEOUT", 3600),
        provisioning_poll_interval=_get_int_env("PROVISIONING_POLL_INTERVAL", 15),
        frp_server_addr=os.getenv("FRP_SERVER_ADDR") or os.getenv("frp_server_addr"),
        frp_domain=os.getenv("FRP_DOMAIN") or os.getenv("frp_domain"),
        frp_dashboard_password=os.getenv("FRP_DASHBOARD_PASSWORD") or os.getenv("frp_dashboard_password"),
        resource_check_interval=_get_int_env("RESOURCE_CHECK_INTERVAL", 300),
        resource_lease_grace_seconds=_get_int_env("RESOURCE_LEASE_GRACE_SECONDS", 1800),
        negotiation_timeout_seconds=_get_int_env("NEGOTIATION_TIMEOUT_SECONDS", 1800),
        negotiation_watchdog_interval=_get_int_env("NEGOTIATION_WATCHDOG_INTERVAL", 60),
        default_vm_host=os.getenv("DEFAULT_VM_HOST", "ww1"),
        # Negotiation policy settings
        negotiation_policy_mode=os.getenv("NEGOTIATION_POLICY_MODE", "bisection").lower(),
        arkhai_negotiator_seller_model_path=os.getenv(
            "ARKHAI_NEGOTIATOR_SELLER_MODEL_PATH",
            "domain/compute/agent/app/policy/models/arkhai_negotiator_seller.pt",
        ),
        arkhai_negotiator_buyer_model_path=os.getenv(
            "ARKHAI_NEGOTIATOR_BUYER_MODEL_PATH",
            "domain/compute/agent/app/policy/models/arkhai_negotiator_buyer.pt",
        ),
    )


# Module-level singleton for convenience
CONFIG = load_config()
