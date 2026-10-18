"""The bare-metal storefront's configuration loader.

Settings are read from the packaged defaults and the configuration files under
``XDG_CONFIG_HOME``, then the loader's environment override layer. Every value
below is a development fixture and must never be used on a public network.
"""

from __future__ import annotations

import pytest

from arkhai_bare_metal_storefront.config import (
    IDENTITY_CREDENTIAL_ENV,
    BareMetalConfigurationError,
    identity_credential,
    load_storefront_settings,
)
from storefront_configuration import (
    ADMIN,
    SELLER,
    SELLER_CREDENTIAL,
    publishable_configuration,
    write_configuration,
)

WALLET_KEY = "0x" + "55" * 32


def test_the_packaged_defaults_state_every_interval(monkeypatch, tmp_path):
    write_configuration(monkeypatch, tmp_path)

    settings = load_storefront_settings()

    assert settings.base_url == "http://localhost:8000"
    assert settings.db_path == "bare-metal-storefront.db"
    assert settings.negotiation_timeout_seconds == 1800
    assert settings.negotiation_watchdog_interval == 60
    assert settings.settlement_servicing_interval_seconds == 30
    assert settings.payment_reconciliation_interval == 30
    assert settings.capacity.poll_interval == 5
    assert settings.capacity.publication_interval_seconds == 30
    assert settings.capacity.placement == "fill_first"
    # No lease bound is shipped: a pool that resolves none is held, not refused.
    assert settings.pricing.default_max_duration_seconds is None
    assert settings.registry.urls == []
    assert settings.settlement == {"schema_version": 1, "priority": []}


def test_each_file_layers_over_the_one_before(monkeypatch, tmp_path):
    write_configuration(
        monkeypatch,
        tmp_path,
        {"base_url": "http://rendered:8000", "pricing": {"default_max_duration_seconds": 7200}},
        toml='base_url = "http://operator:8000"\n\n[capacity]\npoll_interval = 2\n',
    )

    settings = load_storefront_settings()

    # storefront.json, the rendered document, wins over storefront.toml ...
    assert settings.base_url == "http://rendered:8000"
    # ... and each keeps what the other does not state, over the defaults.
    assert settings.capacity.poll_interval == 2
    assert settings.capacity.publication_interval_seconds == 30
    assert settings.pricing.default_max_duration_seconds == 7200


def test_the_secret_overlay_wins_on_a_conflicting_key(monkeypatch, tmp_path):
    write_configuration(
        monkeypatch,
        tmp_path,
        {"Wallet": {"address": "0x" + "33" * 20}, "base_url": "http://rendered:8000"},
        secrets=f'base_url = "http://overlay:8000"\n\n[Wallet]\nprivate_key = "{WALLET_KEY}"\n',
    )

    settings = load_storefront_settings()

    assert settings.base_url == "http://overlay:8000"
    assert settings.wallet.address == "0x" + "33" * 20
    assert settings.wallet.private_key == WALLET_KEY
    # The key is a secret: it is never part of the settings' representation.
    assert WALLET_KEY not in repr(settings)


def test_the_environment_override_layer_applies_over_every_file(monkeypatch, tmp_path):
    write_configuration(monkeypatch, tmp_path, {"capacity": {"poll_interval": 2}})
    monkeypatch.setenv("BARE_METAL_STOREFRONT_CAPACITY__POLL_INTERVAL", "7")
    monkeypatch.setenv("BARE_METAL_STOREFRONT_NEGOTIATION_WATCHDOG_INTERVAL", "45")
    monkeypatch.setenv(
        "BARE_METAL_STOREFRONT_IDENTITY__PRINCIPAL__IDENTIFIER",
        f"@str {SELLER.identity.identifier}",
    )
    monkeypatch.setenv("BARE_METAL_STOREFRONT_IDENTITY__PRINCIPAL__SCHEME", "eip191")

    settings = load_storefront_settings()

    assert settings.capacity.poll_interval == 7
    assert settings.negotiation_watchdog_interval == 45
    assert settings.identity.principal == SELLER.identity


def test_the_signing_credential_is_never_a_setting(monkeypatch, tmp_path):
    write_configuration(monkeypatch, tmp_path, publishable_configuration(tmp_path / "db"))
    monkeypatch.setenv(IDENTITY_CREDENTIAL_ENV, SELLER_CREDENTIAL)

    settings = load_storefront_settings()

    assert SELLER_CREDENTIAL not in settings.model_dump_json()
    assert SELLER_CREDENTIAL not in repr(settings)
    # The composition root reads it apart from settings and hands it to the signer.
    assert identity_credential() == SELLER_CREDENTIAL
    assert settings.signer(identity_credential()).identity == SELLER.identity


def test_a_missing_credential_is_named(monkeypatch):
    monkeypatch.delenv(IDENTITY_CREDENTIAL_ENV, raising=False)

    with pytest.raises(BareMetalConfigurationError, match=IDENTITY_CREDENTIAL_ENV):
        identity_credential()


def test_section_and_key_names_are_read_in_any_case(monkeypatch, tmp_path):
    write_configuration(
        monkeypatch,
        tmp_path,
        {"Capacity": {"Poll_Interval": 3, "Sites": {"Site-A": "http://a.test"}}},
    )

    settings = load_storefront_settings()

    assert settings.capacity.poll_interval == 3
    # A site ID is a name, not a key, and keeps its spelling.
    assert settings.capacity.sites == {"Site-A": "http://a.test"}


@pytest.mark.parametrize(
    ("document", "named"),
    [
        pytest.param({"capacity": {"poll_intervall": 3}}, "capacity.poll_intervall",
                     id="an unknown key in a typed section"),
        pytest.param({"capacity": {"poll_interval": 0}}, "capacity.poll_interval",
                     id="a zero interval"),
        pytest.param({"negotiation_watchdog_interval": True},
                     "negotiation_watchdog_interval", id="a boolean interval"),
        pytest.param({"pricing": {"default_max_duration_seconds": "86400"}},
                     "pricing.default_max_duration_seconds", id="a bound as text"),
        pytest.param({"Identity": {"principal": {"scheme": "eip191", "identifier": "x"}}},
                     "identity.principal", id="a malformed principal"),
    ],
)
def test_a_setting_that_cannot_be_read_is_refused_by_key(
    monkeypatch, tmp_path, document, named
):
    write_configuration(monkeypatch, tmp_path, document)

    with pytest.raises(BareMetalConfigurationError, match=named):
        load_storefront_settings()


def test_administrators_are_every_subjects_principals(monkeypatch, tmp_path):
    document = publishable_configuration(tmp_path / "db")
    document["Identity"]["administrators"]["second"] = {
        "principals": [SELLER.identity.model_dump(mode="json")]
    }
    write_configuration(monkeypatch, tmp_path, document)

    principals = load_storefront_settings().administrator_principals()

    assert principals.identities == (ADMIN.identity, SELLER.identity)
