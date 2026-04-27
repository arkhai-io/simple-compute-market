import asyncio
import json
import logging
import subprocess
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, urlunparse

logger = logging.getLogger(__name__)

NetworkInfo = Dict[str, Any]

ZEROTIER_IP_TOKEN = "{ZEROTIER_IP}"


class BaseUrlResolutionError(Exception):
    """Raised when BASE_URL_OVERRIDE cannot be resolved into a valid URL."""


def _normalize_base_url(url: str) -> str:
    """
    Validate and normalize a base URL.

    Ensures scheme, host, and port are present and strips any trailing slash from the path.
    """
    parsed = urlparse(url)
    if not parsed.scheme:
        raise BaseUrlResolutionError("BASE_URL_OVERRIDE must include a scheme (e.g., http://).")
    if not parsed.hostname:
        raise BaseUrlResolutionError("BASE_URL_OVERRIDE must include a host.")
    if parsed.port is None:
        raise BaseUrlResolutionError("BASE_URL_OVERRIDE must include a port.")

    path = parsed.path.rstrip("/")
    normalized = parsed._replace(path=path)
    return urlunparse(normalized)


def _replace_zerotier_token(base_url: str, zerotier_ip: str) -> str:
    """Replace the {ZEROTIER_IP} token with the provided ZeroTier IP."""
    return base_url.replace(ZEROTIER_IP_TOKEN, zerotier_ip)


def _list_zerotier_networks(timeout: float = 5.0) -> Optional[List[NetworkInfo]]:
    """List all ZeroTier networks via zerotier-cli."""
    cmd = ["sudo", "zerotier-cli", "listnetworks", "-j"]
    try:
        proc = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        logger.warning("ZeroTier CLI not found.")
        return None
    except subprocess.TimeoutExpired:
        logger.warning("ZeroTier CLI timed out while listing networks.")
        return None
    except subprocess.CalledProcessError as exc:
        logger.warning("ZeroTier CLI error when listing networks: %s", exc.stderr or exc.stdout)
        return None

    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        logger.warning("ZeroTier CLI returned invalid JSON.")
        return None


def get_zerotier_ip(network_id: str, *, timeout: float = 5.0) -> Optional[str]:
    """
    Return the first assigned IP for the given ZeroTier network, if any.
    """
    if not network_id:
        return None

    networks = _list_zerotier_networks(timeout=timeout)
    if not networks:
        return None

    for net in networks:
        if net.get("id") != network_id:
            continue
        addresses = net.get("assignedAddresses") or []
        if not addresses:
            return None
        # Take the first assigned address, drop CIDR suffix if present.
        return addresses[0].split("/")[0]

    logger.info("ZeroTier network %s not found in listnetworks output.", network_id)
    return None


def is_network_joined(network_id: str) -> bool:
    """Check if the given ZeroTier network is already joined."""
    if not network_id:
        return False

    networks = _list_zerotier_networks()
    if not networks:
        return False

    return any(net.get("id") == network_id for net in networks)


def join_zerotier_network(network_id: str) -> bool:
    """
    Join the given ZeroTier network.

    Returns True if the join command was issued successfully.
    """
    if not network_id:
        logger.warning("No ZeroTier network ID provided; cannot join network.")
        return False

    if is_network_joined(network_id):
        logger.info("ZeroTier network %s already joined.", network_id)
        return True

    if not _check_zerotier_cli():
        return False

    cmd = ["sudo", "zerotier-cli", "join", network_id]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        logger.info("Joined ZeroTier network %s.", network_id)
        return True
    except subprocess.CalledProcessError as exc:
        logger.error("Failed to join ZeroTier network %s: %s", network_id, exc.stderr or exc.stdout)
        return False


def _check_zerotier_cli() -> bool:
    """Return True if zerotier-cli is installed, False otherwise."""
    try:
        subprocess.run(
            ["sudo", "zerotier-cli", "-v"],
            check=False,
            capture_output=True,
            text=True,
        )
        return True
    except FileNotFoundError:
        logger.warning("ZeroTier CLI not found. Install with: cd infra && make install")
        return False


def get_zerotier_node_id() -> Optional[str]:
    """Return the local ZeroTier node ID, if available."""
    if not _check_zerotier_cli():
        return None

    try:
        proc = subprocess.run(
            ["sudo", "zerotier-cli", "info"],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        logger.warning("ZeroTier CLI error when getting node ID: %s", exc.stderr or exc.stdout)
        return None
    except FileNotFoundError:
        # Already logged by _check_zerotier_cli
        return None

    parts = proc.stdout.split()
    if len(parts) >= 3:
        return parts[2]
    return None


def resolve_base_url_best_effort(base_url_override: str, zerotier_network: Optional[str]) -> str:
    """
    Resolve BASE_URL_OVERRIDE once without waiting.

    - If no token is present, validate and return the normalized URL.
    - If token is present and IP is available, substitute and normalize.
    - If token is present but IP is not yet available, return the raw base_url_override.
    """
    if not base_url_override:
        raise BaseUrlResolutionError("BASE_URL_OVERRIDE is empty.")

    has_token = ZEROTIER_IP_TOKEN in base_url_override
    if not has_token:
        return _normalize_base_url(base_url_override)

    if not zerotier_network:
        raise BaseUrlResolutionError(
            "BASE_URL_OVERRIDE uses {ZEROTIER_IP} but ZEROTIER_NETWORK is not set."
        )

    zerotier_ip = get_zerotier_ip(zerotier_network)
    if not zerotier_ip:
        # IP not assigned yet; caller can decide to keep placeholder.
        return base_url_override

    substituted = _replace_zerotier_token(base_url_override, zerotier_ip)
    return _normalize_base_url(substituted)


async def await_base_url_resolution(
    base_url_override: str,
    zerotier_network: Optional[str],
    *,
    wait_timeout: float = 120.0,
    initial_interval: float = 2.0,
    max_interval: float = 15.0,
) -> str:
    """
    Resolve BASE_URL_OVERRIDE, waiting for ZeroTier IP if a token is present.

    Raises BaseUrlResolutionError if resolution fails or times out.
    """
    if not base_url_override:
        raise BaseUrlResolutionError("BASE_URL_OVERRIDE is empty.")

    has_token = ZEROTIER_IP_TOKEN in base_url_override
    if not has_token:
        return _normalize_base_url(base_url_override)

    if not zerotier_network:
        raise BaseUrlResolutionError(
            "BASE_URL_OVERRIDE uses {ZEROTIER_IP} but ZEROTIER_NETWORK is not set."
        )

    deadline = time.monotonic() + wait_timeout
    interval = initial_interval

    while True:
        zerotier_ip = get_zerotier_ip(zerotier_network)
        if zerotier_ip:
            substituted = _replace_zerotier_token(base_url_override, zerotier_ip)
            return _normalize_base_url(substituted)

        now = time.monotonic()
        if now >= deadline:
            raise BaseUrlResolutionError(
                f"ZeroTier IP not available after waiting {wait_timeout:.0f}s for network {zerotier_network}."
            )

        remaining = deadline - now
        logger.info(
            "Waiting for ZeroTier IP for network %s (placeholder present in BASE_URL_OVERRIDE). "
            "Retrying in %.1fs (%.0fs remaining).",
            zerotier_network,
            interval,
            remaining,
        )
        await asyncio.sleep(interval)
        interval = min(max_interval, interval * 1.5)
