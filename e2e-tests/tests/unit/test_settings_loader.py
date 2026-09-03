from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from src import settings as settings_module


def test_e2e_bootstrap_uses_resolver_environment_and_file_precedence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings_file = tmp_path / "settings.toml"
    secrets_file = tmp_path / ".secrets.toml"
    settings_file.write_text(
        "[bootstrap_characterization]\n"
        'settings_vs_secrets = "settings"\n'
        'settings_only = "settings"\n'
    )
    secrets_file.write_text(
        "[bootstrap_characterization]\n"
        'settings_vs_secrets = "secret"\n'
        'secrets_vs_base = "secret"\n'
        'secret_only = "secret"\n'
    )
    (tmp_path / "config.yml").write_text(
        "bootstrap_characterization:\n"
        "  secrets_vs_base: base\n"
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
        settings_module._BOOTSTRAP_OPTIONS,
        default_config_directory=tmp_path / "unused-default",
        settings_files=(settings_file, secrets_file),
        load_dotenv=False,
    )
    monkeypatch.setattr(settings_module, "_BOOTSTRAP_OPTIONS", options)

    result = settings_module._load_bootstrap(
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
        tmp_path / "config-missing.yml",
    )
    values = result.settings.BOOTSTRAP_CHARACTERIZATION
    assert values.SETTINGS_VS_SECRETS == "secret"
    assert values.SECRETS_VS_BASE == "base"
    assert values.BASE_VS_FIRST == "first"
    assert values.FIRST_VS_SECOND == "second"
    assert values.SETTINGS_ONLY == "settings"
    assert values.SECRET_ONLY == "secret"
    assert values.BASE_ONLY == "base"
    assert values.FIRST_ONLY == "first"
    assert values.SECOND_ONLY == "second"
    assert options.envvar_prefix == "ARKHAI"
    assert options.nested_separator_keyword == "nested_sep"
    assert options.filter_missing_includes is False


def test_e2e_bootstrap_dotenv_participates_at_environment_precedence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings_file = tmp_path / "settings.toml"
    secrets_file = tmp_path / ".secrets.toml"
    dotenv_path = tmp_path / ".env"
    settings_file.write_text(
        "[bootstrap_characterization]\n"
        'dotenv_vs_profile = "settings"\n'
        'environment_vs_dotenv = "settings"\n'
    )
    secrets_file.write_text("[bootstrap_characterization]\nsecret_only = true\n")
    (tmp_path / "config.yml").write_text(
        "bootstrap_characterization:\n  dotenv_vs_profile: base\n"
    )
    (tmp_path / "config-local.yml").write_text(
        "bootstrap_characterization:\n  dotenv_vs_profile: profile\n"
    )
    dotenv_key = "ARKHAI_BOOTSTRAP_CHARACTERIZATION__DOTENV_VS_PROFILE"
    environment_key = "ARKHAI_BOOTSTRAP_CHARACTERIZATION__ENVIRONMENT_VS_DOTENV"
    dotenv_path.write_text(
        f"{dotenv_key}=dotenv\n"
        f"{environment_key}=dotenv\n"
    )
    monkeypatch.delenv(dotenv_key, raising=False)
    monkeypatch.setenv(environment_key, "environment")

    options = replace(
        settings_module._BOOTSTRAP_OPTIONS,
        default_config_directory=tmp_path,
        settings_files=(settings_file, secrets_file),
        dotenv_path=dotenv_path,
    )
    monkeypatch.setattr(settings_module, "_BOOTSTRAP_OPTIONS", options)

    result = settings_module._load_bootstrap(
        {"CONFIG_DIRECTORY": str(tmp_path), "ACTIVE_PROFILES": "local"}
    )

    values = result.settings.BOOTSTRAP_CHARACTERIZATION
    assert values.DOTENV_VS_PROFILE == "dotenv"
    assert values.ENVIRONMENT_VS_DOTENV == "environment"


def test_e2e_profile_helpers_reflect_shared_bootstrap_result() -> None:
    assert settings_module.active_profiles() == list(
        settings_module._bootstrap.active_profiles
    )
    assert (
        settings_module.config_directory()
        == settings_module._bootstrap.config_directory
    )
    assert settings_module._includes == [
        str(path) for path in settings_module._bootstrap.includes
    ]
