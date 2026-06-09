"""Compatibility alias for :mod:`domains.vms.buyer.buy_orchestrator`."""

from importlib import import_module
import sys

_module = import_module("domains.vms.buyer.buy_orchestrator")
sys.modules[__name__] = _module
