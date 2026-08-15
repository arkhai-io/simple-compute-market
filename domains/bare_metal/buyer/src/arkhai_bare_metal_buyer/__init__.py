"""Bare-metal buyer contribution."""

from .config import BareMetalBuyerConfig, load_bare_metal_buyer_config
from .plugin import domain

__all__ = ["BareMetalBuyerConfig", "domain", "load_bare_metal_buyer_config"]
