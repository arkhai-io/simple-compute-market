"""Compatibility alias for :mod:`market_alkahest.chain_probe`."""

from importlib import import_module
import sys

_module = import_module("market_alkahest.chain_probe")
sys.modules[__name__] = _module
