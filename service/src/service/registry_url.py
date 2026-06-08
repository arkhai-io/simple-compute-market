"""Compatibility alias for :mod:`market_config.registry_url`."""

from importlib import import_module
import sys

_module = import_module("market_config.registry_url")
sys.modules[__name__] = _module
