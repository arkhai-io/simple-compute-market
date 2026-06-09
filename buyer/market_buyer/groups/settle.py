"""Compatibility alias for the VM buyer settlement command."""

from __future__ import annotations

import sys

from domains.vms.buyer import settle_cli as _impl

sys.modules[__name__] = _impl
