import asyncio
import json
import logging
import subprocess
import time
from typing import Optional
from urllib.parse import urlparse, urlunparse

logger = logging.getLogger(__name__)

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
    """Replace the token with the provided ZeroTier IP and return the result."""
    return base_url.replace(ZEROTIER_IP_TOKEN, zerotier_ip)


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


def get_zerotier_ip(network_id: str, *, timeout: float = 5.0) -> Optional[str]:
    """
    Return the first assigned IP for the given ZeroTier network, if any.

    Uses `sudo zerotier-cli listnetworks -j` (may prompt for privileges).
    """
    if not network_id:
        return None

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
        logger.warning("ZeroTier CLI not found; skipping IP lookup.")
        return None
    except subprocess.TimeoutExpired:
        logger.warning("ZeroTier CLI timed out while listing networks.")
        return None
    except subprocess.CalledProcessError as exc:
        logger.warning("ZeroTier CLI error when listing networks: %s", exc.stderr or exc.stdout)
        return None

    try:
        networks = json.loads(proc.stdout)
    except json.JSONDecodeError:
        logger.warning("ZeroTier CLI returned invalid JSON.")
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
