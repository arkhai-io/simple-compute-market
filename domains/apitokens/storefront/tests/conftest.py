"""Test bootstrap: environment overrides land before any config import."""

from __future__ import annotations

import os

# Registry fan-out stays local in unit tests; the settings singleton is
# built on first config import, so these must be set here.
os.environ.setdefault("APITOKENS_STOREFRONT_ENABLE_REGISTRY_DISCOVERY", "false")
os.environ.setdefault("APITOKENS_STOREFRONT_DB_PATH", "/tmp/apitokens-storefront-test.db")
