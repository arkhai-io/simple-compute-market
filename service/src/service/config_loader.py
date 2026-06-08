"""Compatibility alias for :mod:`market_config.config_loader`."""

from importlib import import_module
import sys

_module = import_module("market_config.config_loader")
sys.modules[__name__] = _module
