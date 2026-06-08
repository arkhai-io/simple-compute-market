"""Compatibility alias for :mod:`market_alkahest.alkahest`."""

from importlib import import_module
import sys

_module = import_module("market_alkahest.alkahest")
sys.modules[__name__] = _module
