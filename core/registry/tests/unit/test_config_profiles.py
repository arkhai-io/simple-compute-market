"""The registry's profile env files, layered under ACTIVE_PROFILES.

Every value is a public development fixture, never for a public network.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core_registry.config import load_settings, profile_env_files

# Anvil's well-known development account 3; never use it on a public network.
IDENTIFIER = "0x90f79bf6eb2c4f870365e785982e1f101e93b906"
AUTHORITIES = [{"account": "00000000-0000-4000-8000-0000000000d1", "origin": "https://dispute.invalid"}]


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    # The default dotenv files are read from the working directory, so each test
    # runs in an empty one; and the process environment overrides every file, so
    # none of these may leak in from the shell running the tests.
    monkeypatch.chdir(tmp_path)
    for name in (
        "REGISTRY_AUTHORITY_ID", "REGISTRY_AUTHORITY_IDENTIFIER",
        "REGISTRY_DESCRIPTOR_DISPLAY_NAME", "REGISTRY_DESCRIPTOR_OPERATOR_IDENTITY",
        "REGISTRY_DESCRIPTOR_RECOMMENDED_DISPUTE_AUTHORITIES",
        "CONFIG_DIRECTORY", "ACTIVE_PROFILES",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def profiles(tmp_path) -> Path:
    directory = tmp_path / "profiles"
    directory.mkdir()
    return directory


def _profile(directory: Path, name: str, *lines: str) -> None:
    (directory / f"config-{name}.env").write_text("\n".join(lines) + "\n")


def _selecting(directory: Path, profiles: str) -> dict[str, str]:
    return {"CONFIG_DIRECTORY": str(directory), "ACTIVE_PROFILES": profiles}


def test_two_profiles_layer_and_the_later_wins(profiles):
    _profile(profiles, "registry", "REGISTRY_AUTHORITY_ID=bare-metal-registry",
             "REGISTRY_DESCRIPTOR_DISPLAY_NAME=Local registry")
    _profile(profiles, "lane", "REGISTRY_DESCRIPTOR_DISPLAY_NAME=Lane registry")

    settings = load_settings(_selecting(profiles, "registry,lane"))

    assert settings.registry_authority_id == "bare-metal-registry"
    assert settings.registry_descriptor_display_name == "Lane registry"


def test_a_profile_overrides_the_default_files_and_dotenv_overrides_dotenv_local(
    tmp_path, profiles,
):
    (tmp_path / ".env.local").write_text(
        "REGISTRY_AUTHORITY_ID=from-env-local\n"
        "REGISTRY_DESCRIPTOR_OPERATOR_IDENTITY=from-env-local\n"
        "REGISTRY_DESCRIPTOR_DISPLAY_NAME=from-env-local\n"
    )
    (tmp_path / ".env").write_text(
        "REGISTRY_DESCRIPTOR_OPERATOR_IDENTITY=from-env\n"
        "REGISTRY_DESCRIPTOR_DISPLAY_NAME=from-env\n"
    )
    _profile(profiles, "registry", "REGISTRY_DESCRIPTOR_DISPLAY_NAME=from-profile")

    settings = load_settings(_selecting(profiles, "registry"))

    assert settings.registry_authority_id == "from-env-local"
    assert settings.registry_descriptor_operator_identity == "from-env"
    assert settings.registry_descriptor_display_name == "from-profile"


def test_the_process_environment_wins_over_every_profile(profiles, monkeypatch):
    _profile(profiles, "registry", "REGISTRY_DESCRIPTOR_DISPLAY_NAME=From registry")
    _profile(profiles, "lane", "REGISTRY_DESCRIPTOR_DISPLAY_NAME=From lane")
    monkeypatch.setenv("REGISTRY_DESCRIPTOR_DISPLAY_NAME", "From process")

    settings = load_settings(_selecting(profiles, "registry,lane"))

    assert settings.registry_descriptor_display_name == "From process"


def test_no_active_profiles_loads_the_default_files_alone(tmp_path, profiles):
    (tmp_path / ".env").write_text("REGISTRY_DESCRIPTOR_DISPLAY_NAME=from-env\n")
    _profile(profiles, "registry", "REGISTRY_AUTHORITY_ID=never-read")

    settings = load_settings({"CONFIG_DIRECTORY": str(profiles)})

    assert profile_env_files({"CONFIG_DIRECTORY": str(profiles)}) == ()
    assert settings.registry_descriptor_display_name == "from-env"
    assert settings.registry_authority_id is None


def test_the_resolver_variables_are_read_from_the_process_environment_by_default(
    profiles, monkeypatch,
):
    _profile(profiles, "registry", "REGISTRY_AUTHORITY_ID=bare-metal-registry")
    monkeypatch.setenv("CONFIG_DIRECTORY", str(profiles))
    monkeypatch.setenv("ACTIVE_PROFILES", "registry")

    assert load_settings().registry_authority_id == "bare-metal-registry"


def test_a_missing_profile_file_is_skipped(profiles):
    _profile(profiles, "registry", "REGISTRY_AUTHORITY_ID=bare-metal-registry")

    settings = load_settings(_selecting(profiles, "registry, absent ,"))

    assert settings.registry_authority_id == "bare-metal-registry"
    assert profile_env_files(_selecting(profiles, "registry, absent ,")) == (
        profiles / "config-registry.env", profiles / "config-absent.env",
    )


def test_a_json_list_is_parsed_from_a_single_quoted_line(profiles):
    _profile(
        profiles, "payments-lane",
        f"REGISTRY_DESCRIPTOR_RECOMMENDED_DISPUTE_AUTHORITIES='{json.dumps(AUTHORITIES)}'",
    )

    settings = load_settings(_selecting(profiles, "payments-lane"))

    assert settings.registry_descriptor_recommended_dispute_authorities == AUTHORITIES


def test_a_hex_identifier_is_read_as_a_string(profiles):
    _profile(profiles, "registry", f"REGISTRY_AUTHORITY_IDENTIFIER={IDENTIFIER}")

    settings = load_settings(_selecting(profiles, "registry"))

    assert settings.registry_authority_identifier == IDENTIFIER
