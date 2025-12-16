import json
import logging
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)


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
