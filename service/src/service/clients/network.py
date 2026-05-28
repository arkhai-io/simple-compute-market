import json
import logging
import subprocess
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

NetworkInfo = Dict[str, Any]

ZEROTIER_IP_TOKEN = "{ZEROTIER_IP}"


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


def _check_zerotier_cli() -> bool:
    """Return True if zerotier-cli is installed, False otherwise."""
    try:
        subprocess.run(
            ["zerotier-cli", "-v"],
            check=False,
            capture_output=True,
            text=True,
        )
        return True
    except FileNotFoundError:
        logger.warning("ZeroTier CLI not found. Install with: cd scripts/zerotier && make install")
        return False


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


# Convenience re-export for callers who need URL resolution
try:
    from market_storefront.utils.zerotier import await_base_url_resolution
except ImportError:
    await_base_url_resolution = None  # type: ignore[assignment]

__all__ = [
    "ZEROTIER_IP_TOKEN",
    "get_zerotier_ip",
    "is_network_joined",
    "join_zerotier_network",
    "get_zerotier_node_id",
    "await_base_url_resolution",
]
