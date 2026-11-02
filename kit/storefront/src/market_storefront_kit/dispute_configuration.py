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

    def for_publication(self) -> tuple[DisputeEntry, ...]:
        """Offer only authorities allowed at every destination of a shared listing.

        Publication stores one option set for all its registries. A registry's
        recommendations cannot silently become another registry's defaults.
        """
        destinations = [entries for url, entries in self.authorities.items() if url]
        if not destinations:
            return self.authorities.get("", self.config.authorities(role="seller"))
        return tuple(entry for entry in destinations[0]
                     if all(entry in entries for entries in destinations[1:]))

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
