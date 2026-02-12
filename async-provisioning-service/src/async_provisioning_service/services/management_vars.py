"""
Management vars loader for golden image credentials.

Reads management-vars.yaml from the compute-provisioning-iac submodule
and provides golden image credentials server-side. Agents never see
these credentials directly.
"""

import logging
from dataclasses import dataclass
from typing import Optional

import yaml

from async_provisioning_service.config import settings


logger = logging.getLogger(__name__)

# Module-level cache for management vars
_cached_vars: Optional[dict] = None


@dataclass
class GoldenImageCredentials:
    root_ssh_filename: str
    root_ssh_password: str
    golden_image_name: Optional[str] = None
    gcs_bucket: Optional[str] = None
    gcs_project: Optional[str] = None


def load_management_vars(force_reload: bool = False) -> dict:
    """Load and cache management-vars.yaml from IAC submodule.

    Returns the parsed YAML as a dictionary. Caches the result for
    subsequent calls unless force_reload is True.
    """
    global _cached_vars

    if _cached_vars is not None and not force_reload:
        return _cached_vars

    path = settings.management_vars_path
    try:
        content = path.read_text(encoding="utf-8")
        _cached_vars = yaml.safe_load(content) or {}
        logger.info("Loaded management vars from %s", path)
        return _cached_vars
    except FileNotFoundError:
        logger.warning("Management vars file not found: %s", path)
        return {}
    except yaml.YAMLError as exc:
        logger.error("Failed to parse management vars YAML: %s", exc)
        return {}


def get_golden_image_credentials() -> Optional[GoldenImageCredentials]:
    """Extract golden image credentials from management vars.

    Returns None if management vars are not available or credentials
    are not configured.
    """
    vars_data = load_management_vars()
    if not vars_data:
        return None

    root_ssh_filename = vars_data.get("root_ssh_filename")
    root_ssh_password = vars_data.get("root_ssh_password")

    if not root_ssh_filename or not root_ssh_password:
        logger.warning("Golden image credentials not found in management vars")
        return None

    return GoldenImageCredentials(
        root_ssh_filename=root_ssh_filename,
        root_ssh_password=root_ssh_password,
        golden_image_name=vars_data.get("golden_image_name"),
        gcs_bucket=vars_data.get("gcs_bucket"),
        gcs_project=vars_data.get("gcs_project"),
    )
