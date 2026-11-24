"""Seller preferences resolved independently for each publication registry."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import injected_time
from market_deal_lifecycle.configuration import (
    DisputeConfig,
    DisputeEntry,
    authorities_by_registry,
    dispute_config,
)

logger = logging.getLogger(__name__)

#: The mechanism readiness resource naming the registries whose
#: recommendations the storefront could not read.
DISPUTE_AUTHORITIES_UNREAD = "dispute_authorities_unread"


@dataclass(frozen=True, slots=True)
class UnreadRegistry:
    """A registry whose last descriptor read failed, and when it failed."""

    url: str
    last_failed_at: datetime

    def public(self) -> dict[str, str]:
        return {"registry": self.url, "last_failed_at": self.last_failed_at.isoformat()}


@dataclass
class RegistryDisputePolicy:
    """A seller's dispute authorities per registry, and the state of each read.

    Each registry's recommendations come from its signed descriptor. A
    registry whose read failed contributes none, and is read again by
    :meth:`reread` until a read succeeds; a successful read is kept until the
    process restarts, so a registry that changes its recommendations reaches
    a running storefront only through its restart.
    """

    config: DisputeConfig
    authorities: dict[str, tuple[DisputeEntry, ...]] = field(default_factory=dict)
    # The time of the world a failure is recorded at: the process's source.
    clock: Callable[[], datetime] = field(default=injected_time.now_datetime, repr=False)
    _recommendations: dict[str, list[Any]] = field(default_factory=dict, init=False, repr=False)
    _last_failures: dict[str, datetime] = field(default_factory=dict, init=False, repr=False)
    _unread: set[str] = field(default_factory=set, init=False, repr=False)
    # The registry client factory the startup read was given, which the
    # re-read uses, so it reads the registries the storefront publishes through.
    _client_factory: Callable[[], Any] | None = field(default=None, init=False, repr=False)
    # Held across every read, so compositions that overlap read one at a time:
    # a failure answered after another read's success cannot mark a read
    # registry unread again, and a registry is not requested twice at once.
    _reading: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

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

    def unread_registries(self) -> tuple[UnreadRegistry, ...]:
        """Every registry whose last read failed, with when it last failed."""
        return tuple(
            UnreadRegistry(url, self._last_failures[url])
            for url in self._recommendations
            if url in self._unread
        )

    def readiness_resources(self) -> dict[str, Any]:
        """The unread registries as a mechanism readiness resource, or nothing.

        Registries are read only while ``use_registry_dispute_authorities`` is
        true, so none is unread while it is false.
        """
        unread = self.unread_registries()
        if not unread:
            return {}
        return {DISPUTE_AUTHORITIES_UNREAD: [registry.public() for registry in unread]}

    async def refresh(self, client_factory: Callable[[], Any] | None) -> None:
        """Read recommendations under configured registry pins, before publication.

        A failed registry contributes no recommendations. Local preferences and
        vetoes still apply, and one registry never supplies another's defaults.
        """
        async with self._reading:
            self._recommendations.clear()
            self._unread.clear()
            self._client_factory = client_factory
            if client_factory is not None:
                client = client_factory()
                urls = client.urls
                self._recommendations.update({url: [] for url in urls})
                if self.config.use_registry_dispute_authorities:
                    await self._read(client, urls)
            self._resolve()

    async def reread(self) -> None:
        """Read again only the registries whose last read failed.

        It reads through the client factory :meth:`refresh` was given. Every
        other registry keeps the recommendations its read gave. With no
        registry unread, nothing is read. A re-read that overlaps another
        waits for it, and then reads only what is still unread.
        """
        async with self._reading:
            if self._client_factory is None or not self._unread:
                return
            unread = [url for url in self._recommendations if url in self._unread]
            # A registry still unread changes nothing, so resolving again would
            # only repeat the warnings its first failure gave.
            if await self._read(self._client_factory(), unread):
                self._resolve()

    async def _read(self, client: Any, urls: Iterable[str]) -> bool:
        """Read ``urls``' descriptors, recording each outcome; True if any was read."""
        urls = list(urls)
        descriptors: Mapping[str, Any] = {}
        try:
            async with client:
                descriptors = await client.get_descriptors(registries=urls)
        except Exception as exc:
            logger.warning("registry descriptors unavailable (%s)", type(exc).__name__)
        failed_at = self.clock()
        any_read = False
        for url in urls:
            descriptor = descriptors.get(url)
            if descriptor is None:
                self._unread.add(url)
                self._last_failures[url] = failed_at
                continue
            any_read = True
            self._unread.discard(url)
            self._recommendations[url] = list(descriptor.recommended_dispute_authorities or [])
        return any_read

    def _resolve(self) -> None:
        resolved = authorities_by_registry(
            self.config,
            self._recommendations,
            role="seller",
            report=logger.warning,
        )
        self.authorities.clear()
        self.authorities.update(resolved)
