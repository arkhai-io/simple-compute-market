"""Compatibility alias for :mod:`market_config.role`."""

from importlib import import_module
import sys

_module = import_module("market_config.role")
sys.modules[__name__] = _module
