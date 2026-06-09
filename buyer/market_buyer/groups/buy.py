"""Compatibility alias for the VM buyer ``market buy`` command."""

from __future__ import annotations

import sys

from domains.vms.buyer import buy_cli as _impl

sys.modules[__name__] = _impl
