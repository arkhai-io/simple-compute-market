"""Configuration and sink construction fail early, and never at reveal time."""

from __future__ import annotations

import pytest
from market_delivery import (
    ConfiguredSink,
    DeclaredSink,
    DeliveryConfigurationError,
    SinkSettings,
    build_delivery_sinks,
    discover_sink_settings_models,
    load_delivery_config,
    validate_delivery_origins,
)
from market_delivery.builtin.smtp_sink import SmtpSinkSettings
from market_delivery.builtin.webhook_sink import WebhookSinkSettings
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


def _recording_factory(received: list):
    def factory(settings, **_):
        return lambda event: received.append((dict(settings), event))

    return factory


def test_two_instances_of_one_sink_each_keep_their_own_settings() -> None:
    config = load_delivery_config(
        {
            "enabled": ["west-hook", "east-hook"],
            "west-hook": {"sink": "webhook", "url": "https://west.invalid"},
            "east-hook": {"sink": "webhook", "url": "https://east.invalid"},
        }
    )
    built: list = []
    sinks = build_delivery_sinks(
        config,
        factories={"webhook": lambda settings: built.append(dict(settings)) or (lambda e: None)},
    )
    assert [sink.name for sink in sinks.sinks] == ["west-hook", "east-hook"]
    assert built == [{"url": "https://west.invalid"}, {"url": "https://east.invalid"}]


def test_a_configuration_written_before_instances_keeps_its_meaning() -> None:
    config = load_delivery_config(
        {"enabled": ["file"], "file": {"path": "/tmp/introductions.jsonl"}}
    )
    assert config.sink_for("file") == "file"
    received: list = []
    sinks = build_delivery_sinks(config, factories={"file": _recording_factory(received)})
    assert [sink.name for sink in sinks.sinks] == ["file"]


def test_an_instance_named_for_one_sink_stating_another_is_refused() -> None:
    config = load_delivery_config(
        {"enabled": ["webhook"], "webhook": {"sink": "file", "path": "/tmp/x"}}
    )
    with pytest.raises(DeliveryConfigurationError, match="named for the 'webhook' sink"):
        build_delivery_sinks(
            config,
            factories={"webhook": _recording_factory([]), "file": _recording_factory([])},
        )


def test_an_instance_may_not_take_a_section_settings_name() -> None:
    with pytest.raises(DeliveryConfigurationError, match="section settings"):
        load_delivery_config({"enabled": ["origins"]}, role="seller")


def _routed(**origins) -> dict:
    return {
        "enabled": ["west-hook", "east-hook", "audit"],
        "west-hook": {"sink": "webhook", "url": "https://west.invalid"},
        "east-hook": {"sink": "webhook", "url": "https://east.invalid"},
        "audit": {"sink": "file", "path": "/tmp/audit.jsonl"},
        "origins": origins
        or {"dc-west": ["west-hook", "audit"], "dc-east": ["east-hook", "audit"]},
    }


def test_a_seller_routing_table_is_read() -> None:
    config = load_delivery_config(_routed(), role="seller")
    assert config.origins == {
        "dc-west": ("west-hook", "audit"),
        "dc-east": ("east-hook", "audit"),
    }


def test_a_buyer_may_not_route() -> None:
    with pytest.raises(DeliveryConfigurationError, match="no origin"):
        load_delivery_config(_routed())


def test_routing_an_instance_that_is_not_enabled_is_refused() -> None:
    with pytest.raises(DeliveryConfigurationError, match="not enabled: west-hok"):
        load_delivery_config(
            _routed(**{"dc-west": ["west-hok", "audit"], "dc-east": ["east-hook"]}),
            role="seller",
        )


def test_an_enabled_instance_routed_for_no_origin_is_refused() -> None:
    with pytest.raises(DeliveryConfigurationError, match="enabled instances: audit"):
        load_delivery_config(
            _routed(**{"dc-west": ["west-hook"], "dc-east": ["east-hook"]}),
            role="seller",
        )


def test_routing_an_unknown_origin_is_refused() -> None:
    config = load_delivery_config(_routed(), role="seller")
    validate_delivery_origins(config, {"dc-west", "dc-east"})
    with pytest.raises(DeliveryConfigurationError, match="dc-east"):
        validate_delivery_origins(config, {"dc-west"})


def test_several_origins_without_routing_are_refused_and_one_is_not() -> None:
    config = load_delivery_config(
        {"enabled": ["file"], "file": {"path": "/tmp/x"}}, role="seller"
    )
    validate_delivery_origins(config, {"default"})
    with pytest.raises(DeliveryConfigurationError, match="dc-east, dc-west"):
        validate_delivery_origins(config, {"dc-west", "dc-east"})
    # Nothing enabled routes nothing, whatever the origins.
    validate_delivery_origins(load_delivery_config(None), {"dc-west", "dc-east"})


def test_signing_requires_a_signer() -> None:
    config = load_delivery_config(
        {"enabled": ["hook"], "hook": {"sink": "webhook", "url": "https://x.invalid", "sign": True}}
    )
    with pytest.raises(DeliveryConfigurationError, match="no marketplace signer"):
        build_delivery_sinks(config, factories={"webhook": _recording_factory([])})


def test_installed_built_in_sinks_declare_their_settings_models() -> None:

    models, warnings = discover_sink_settings_models()

    assert warnings == ()
    assert {"command", "file", "smtp", "webhook"} <= set(models)
    assert models["webhook"] is WebhookSinkSettings
    assert models["smtp"] is SmtpSinkSettings


def test_a_plain_factory_plugin_installs_and_declares_nothing(monkeypatch) -> None:

    class Settings(SinkSettings):
        target: str

    class Declared:
        name = "declared"

        def load(self):
            return DeclaredSink(lambda settings: (lambda event: None), Settings)

    class Plain:
        name = "plain"

        def load(self):
            return lambda settings: (lambda event: None)

    monkeypatch.setattr(
        "market_delivery.discovery._iter_entry_points", lambda: [Declared(), Plain()]
    )

    factories, _ = discover_sink_factories()
    models, _ = discover_sink_settings_models()
    assert set(factories) == {"declared", "plain"}
    assert models == {"declared": Settings}


def test_a_declared_sink_builds_like_its_factory() -> None:

    built = []

    class Settings(SinkSettings):
        target: str

    def build(settings, **kwargs):
        built.append((dict(settings), kwargs))
        return lambda event: None

    DeclaredSink(build, Settings)({"target": "x"}, signer="s")
    assert built == [({"target": "x"}, {"signer": "s"})]
