"""Configuration and sink construction fail early, and never at reveal time."""

from __future__ import annotations

import pytest

from market_delivery import (
    ConfiguredSink,
    DeliveryConfigurationError,
    build_delivery_sinks,
    load_delivery_config,
)
from market_delivery.discovery import discover_sink_factories


def test_absent_configuration_means_no_delivery() -> None:
    config = load_delivery_config(None)

    assert config.active is False
    assert build_delivery_sinks(config).sinks == ()
    assert not build_delivery_sinks(config)


def test_per_sink_tables_sit_directly_under_the_section() -> None:
    config = load_delivery_config(
        {
            "enabled": ["file", "webhook"],
            "timeout_seconds": 4.0,
            "file": {"path": "/tmp/introductions.jsonl"},
            "webhook": {"url": "https://example.invalid/hook"},
        }
    )

    assert config.enabled == ("file", "webhook")
    assert config.timeout_seconds == 4.0
    assert config.settings_for("file") == {"path": "/tmp/introductions.jsonl"}


def test_a_scalar_typo_in_the_section_is_refused() -> None:
    with pytest.raises(DeliveryConfigurationError, match="unknown setting"):
        load_delivery_config({"enabled": ["file"], "timout_seconds": 3})


def test_settings_for_a_sink_nobody_enabled_are_refused() -> None:
    with pytest.raises(DeliveryConfigurationError, match="not enabled"):
        load_delivery_config({"enabled": ["file"], "webhok": {"url": "x"}})


def test_the_same_sink_cannot_be_enabled_twice() -> None:
    with pytest.raises(DeliveryConfigurationError, match="twice"):
        load_delivery_config({"enabled": ["file", "file"], "file": {"path": "/tmp/x"}})


def test_an_uninstalled_sink_fails_when_the_set_is_built() -> None:
    config = load_delivery_config({"enabled": ["pigeon"], "pigeon": {}})

    with pytest.raises(DeliveryConfigurationError, match="not installed"):
        build_delivery_sinks(config, factories={"file": lambda settings: None})


def test_settings_a_sink_rejects_fail_when_the_set_is_built() -> None:
    def picky(settings):
        raise ValueError("needs a path")

    config = load_delivery_config({"enabled": ["picky"], "picky": {}})

    with pytest.raises(DeliveryConfigurationError, match="rejected its settings"):
        build_delivery_sinks(config, factories={"picky": picky})


def test_a_broken_distribution_is_reported_and_survived(monkeypatch) -> None:
    class BrokenEntryPoint:
        name = "broken"

        def load(self):
            raise ImportError("no module named anything")

    class WorkingEntryPoint:
        name = "working"

        def load(self):
            return lambda settings: (lambda event: None)

    monkeypatch.setattr(
        "market_delivery.discovery._iter_entry_points",
        lambda: [BrokenEntryPoint(), WorkingEntryPoint()],
    )
    factories, warnings = discover_sink_factories()

    assert set(factories) == {"working"}
    assert warnings and "broken" in warnings[0] and "skipped" in warnings[0]

    built = build_delivery_sinks(load_delivery_config({"enabled": ["working"]}))
    assert [sink.name for sink in built.sinks] == ["working"]
    assert built.warnings == warnings


def test_a_sink_timeout_overrides_the_section_default() -> None:
    config = load_delivery_config(
        {
            "enabled": ["quick", "slow"],
            "timeout_seconds": 9.0,
            "quick": {"timeout_seconds": 1.5},
            "slow": {},
        }
    )
    built = build_delivery_sinks(
        config,
        factories={name: (lambda settings: (lambda event: None)) for name in ("quick", "slow")},
    )

    bounds = {sink.name: sink.timeout_seconds for sink in built.sinks}
    assert bounds == {"quick": 1.5, "slow": 9.0}
    assert all(isinstance(sink, ConfiguredSink) for sink in built.sinks)


def test_the_built_in_sinks_are_installed_under_the_entry_point_group() -> None:
    factories, _ = discover_sink_factories()

    assert {"file", "command", "webhook", "smtp"} <= set(factories)


def test_a_third_party_sink_delivers_with_no_marketplace_change(monkeypatch) -> None:
    """The whole extension path: install, enable, receive -- no core edit."""

    received = []

    class ThirdPartyEntryPoint:
        name = "pigeon"

        def load(self):
            def build(settings):
                loft = settings["loft"]

                def sink(event):
                    received.append((loft, event.obligation_ref, event.contact))

                return sink

            return build

    monkeypatch.setattr(
        "market_delivery.discovery._iter_entry_points",
        lambda: [ThirdPartyEntryPoint()],
    )
    from market_delivery import deliver, introduction_delivery_event

    built = build_delivery_sinks(
        load_delivery_config({"enabled": ["pigeon"], "pigeon": {"loft": "4"}})
    )
    event = introduction_delivery_event(
        {
            "obligation_ref": "e" * 64,
            "revealed": True,
            "introduction": {},
            "counterparty_contact": {"pigeon": "loft 9"},
        },
        role="seller",
    )
    outcomes = deliver(built.sinks, event)

    assert received == [("4", "e" * 64, {"pigeon": "loft 9"})]
    assert outcomes[0].delivered is True
