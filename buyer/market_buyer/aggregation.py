"""Compatibility alias for :mod:`domains.vms.buyer.aggregation`."""

from importlib import import_module
import sys

_module = import_module("domains.vms.buyer.aggregation")
sys.modules[__name__] = _module
