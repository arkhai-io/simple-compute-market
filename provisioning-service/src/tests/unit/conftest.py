"""
Shared fixtures for unit tests.

Unit tests are synchronous and do not start the FastAPI app.
Each fixture provides a lightweight mock of the Settings object
so service constructors can be called without real config files.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_settings():
    """A MagicMock that stands in for Settings in service constructors.

    Tests that need specific values should set them directly::

        mock_settings.ansible_timeout_seconds = 60
    """
    settings = MagicMock()
    settings.default_vm_host = "kvm1"
    settings.default_max_retries = 3
    settings.retry_backoff_initial_seconds = 60
    settings.retry_backoff_multiplier = 2.0
    settings.retry_backoff_max_seconds = 3600
    settings.ansible_timeout_seconds = 1800
    settings.non_retryable_errors = [
        "Invalid SSH key",
        "VM target not found",
        "Permission denied",
        "Authentication failed",
        "UNREACHABLE",
        "Domain not found",
    ]
    settings.frp_server_addr = ""
    settings.frp_domain = ""
    settings.frp_dashboard_password = ""
    return settings
