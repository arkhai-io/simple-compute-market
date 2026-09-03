from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest
from market_config import load_dynaconf

from src import settings as settings_module


def test_e2e_bootstrap_preserves_profile_secret_and_dotenv_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings_file = tmp_path / "settings.toml"
    secrets_file = tmp_path / ".secrets.toml"
    dotenv_path = tmp_path / ".env"
    settings_file.write_text(
        '[bootstrap_characterization]\nlayer = "settings"\nsettings_only = "yes"\n'
    )
    secrets_file.write_text(
        '[bootstrap_characterization]\nlayer = "secret"\nsecret_only = "yes"\n'
    )
    (tmp_path / "config.yml").write_text(
        "bootstrap_characterization:\n  layer: base\n  base_only: true\n"
    )
    (tmp_path / "config-first.yml").write_text(
        "bootstrap_characterization:\n  layer: first\n  first_only: true\n"
    )
    dotenv_key = "ARKHAI_BOOTSTRAP_CHARACTERIZATION__DOTENV_ONLY"
    dotenv_path.write_text(f"{dotenv_key}=from-dotenv\n")
    monkeypatch.delenv(dotenv_key, raising=False)
    monkeypatch.setenv(
        "ARKHAI_BOOTSTRAP_CHARACTERIZATION__LAYER",
        "environment",
    )

    options = replace(
        settings_module._BOOTSTRAP_OPTIONS,
        default_config_directory=tmp_path,
        settings_files=(settings_file, secrets_file),
        dotenv_path=dotenv_path,
    )
    result = load_dynaconf(
        options,
        config_directory=None,
        active_profiles=" first, missing ",
    )
    dotenv_only = result.settings.BOOTSTRAP_CHARACTERIZATION.DOTENV_ONLY
    os.environ.pop(dotenv_key, None)

    assert result.active_profiles == ("first", "missing")
    assert result.includes == (
        tmp_path / "config.yml",
        tmp_path / "config-first.yml",
        tmp_path / "config-missing.yml",
    )
    assert result.settings.BOOTSTRAP_CHARACTERIZATION.LAYER == "environment"
    assert result.settings.BOOTSTRAP_CHARACTERIZATION.SETTINGS_ONLY == "yes"
    assert result.settings.BOOTSTRAP_CHARACTERIZATION.SECRET_ONLY == "yes"
    assert result.settings.BOOTSTRAP_CHARACTERIZATION.BASE_ONLY is True
    assert result.settings.BOOTSTRAP_CHARACTERIZATION.FIRST_ONLY is True
    assert dotenv_only == "from-dotenv"
    assert options.envvar_prefix == "ARKHAI"
    assert options.nested_separator_keyword == "nested_sep"
    assert options.filter_missing_includes is False


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
