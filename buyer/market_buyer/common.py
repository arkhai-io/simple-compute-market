"""Compatibility alias for :mod:`domains.vms.buyer.common`."""

from importlib import import_module
import sys

_module = import_module("domains.vms.buyer.common")
sys.modules[__name__] = _module
