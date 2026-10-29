from __future__ import annotations

import base64
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from dynaconf import Dynaconf
from market_identity import Ed25519Signer, Eip191Signer

from compute_provisioning_service import config as config_module
from compute_provisioning_service.config import RetiredSettingsError, Settings
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


def test_provisioning_bootstrap_uses_resolver_environment_and_file_precedence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings_file = tmp_path / "settings.toml"
    settings_file.write_text(
        "[bootstrap_characterization]\n"
        'settings_vs_base = "settings"\n'
        'settings_only = "settings"\n'
    )
    (tmp_path / "config.yml").write_text(
        "bootstrap_characterization:\n"
        "  settings_vs_base: base\n"
        "  base_vs_first: base\n"
        "  base_only: base\n"
    )
    (tmp_path / "config-first.yml").write_text(
        "bootstrap_characterization:\n"
        "  base_vs_first: first\n"
        "  first_vs_second: first\n"
        "  first_only: first\n"
    )
    (tmp_path / "config-second.yml").write_text(
        "bootstrap_characterization:\n"
        "  first_vs_second: second\n"
        "  second_only: second\n"
    )

    options = replace(
        config_module._BOOTSTRAP_OPTIONS,
        default_config_directory=tmp_path / "unused-default",
        settings_files=(settings_file,),
        load_dotenv=False,
    )
    monkeypatch.setattr(config_module, "_BOOTSTRAP_OPTIONS", options)

    result = config_module._load_bootstrap(
        {
            "CONFIG_DIRECTORY": str(tmp_path),
            "ACTIVE_PROFILES": " first, second, missing ",
        }
    )

    assert result.config_directory == tmp_path
    assert result.active_profiles == ("first", "second", "missing")
    assert result.includes == (
        tmp_path / "config.yml",
        tmp_path / "config-first.yml",
        tmp_path / "config-second.yml",
    )
    values = result.settings.BOOTSTRAP_CHARACTERIZATION
    assert values.SETTINGS_VS_BASE == "base"
    assert values.BASE_VS_FIRST == "first"
    assert values.FIRST_VS_SECOND == "second"
    assert values.SETTINGS_ONLY == "settings"
    assert values.BASE_ONLY == "base"
    assert values.FIRST_ONLY == "first"
    assert values.SECOND_ONLY == "second"
    assert options.envvar_prefix == "PROVISIONING"
    assert options.nested_separator_keyword == "envvar_separator"
    assert options.filter_missing_includes is True


def test_provisioning_bootstrap_dotenv_uses_environment_layer_without_dotenv_local(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings_file = tmp_path / "settings.toml"
    settings_file.write_text(
        "[bootstrap_characterization]\n"
        'dotenv_vs_file = "settings"\n'
        'environment_vs_dotenv = "settings"\n'
        'local_only = "settings"\n'
    )
    dotenv_key = "PROVISIONING_BOOTSTRAP_CHARACTERIZATION__DOTENV_VS_FILE"
    environment_key = (
        "PROVISIONING_BOOTSTRAP_CHARACTERIZATION__ENVIRONMENT_VS_DOTENV"
    )
    local_key = "PROVISIONING_BOOTSTRAP_CHARACTERIZATION__LOCAL_ONLY"
    (tmp_path / ".env").write_text(
        f"{dotenv_key}=dotenv\n"
        f"{environment_key}=dotenv\n"
    )
    (tmp_path / ".env.local").write_text(f"{local_key}=dotenv-local\n")
    monkeypatch.delenv(dotenv_key, raising=False)
    monkeypatch.delenv(local_key, raising=False)
    monkeypatch.setenv(environment_key, "environment")
    monkeypatch.chdir(tmp_path)
    # Dynaconf's discovery returns the first `.env` found walking up from the
    # invoked script before it tries the working directory, so a `.env` in any
    # ancestor of the test runner would shadow this one. Rooting discovery here
    # keeps the service's discovery path while excluding the runner's
    # surroundings.
    monkeypatch.setenv("ROOT_PATH_FOR_DYNACONF", str(tmp_path))

    options = replace(
        config_module._BOOTSTRAP_OPTIONS,
        default_config_directory=tmp_path,
        settings_files=(settings_file,),
    )
    monkeypatch.setattr(config_module, "_BOOTSTRAP_OPTIONS", options)

    result = config_module._load_bootstrap(
        {"CONFIG_DIRECTORY": str(tmp_path), "ACTIVE_PROFILES": ""}
    )

    values = result.settings.BOOTSTRAP_CHARACTERIZATION
    assert values.DOTENV_VS_FILE == "dotenv"
    assert values.ENVIRONMENT_VS_DOTENV == "environment"
    assert values.LOCAL_ONLY == "settings"
    assert options.load_dotenv is True


def _layered_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    profile: str = "",
    environment: dict[str, str] | None = None,
) -> Settings:
    """The service's own settings file under one profile, loaded as the service
    loads it, with no dotenv file in reach and no playbook setting in the
    process environment beyond ``environment``, and no pool seed path there."""
    monkeypatch.delenv("PROVISIONING_VM_PLAYBOOK_PATH", raising=False)
    monkeypatch.delenv("PROVISIONING_PLAYBOOK_PATH", raising=False)
    monkeypatch.delenv("PROVISIONING_POOL_SEED_PATH", raising=False)
    for name, value in (environment or {}).items():
        monkeypatch.setenv(name, value)
    (tmp_path / "config-first.yml").write_text(profile)
    monkeypatch.chdir(tmp_path)
    options = replace(
        config_module._BOOTSTRAP_OPTIONS,
        default_config_directory=tmp_path,
        load_dotenv=False,
    )
    monkeypatch.setattr(config_module, "_BOOTSTRAP_OPTIONS", options)
    result = config_module._load_bootstrap(
        {"CONFIG_DIRECTORY": str(tmp_path), "ACTIVE_PROFILES": "first"}
    )
    return Settings(result.settings)


