"""Core orchestration for automated storefront publication sources.

Domain packages provide :class:`PublicationSource` adapters. Concrete
storefront composition roots provide infrastructure callbacks for settlement
payload construction and listing publication. This module owns only the generic
control flow over sources.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .publication_plugins import build_publication_source
from .publication_sources import PublicationSource

Payload = tuple[list[dict[str, Any]], list[dict[str, Any]], int | None]
PayloadBuilder = Callable[
    [PublicationSource, dict[str, Any], dict[str, Any]],
    Payload | str,
]
PublishOffer = Callable[
    [
        dict[str, Any],
        list[dict[str, Any]],
        list[dict[str, Any]],
        int | None,
    ],
    dict[str, Any],
]


@dataclass(frozen=True)
class PublicationCycleResult:
    """Result from one core-owned publication command cycle."""

    closed: dict[str, list[str]]
    published: list[dict[str, Any]]
    failed: list[tuple[dict[str, Any], str]]
    skipped: list[dict[str, Any]]


@dataclass(frozen=True)
class PublicationCommandResult:
    """Command-facing publication result with reusable summary semantics."""

    cycle: PublicationCycleResult

    @property
    def closed(self) -> dict[str, list[str]]:
        return self.cycle.closed

    @property
    def published(self) -> list[dict[str, Any]]:
        return self.cycle.published

    @property
    def failed(self) -> list[tuple[dict[str, Any], str]]:
        return self.cycle.failed

    @property
    def skipped(self) -> list[dict[str, Any]]:
        return self.cycle.skipped

    @property
    def published_count(self) -> int:
        return len(self.published)

    @property
    def failed_count(self) -> int:
        return len(self.failed)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)

    @property
    def closed_count(self) -> int:
        return sum(len(listing_ids) for listing_ids in self.closed.values())

    @property
    def has_publications(self) -> bool:
        return self.published_count > 0

    @property
    def has_failures(self) -> bool:
        return self.failed_count > 0

    @property
    def no_new_listings(self) -> bool:
        """True when the command did not publish or fail any candidate."""
        return not self.has_publications and not self.has_failures


@dataclass(frozen=True)
class PublicationCommand:
    """Reusable command surface for selected domain publication sources."""

    selection: "PublicationSourceSelection"
    db_path: str
    base_url: str
    build_payload: PayloadBuilder
    publish_offer: PublishOffer

    def run(
        self,
        *,
        skip_ids: set[str] | None = None,
        close_stale: bool = True,
        skip_open: bool = True,
    ) -> PublicationCommandResult:
        """Run one publication command cycle."""
        return run_publication_command(
            self.selection,
            db_path=self.db_path,
            base_url=self.base_url,
            build_payload=self.build_payload,
            publish_offer=self.publish_offer,
            skip_ids=skip_ids,
            close_stale=close_stale,
            skip_open=skip_open,
        )


@dataclass(frozen=True)
class PublicationSourceSelection:
    """Core-owned selection of domain publication sources.

    Storefront composition roots use this as the small command-facing wrapper:
    choose source entry-point names, provide per-source infrastructure kwargs,
    then let core build sources and run publication cycles.
    """

    source_names: Sequence[str]
    source_kwargs_by_name: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    def build_sources(self) -> tuple[PublicationSource, ...]:
        """Build the selected publication source adapters."""
        return build_publication_sources_by_name(
            self.source_names,
            source_kwargs_by_name={
                name: dict(kwargs)
                for name, kwargs in self.source_kwargs_by_name.items()
            },
        )

    def close_stale(
        self,
        *,
        db_path: str,
        base_url: str,
    ) -> dict[str, list[str]]:
        """Close stale listings for the selected sources."""
        return close_stale_publication_listings(
            self.build_sources(),
            db_path=db_path,
            base_url=base_url,
        )

    def open_keys(self, db_path: str) -> set[str]:
        """Return open publication keys for the selected sources."""
        return open_publication_keys(self.build_sources(), db_path)

    def command(
        self,
        *,
        db_path: str,
        base_url: str,
        build_payload: PayloadBuilder,
        publish_offer: PublishOffer,
    ) -> PublicationCommand:
        """Create a reusable command object for this source selection."""
        return PublicationCommand(
            selection=self,
            db_path=db_path,
            base_url=base_url,
            build_payload=build_payload,
            publish_offer=publish_offer,
        )

    def run_cycle(
        self,
        *,
        db_path: str,
        base_url: str,
        build_payload: PayloadBuilder,
        publish_offer: PublishOffer,
        skip_ids: set[str] | None = None,
        close_stale: bool = True,
        skip_open: bool = True,
    ) -> PublicationCycleResult:
        """Run one publication cycle for the selected sources."""
        return self.run_command(
            db_path=db_path,
            base_url=base_url,
            build_payload=build_payload,
            publish_offer=publish_offer,
            skip_ids=skip_ids,
            close_stale=close_stale,
            skip_open=skip_open,
        ).cycle

    def run_command(
        self,
        *,
        db_path: str,
        base_url: str,
        build_payload: PayloadBuilder,
        publish_offer: PublishOffer,
        skip_ids: set[str] | None = None,
        close_stale: bool = True,
        skip_open: bool = True,
    ) -> PublicationCommandResult:
        """Run one command-style publication cycle for the selected sources."""
        return run_publication_command(
            self,
            db_path=db_path,
            base_url=base_url,
            build_payload=build_payload,
            publish_offer=publish_offer,
            skip_ids=skip_ids,
            close_stale=close_stale,
            skip_open=skip_open,
        )


def close_stale_publication_listings(
    sources: Iterable[PublicationSource],
    *,
    db_path: str,
    base_url: str,
) -> dict[str, list[str]]:
    """Close stale listings for every configured publication source."""
    return {
        source.name: source.close_stale(db_path, base_url)
        for source in sources
    }


def open_publication_keys(
    sources: Iterable[PublicationSource],
    db_path: str,
) -> set[str]:
    """Return the union of keys already covered by open listings."""
    covered: set[str] = set()
    for source in sources:
        covered.update(source.open_keys(db_path))
    return covered


def build_publication_source_selection(
    source_names: Sequence[str],
    *,
    source_kwargs_by_name: Mapping[str, Mapping[str, Any]] | None = None,
) -> PublicationSourceSelection:
    """Build a command-facing selected-source composition by entry-point name."""
    return PublicationSourceSelection(
        source_names=tuple(source_names),
        source_kwargs_by_name=source_kwargs_by_name or {},
    )


def build_publication_sources_by_name(
    source_names: Sequence[str],
    *,
    source_kwargs_by_name: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[PublicationSource, ...]:
    """Build selected domain publication sources from entry-point names."""
    kwargs_by_name = source_kwargs_by_name or {}
    return tuple(
        build_publication_source(name, **kwargs_by_name.get(name, {}))
        for name in source_names
    )


def publish_source_by_name(
    source_name: str,
    *,
    source_kwargs: dict[str, Any] | None = None,
    db_path: str,
    base_url: str,
    build_payload: PayloadBuilder,
    publish_offer: PublishOffer,
    skip_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[tuple[dict[str, Any], str]], list[dict[str, Any]]]:
    """Load one publication source by name and publish one round."""
    source = build_publication_source(source_name, **(source_kwargs or {}))
    return publish_round(
        [source],
        db_path=db_path,
        base_url=base_url,
        build_payload=build_payload,
        publish_offer=publish_offer,
        skip_ids=skip_ids,
    )


def run_publication_cycle(
    sources: Iterable[PublicationSource],
    *,
    db_path: str,
    base_url: str,
    build_payload: PayloadBuilder,
    publish_offer: PublishOffer,
    skip_ids: set[str] | None = None,
    close_stale: bool = True,
    skip_open: bool = True,
) -> PublicationCycleResult:
    """Run one command-style publication cycle over selected sources.

    The cycle closes stale source listings, computes open publication keys, and
    publishes candidates not already represented by an open listing. Concrete
    storefronts inject settlement payload construction and listing creation.
    """
    selected = tuple(sources)
    closed = (
        close_stale_publication_listings(
            selected,
            db_path=db_path,
            base_url=base_url,
        )
        if close_stale
        else {}
    )
    covered = open_publication_keys(selected, db_path) if skip_open else set()
    if skip_ids:
        covered |= skip_ids
    published, failed, skipped = publish_round(
        selected,
        db_path=db_path,
        base_url=base_url,
        build_payload=build_payload,
        publish_offer=publish_offer,
        skip_ids=covered,
    )
    return PublicationCycleResult(
        closed=closed,
        published=published,
        failed=failed,
        skipped=skipped,
    )


def run_publication_cycle_by_name(
    source_names: Sequence[str],
    *,
    source_kwargs_by_name: Mapping[str, Mapping[str, Any]] | None = None,
    db_path: str,
    base_url: str,
    build_payload: PayloadBuilder,
    publish_offer: PublishOffer,
    skip_ids: set[str] | None = None,
    close_stale: bool = True,
    skip_open: bool = True,
) -> PublicationCycleResult:
    """Build selected sources by name and run one publication cycle."""
    return run_publication_command_by_name(
        source_names,
        source_kwargs_by_name=source_kwargs_by_name,
        db_path=db_path,
        base_url=base_url,
        build_payload=build_payload,
        publish_offer=publish_offer,
        skip_ids=skip_ids,
        close_stale=close_stale,
        skip_open=skip_open,
    ).cycle


def run_publication_command(
    selection: PublicationSourceSelection,
    *,
    db_path: str,
    base_url: str,
    build_payload: PayloadBuilder,
    publish_offer: PublishOffer,
    skip_ids: set[str] | None = None,
    close_stale: bool = True,
    skip_open: bool = True,
) -> PublicationCommandResult:
    """Run the CLI-facing publication command for a source selection."""
    cycle = run_publication_cycle(
        selection.build_sources(),
        db_path=db_path,
        base_url=base_url,
        build_payload=build_payload,
        publish_offer=publish_offer,
        skip_ids=skip_ids,
        close_stale=close_stale,
        skip_open=skip_open,
    )
    return PublicationCommandResult(cycle=cycle)


def run_publication_command_by_name(
    source_names: Sequence[str],
    *,
    source_kwargs_by_name: Mapping[str, Mapping[str, Any]] | None = None,
    db_path: str,
    base_url: str,
    build_payload: PayloadBuilder,
    publish_offer: PublishOffer,
    skip_ids: set[str] | None = None,
    close_stale: bool = True,
    skip_open: bool = True,
) -> PublicationCommandResult:
    """Build selected sources by name and run the CLI-facing command."""
    return run_publication_command(
        build_publication_source_selection(
            source_names,
            source_kwargs_by_name=source_kwargs_by_name,
        ),
        db_path=db_path,
        base_url=base_url,
        build_payload=build_payload,
        publish_offer=publish_offer,
        skip_ids=skip_ids,
        close_stale=close_stale,
        skip_open=skip_open,
    )


def publish_round(
    sources: Iterable[PublicationSource],
    *,
    db_path: str,
    base_url: str,
    build_payload: PayloadBuilder,
    publish_offer: PublishOffer,
    skip_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[tuple[dict[str, Any], str]], list[dict[str, Any]]]:
    """Publish one round of candidates from the configured sources.

    Returns ``(published, failed, skipped)``. Domain semantics live in each
    ``PublicationSource``; settlement and HTTP side effects live in caller
    callbacks. The control flow is intentionally schema-opaque.
    """
    skip_ids = skip_ids or set()
    published: list[dict[str, Any]] = []
    failed: list[tuple[dict[str, Any], str]] = []
    skipped: list[dict[str, Any]] = []

    for source in sources:
        for candidate in source.available_candidates(db_path):
            if source.skip_keys(candidate) & skip_ids:
                skipped.append(candidate)
                continue

            offer = source.offer_resource(candidate)
            payload = build_payload(source, candidate, offer)
            if isinstance(payload, str):
                failed.append((candidate, payload))
                continue
            accepted_escrows, demands, max_duration_seconds = payload

            try:
                reopened = source.reopen_existing(
                    db_path,
                    base_url,
                    candidate,
                    offer,
                    accepted_escrows,
                    demands,
                    max_duration_seconds,
                )
            except Exception as exc:
                failed.append((candidate, f"{source.reopen_error_label}: {exc}"))
                continue

            if reopened is not None:
                if reopened.get("status") in {"published", "disabled"}:
                    published.append({
                        "resource": candidate,
                        "response": reopened,
                        "accepted_escrows": accepted_escrows,
                        "demands": demands,
                    })
                else:
                    failed.append((
                        candidate,
                        reopened.get("message") or str(reopened),
                    ))
                continue

            try:
                response = publish_offer(
                    offer,
                    accepted_escrows,
                    demands,
                    max_duration_seconds,
                )
                if response.get("listing_id"):
                    source.record_published(
                        db_path,
                        candidate,
                        str(response["listing_id"]),
                    )
                published.append({
                    "resource": candidate,
                    "response": response,
                    "accepted_escrows": accepted_escrows,
                    "demands": demands,
                })
            except Exception as exc:
                failed.append((candidate, str(exc)))

    return published, failed, skipped
