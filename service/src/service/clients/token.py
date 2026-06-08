"""Compatibility alias for :mod:`market_alkahest.token`."""

from importlib import import_module
import sys

_module = import_module("market_alkahest.token")
sys.modules[__name__] = _module
