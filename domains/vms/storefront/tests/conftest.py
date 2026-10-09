"""Explicit public configuration for the storefront test process."""

from __future__ import annotations

import os

os.environ.setdefault(
    "STOREFRONT_STOREFRONT_DOMAINS",
    '@json [{"contribution":"vms","offering_mode":"vm",'
    '"domain_identity":"compute.v1","contract_version":"1.0"}]',
)