def test_the_vm_playbook_resolves_from_its_domain_named_setting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _layered_settings(
        tmp_path, monkeypatch, profile='vm_playbook_path: "playbooks/vm.yaml"\n'
    )

    assert settings.resolved_vm_playbook_path == (tmp_path / "playbooks/vm.yaml").resolve()
    assert settings.stated_retired_settings() == ()
    settings.refuse_retired_settings()


def test_the_packaged_defaults_state_no_retired_setting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _layered_settings(tmp_path, monkeypatch)

    assert settings.resolved_vm_playbook_path == Path(
        "/opt/domains/vms/provisioning/iac/ansible/playbooks/single-tenant/vm-operations.yaml"
    )
    settings.refuse_retired_settings()


_SETTINGS_DIR = Path(config_module.__file__).parent


def test_the_packaged_pool_seed_document_is_the_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _layered_settings(tmp_path, monkeypatch)

    assert settings.resolved_pool_seed_path == (_SETTINGS_DIR / "seed/pools.yaml").resolve()
    assert settings.resolved_pool_seed_path.is_file()


def test_an_absolute_pool_seed_path_is_taken_as_stated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _layered_settings(
        tmp_path, monkeypatch, profile=f'pool_seed_path: "{tmp_path / "pools.yaml"}"\n'
    )

    assert settings.resolved_pool_seed_path == (tmp_path / "pools.yaml").resolve()


def test_a_relative_pool_seed_path_resolves_against_the_settings_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Not against the working directory, which the profile loader moved to."""
    settings = _layered_settings(
        tmp_path, monkeypatch, profile='pool_seed_path: "seed/other.yaml"\n'
    )

    assert settings.resolved_pool_seed_path == (_SETTINGS_DIR / "seed/other.yaml").resolve()


@pytest.mark.parametrize("value", ['""', '"  "'])
def test_an_empty_pool_seed_path_disables_seeding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    settings = _layered_settings(tmp_path, monkeypatch, profile=f"pool_seed_path: {value}\n")

    assert settings.resolved_pool_seed_path is None


def test_the_retired_playbook_setting_in_a_profile_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _layered_settings(
        tmp_path, monkeypatch, profile='playbook_path: "/opt/vm.yaml"\n'
    )

    assert settings.stated_retired_settings() == ("playbook_path",)
    with pytest.raises(
        RetiredSettingsError,
        match=r"playbook_path \(state vm_playbook_path instead\)",
    ):
        settings.refuse_retired_settings()


def test_the_retired_playbook_setting_in_the_environment_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _layered_settings(
        tmp_path,
        monkeypatch,
        environment={"PROVISIONING_PLAYBOOK_PATH": "/opt/vm.yaml"},
    )

    with pytest.raises(RetiredSettingsError, match="vm_playbook_path"):
        settings.refuse_retired_settings()
