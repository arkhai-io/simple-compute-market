"""Compatibility alias for the VM buyer escrow commands."""

from __future__ import annotations

import sys

from domains.vms.buyer import escrow_cli as _impl

sys.modules[__name__] = _impl
