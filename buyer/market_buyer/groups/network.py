"""Compatibility alias for :mod:`domains.vms.buyer.network_cli`."""

from importlib import import_module
import sys

_module = import_module("domains.vms.buyer.network_cli")
sys.modules[__name__] = _module
