"""The migration's settings: the database's location and the log level alone.

They come from the same files as the application's settings, layered the same
way, but no other key is read, so a migration runs whatever else a profile
states, and with no credential file present.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from core_registry.config import load_settings
from core_registry.settings_source import load_database_settings


@pytest.fixture
def profiles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    for name in ("DATABASE_URL", "LOG_LEVEL", "CONFIG_DIRECTORY", "ACTIVE_PROFILES"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def test_the_database_settings_follow_the_profiles(profiles: Path) -> None:
    (profiles / "config-registry.env").write_text(
        "DATABASE_URL=sqlite:////var/lib/arkhai-registry/indexer.db\nLOG_LEVEL=debug\n"
    )
    (profiles / "config-lane.env").write_text("LOG_LEVEL=warning\n")
    settings = load_database_settings(
        {"CONFIG_DIRECTORY": str(profiles), "ACTIVE_PROFILES": "registry,lane"}
    )
    assert settings.database_url == "sqlite:////var/lib/arkhai-registry/indexer.db"
    assert settings.log_level == "warning"


def test_no_other_setting_is_read(profiles: Path) -> None:
    """A setting the application would refuse to load leaves the migration's
    settings readable."""
    (profiles / "config-registry.env").write_text(
        "DATABASE_URL=sqlite:///./registry.db\n"
        "REGISTRY_AUTHORITY_CREDENTIAL_FILE=/run/secrets/absent/credential\n"
        "REGISTRY_REQUIRE_READ_API_KEY=not-a-boolean\n"
    )
    environment = {"CONFIG_DIRECTORY": str(profiles), "ACTIVE_PROFILES": "registry"}
    with pytest.raises(ValidationError):
        load_settings(environment)
    assert load_database_settings(environment).database_url == "sqlite:///./registry.db"
