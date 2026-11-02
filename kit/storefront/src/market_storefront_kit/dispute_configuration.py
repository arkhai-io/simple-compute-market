"""Seller preferences resolved independently for each publication registry."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from market_deal_lifecycle.configuration import (
    DisputeConfig,
    DisputeEntry,
    authorities_by_registry,
    dispute_config,
)

logger = logging.getLogger(__name__)


@dataclass
class RegistryDisputePolicy:
    config: DisputeConfig
    authorities: dict[str, tuple[DisputeEntry, ...]] = field(default_factory=dict)

    @classmethod
    def from_document(cls, document: Mapping[str, Any]) -> RegistryDisputePolicy:
        return cls(dispute_config(document, role="seller"))

    async def refresh(self, client_factory: Callable[[], Any] | None) -> None:
        """Read recommendations under configured registry pins, before publication.

        A failed registry contributes no recommendations. Local preferences and
        vetoes still apply, and one registry never supplies another's defaults.
        """
        descriptors = {}
        if client_factory is not None:
            client = client_factory()
            descriptors = {url: None for url in client.urls}
            if self.config.use_registry_dispute_authorities:
                try:
                    async with client:
                        descriptors = await client.get_descriptors()
                except Exception as exc:
                    logger.warning("registry descriptors unavailable (%s)", type(exc).__name__)
        resolved = authorities_by_registry(
            self.config,
            {url: descriptor.recommended_dispute_authorities or [] if descriptor else []
             for url, descriptor in descriptors.items()},
            role="seller",
            report=logger.warning,
        )
        self.authorities.clear()
        self.authorities.update(resolved)
