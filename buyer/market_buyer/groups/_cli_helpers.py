"""Compatibility alias for :mod:`domains.vms.buyer.cli_helpers`."""

from importlib import import_module
import sys

_module = import_module("domains.vms.buyer.cli_helpers")
sys.modules[__name__] = _module
