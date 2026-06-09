"""Compatibility alias for the VM buyer negotiation command."""

from __future__ import annotations

import sys

from domains.vms.buyer import negotiate_cli as _impl

sys.modules[__name__] = _impl
