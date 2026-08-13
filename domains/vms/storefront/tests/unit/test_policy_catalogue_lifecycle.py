"""The negotiation policy catalogue is composed at startup, not per request.

The permanent contract is that composition failures surface before the role
serves traffic. That only holds if composition happens during application
startup: a catalogue rebuilt on each negotiation moves a broken operator policy
directory, a duplicate source, or a malformed middleware from a startup failure
into a request failure, and lets filesystem discovery observe changes mid-process.

This was implemented per hook first, contradicting the documented invariant.
"""

from __future__ import annotations

import pytest
from market_policy import InlineSource, negotiation_catalogue_builder

from market_storefront import container
from market_storefront.utils import sync_negotiation


def test_the_negotiation_path_does_not_compose_a_catalogue(monkeypatch) -> None:
    """Reaching negotiation with none resolved is a composition bug, not a
    reason to build one late."""
    monkeypatch.setattr(container, "resolved_policy_catalogue", None)

    def _fail(*_args, **_kwargs):
        raise AssertionError("negotiation composed a catalogue on demand")

    monkeypatch.setattr(sync_negotiation, "compose_policy_catalogue", _fail)

    with pytest.raises(RuntimeError, match="lifespan startup"):
        container.policy_catalogue()


def test_the_resolved_catalogue_is_what_negotiation_reads(monkeypatch) -> None:
    sentinel = (
        negotiation_catalogue_builder()
        .add_loader(InlineSource({"sentinel": lambda h, c: None}, label="test"))
        .build()
    )
    monkeypatch.setattr(container, "resolved_policy_catalogue", sentinel)

    assert container.policy_catalogue() is sentinel
    assert container.policy_catalogue().names() == ("sentinel",)


def test_a_broken_source_fails_composition_rather_than_a_request() -> None:
    """The failure the lifecycle change relocates: it belongs to startup."""

    class _Broken:
        def describe(self) -> str:
            return "broken-operator-directory"

        def load(self):
            raise OSError("policy directory unreadable")

    builder = negotiation_catalogue_builder().add_loader(_Broken())

    with pytest.raises(Exception, match="broken-operator-directory"):
        builder.build()


def test_composition_is_reachable_as_a_startup_step() -> None:
    """`server._populate_container` calls this; it must not need a request."""
    catalogue = sync_negotiation.compose_policy_catalogue()

    assert catalogue.names()
