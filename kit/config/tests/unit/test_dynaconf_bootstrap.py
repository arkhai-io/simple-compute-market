from __future__ import annotations

from pathlib import Path

import pytest

from market_config.dynaconf_bootstrap import (
    DynaconfBootstrapOptions,
    _dynaconf_kwargs,
    load_dynaconf,
    parse_active_profiles,
    resolve_config_directory,
    resolve_include_paths,
)


def test_parse_active_profiles_trims_empties_and_preserves_order() -> None:
    assert parse_active_profiles(" local, production ,,mock ") == (
        "local",
        "production",
        "mock",
    )


def test_resolve_config_directory_preserves_explicit_empty_path() -> None:
    default = Path("/default/config")

    assert resolve_config_directory(None, default) == default
    assert resolve_config_directory("", default) == Path("")
    assert resolve_config_directory("/override", default) == Path("/override")


def test_resolve_include_paths_preserves_base_then_profile_order(tmp_path: Path) -> None:
    assert resolve_include_paths(
        config_directory=tmp_path,
        active_profiles=("first", "second"),
    ) == (
        tmp_path / "config.yml",
        tmp_path / "config-first.yml",
        tmp_path / "config-second.yml",
    )


def test_resolve_include_paths_filters_only_when_requested(tmp_path: Path) -> None:
    base = tmp_path / "config.yml"
    second = tmp_path / "config-second.yml"
    base.write_text("base: true\n")
    second.write_text("second: true\n")

    assert resolve_include_paths(
        config_directory=tmp_path,
        active_profiles=("missing", "second"),
        filter_missing=True,
    ) == (base, second)
    assert resolve_include_paths(
        config_directory=tmp_path,
        active_profiles=("missing", "second"),
        filter_missing=False,
    ) == (
        base,
        tmp_path / "config-missing.yml",
        second,
    )


def test_dynaconf_kwargs_preserve_consumer_constructor_options(tmp_path: Path) -> None:
    settings_file = tmp_path / "settings.toml"
    secrets_file = tmp_path / ".secrets.toml"
    dotenv_path = tmp_path / ".env"
    includes = (tmp_path / "config.yml", tmp_path / "config-local.yml")

    e2e_options = DynaconfBootstrapOptions(
        default_config_directory=tmp_path / "config",
        settings_files=(settings_file, secrets_file),
        envvar_prefix="ARKHAI",
        nested_separator_keyword="nested_sep",
        dotenv_path=dotenv_path,
    )
    provisioning_options = DynaconfBootstrapOptions(
        default_config_directory=tmp_path / "config",
        settings_files=(settings_file,),
        envvar_prefix="PROVISIONING",
        nested_separator_keyword="envvar_separator",
        filter_missing_includes=True,
    )

    assert _dynaconf_kwargs(e2e_options, includes) == {
        "settings_file": [str(settings_file), str(secrets_file)],
        "includes": [str(path) for path in includes],
        "envvar_prefix": "ARKHAI",
        "load_dotenv": True,
        "environments": False,
        "merge_enabled": True,
        "nested_sep": "__",
        "dotenv_path": str(dotenv_path),
    }
    assert _dynaconf_kwargs(provisioning_options, includes) == {
        "settings_file": [str(settings_file)],
        "includes": [str(path) for path in includes],
        "envvar_prefix": "PROVISIONING",
        "load_dotenv": True,
        "environments": False,
        "merge_enabled": True,
        "envvar_separator": "__",
    }


def test_load_dynaconf_applies_profile_layers_and_nested_environment_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings_file = tmp_path / "settings.toml"
    settings_file.write_text('[sample]\nvalue = "settings"\nsettings_only = true\n')
    (tmp_path / "config.toml").write_text(
        '[sample]\nvalue = "base"\nbase_only = true\n'
    )
    (tmp_path / "config-local.toml").write_text(
        '[sample]\nvalue = "profile"\nprofile_only = true\n'
    )
    monkeypatch.setenv("BOOTSTRAP_SAMPLE__VALUE", "environment")

    options = DynaconfBootstrapOptions(
        default_config_directory=tmp_path,
        settings_files=(settings_file,),
        envvar_prefix="BOOTSTRAP",
        nested_separator_keyword="nested_sep",
        base_include_name="config.toml",
        profile_include_pattern="config-{profile}.toml",
        load_dotenv=False,
    )
    result = load_dynaconf(
        options,
        config_directory=None,
        active_profiles="local",
    )

    assert result.active_profiles == ("local",)
    assert result.includes == (
        tmp_path / "config.toml",
        tmp_path / "config-local.toml",
    )
    assert result.settings.SAMPLE.VALUE == "environment"
    assert result.settings.SAMPLE.SETTINGS_ONLY is True
    assert result.settings.SAMPLE.BASE_ONLY is True
    assert result.settings.SAMPLE.PROFILE_ONLY is True
