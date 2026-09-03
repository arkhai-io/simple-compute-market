from __future__ import annotations

import base64
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from dynaconf import Dynaconf
from market_config import load_dynaconf
from market_identity import Ed25519Signer, Eip191Signer

from compute_provisioning_service.config import (
    Settings,
    _BOOTSTRAP_OPTIONS,
)
from compute_provisioning_service.identity import (
    IDENTITY_CREDENTIAL_ENV,
    resolve_identity_context,
)


def _credential(scheme: str, seed: bytes) -> str:
    if scheme == "ed25519":
        return base64.urlsafe_b64encode(seed).rstrip(b"=").decode()
    return seed.hex()


def _settings(service, storefront, **overrides):
    admin = (
        Ed25519Signer(b"\x13" * 32)
        if service.identity.scheme.value == "ed25519"
        else Eip191Signer(b"\x23" * 32)
    )
    values = {
        "identity.scheme": service.identity.scheme.value,
        "identity.identifier": service.identity.identifier,
        "storefront_identity.scheme": storefront.identity.scheme.value,
        "storefront_identity.identifier": storefront.identity.identifier,
        "admin_identity.scheme": admin.identity.scheme.value,
        "admin_identity.identifier": admin.identity.identifier,
        "storefront_site_id": "default",
    }
    values.update(overrides)
    return SimpleNamespace(_source=values)


@pytest.mark.parametrize(
    ("scheme", "service", "storefront", "secret"),
    (
        (
            "ed25519",
            Ed25519Signer(b"\x11" * 32),
            Ed25519Signer(b"\x12" * 32),
            b"\x11" * 32,
        ),
        (
            "eip191",
            Eip191Signer(b"\x21" * 32),
            Eip191Signer(b"\x22" * 32),
            b"\x21" * 32,
        ),
    ),
)
def test_identity_composition_supports_both_schemes_without_chain_settings(
    scheme,
    service,
    storefront,
    secret,
):
    context = resolve_identity_context(
        _settings(service, storefront),
        environ={IDENTITY_CREDENTIAL_ENV: _credential(scheme, secret)},
    )

    assert context.signer.identity == service.identity
    assert context.storefront_principal == storefront.identity
    assert context.admin_principal not in {
        context.signer.identity,
        context.storefront_principal,
    }
    assert context.storefront_site_id == "default"


@pytest.mark.parametrize(
    ("settings", "environment", "message"),
    (
        (
            SimpleNamespace(_source={}),
            {},
            "identity.scheme and identity.identifier are required",
        ),
        (
            _settings(
                Ed25519Signer(b"\x11" * 32),
                Ed25519Signer(b"\x12" * 32),
            ),
            {},
            "ARKHAI_IDENTITY_CREDENTIAL is required",
        ),
        (
            _settings(
                Ed25519Signer(b"\x11" * 32),
                Ed25519Signer(b"\x12" * 32),
                storefront_site_id="",
            ),
            {IDENTITY_CREDENTIAL_ENV: _credential("ed25519", b"\x11" * 32)},
            "storefront_site_id is required",
        ),
        (
            _settings(
                Ed25519Signer(b"\x11" * 32),
                Ed25519Signer(b"\x12" * 32),
            ),
            {IDENTITY_CREDENTIAL_ENV: _credential("ed25519", b"\x13" * 32)},
            "does not match",
        ),
        (
            _settings(
                Ed25519Signer(b"\x11" * 32),
                Ed25519Signer(b"\x12" * 32),
                **{
                    "admin_identity.scheme": "",
                    "admin_identity.identifier": "",
                },
            ),
            {IDENTITY_CREDENTIAL_ENV: _credential("ed25519", b"\x11" * 32)},
            "admin_identity.scheme and admin_identity.identifier are required",
        ),
    ),
)
def test_missing_or_mismatched_identity_configuration_fails_startup(
    settings,
    environment,
    message,
):
    with pytest.raises(RuntimeError, match=message):
        resolve_identity_context(settings, environ=environment)


def test_provisioning_bootstrap_preserves_profile_and_constructor_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "settings.toml").write_text(
        '[bootstrap_characterization]\nlayer = "settings"\n'
    )
    (tmp_path / "config.yml").write_text(
        "bootstrap_characterization:\n  layer: base\n  base_only: true\n"
    )
    (tmp_path / "config-first.yml").write_text(
        "bootstrap_characterization:\n  layer: first\n  first_only: true\n"
    )
    monkeypatch.setenv(
        "PROVISIONING_BOOTSTRAP_CHARACTERIZATION__LAYER",
        "environment",
    )

    options = replace(
        _BOOTSTRAP_OPTIONS,
        default_config_directory=tmp_path,
        settings_files=(tmp_path / "settings.toml",),
        load_dotenv=False,
    )
    result = load_dynaconf(
        options,
        config_directory=None,
        active_profiles=" first, missing ",
    )

    assert result.active_profiles == ("first", "missing")
    assert result.includes == (
        tmp_path / "config.yml",
        tmp_path / "config-first.yml",
    )
    assert result.settings.BOOTSTRAP_CHARACTERIZATION.LAYER == "environment"
    assert result.settings.BOOTSTRAP_CHARACTERIZATION.BASE_ONLY is True
    assert result.settings.BOOTSTRAP_CHARACTERIZATION.FIRST_ONLY is True
    assert options.envvar_prefix == "PROVISIONING"
    assert options.nested_separator_keyword == "envvar_separator"
    assert _BOOTSTRAP_OPTIONS.load_dotenv is True
    assert _BOOTSTRAP_OPTIONS.dotenv_files == (".env", ".env.local")
    assert options.filter_missing_includes is True


class TestBareMetalReclaimPolicy:
    def test_default_is_remove_lease_key(self):
        settings = Settings(Dynaconf(environments=False))

        assert settings.bare_metal_reclaim_policy == "remove_lease_key"

    def test_accepts_supported_policy(self):
        settings = Settings(Dynaconf(environments=False))
        settings._source.set("bare_metal_reclaim_policy", "lock_user")

        assert settings.bare_metal_reclaim_policy == "lock_user"

    def test_rejects_unknown_policy(self):
        settings = Settings(Dynaconf(environments=False))
        settings._source.set("bare_metal_reclaim_policy", "wipe_disk")

        with pytest.raises(ValueError, match="Invalid bare_metal_reclaim_policy"):
            _ = settings.bare_metal_reclaim_policy
