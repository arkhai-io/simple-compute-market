"""Shared Dynaconf bootstrap mechanics for role composition roots."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from dynaconf import Dynaconf

NestedSeparatorKeyword = Literal["envvar_separator", "nested_sep"]


@dataclass(frozen=True)
class DynaconfBootstrapOptions:
    """Consumer policy needed to construct a Dynaconf settings object."""

    default_config_directory: Path
    settings_files: tuple[Path, ...]
    envvar_prefix: str
    nested_separator_keyword: NestedSeparatorKeyword
    base_include_name: str = "config.yml"
    profile_include_pattern: str = "config-{profile}.yml"
    nested_separator: str = "__"
    load_dotenv: bool = True
    dotenv_path: Path | None = None
    filter_missing_includes: bool = False
    environments: bool = False
    merge_enabled: bool = True


@dataclass(frozen=True)
class DynaconfBootstrapResult:
    """Constructed settings plus the resolved profile inputs used to build it."""

    settings: Dynaconf
    config_directory: Path
    active_profiles: tuple[str, ...]
    includes: tuple[Path, ...]


def parse_active_profiles(raw_profiles: str) -> tuple[str, ...]:
    """Parse a comma-separated profile selector while preserving input order."""

    return tuple(
        profile.strip() for profile in raw_profiles.split(",") if profile.strip()
    )


def resolve_config_directory(
    configured_directory: str | Path | None,
    default_directory: Path,
) -> Path:
    """Resolve the config directory without changing explicit empty-path semantics."""

    if configured_directory is None:
        return default_directory
    return Path(configured_directory)


def resolve_include_paths(
    *,
    config_directory: Path,
    active_profiles: tuple[str, ...],
    base_include_name: str = "config.yml",
    profile_include_pattern: str = "config-{profile}.yml",
    filter_missing: bool = False,
) -> tuple[Path, ...]:
    """Build base-then-profile include paths, optionally removing missing files."""

    candidates = (config_directory / base_include_name,) + tuple(
        config_directory / profile_include_pattern.format(profile=profile)
        for profile in active_profiles
    )
    if filter_missing:
        return tuple(path for path in candidates if path.exists())
    return candidates


def _dynaconf_kwargs(
    options: DynaconfBootstrapOptions,
    includes: tuple[Path, ...],
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "settings_file": [str(path) for path in options.settings_files],
        "includes": [str(path) for path in includes],
        "envvar_prefix": options.envvar_prefix,
        "load_dotenv": options.load_dotenv,
        "environments": options.environments,
        "merge_enabled": options.merge_enabled,
        options.nested_separator_keyword: options.nested_separator,
    }
    if options.dotenv_path is not None:
        kwargs["dotenv_path"] = str(options.dotenv_path)
    return kwargs


def load_dynaconf(
    options: DynaconfBootstrapOptions,
    *,
    config_directory: str | Path | None,
    active_profiles: str,
) -> DynaconfBootstrapResult:
    """Resolve profile inputs and construct Dynaconf from explicit consumer policy."""

    resolved_directory = resolve_config_directory(
        config_directory,
        options.default_config_directory,
    )
    resolved_profiles = parse_active_profiles(active_profiles)
    includes = resolve_include_paths(
        config_directory=resolved_directory,
        active_profiles=resolved_profiles,
        base_include_name=options.base_include_name,
        profile_include_pattern=options.profile_include_pattern,
        filter_missing=options.filter_missing_includes,
    )
    settings = Dynaconf(**_dynaconf_kwargs(options, includes))
    return DynaconfBootstrapResult(
        settings=settings,
        config_directory=resolved_directory,
        active_profiles=resolved_profiles,
        includes=includes,
    )
