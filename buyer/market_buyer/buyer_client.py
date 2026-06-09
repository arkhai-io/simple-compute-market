"""Compatibility alias for :mod:`domains.vms.buyer.buyer_client`."""

from importlib import import_module
import sys

_module = import_module("domains.vms.buyer.buyer_client")
sys.modules[__name__] = _module
