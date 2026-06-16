"""Compatibility shim — direct ERC-20 transfers moved to
``core_storefront.token_transfer`` when the API-tokens domain became
the second storefront composition root."""

from core_storefront.token_transfer import (  # noqa: F401
    _transfer_sync,
    transfer_erc20,
)
