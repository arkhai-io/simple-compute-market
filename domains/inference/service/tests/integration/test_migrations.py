"""The inference service's migration command and its startup check, over the family authority's chain.

The chain and its refusals are the authority library's and are tested there.
Here: the installed command is this root's, it reads this service's settings
without its signing credential, and the composition refuses a database the
command has not migrated.

External boundary: file-backed SQLite in a temp directory; the command runs
through its entry point with the service's own settings loader.
"""

from __future__ import annotations


import importlib
import sqlite3
from collections.abc import Callable
from importlib.metadata import entry_points
from pathlib import Path

import pytest
from arkhai_api_authority import IncompatibleDatabase, authority_chain

from inference_service import migrate as migrate_command
from inference_service.migrate import CHAIN

from tests.integration.signed_service import unload_service_modules
from market_schema_migrations import Floor

COMMAND = "inference-service-migrate"


def _recorded(path: Path) -> list[str]:
    connection = sqlite3.connect(path)
    try:
        return [row[0] for row in connection.execute("SELECT id FROM schema_migrations")]
    finally:
        connection.close()


@pytest.fixture
def command(monkeypatch) -> Callable[..., int]:
    """Run ``inference-service-migrate`` with ``configuration`` in the service's environment layer."""

    def run(database: Path, *arguments: str, **configuration: str) -> int:
        monkeypatch.setenv("INFERENCE_DATABASE_URL", f"sqlite:///{database}")
        for name, value in configuration.items():
            monkeypatch.setenv(f"INFERENCE_{name.upper()}", value)
        try:
            migrate_command.main(list(arguments))
        except SystemExit as exit_:
            return int(exit_.code or 0)
        return 0

    return run


def test_the_chain_is_the_authoritys_named_for_this_service():
    assert CHAIN == authority_chain(
        service="the inference service", command=COMMAND, floor=Floor("0.0.0")
    )


def test_the_console_script_is_the_command():
    """The installed ``inference-service-migrate`` runs this entry point."""
    (script,) = entry_points(group="console_scripts", name=COMMAND)
    assert script.load() is migrate_command.main


def test_check_passes_only_once_the_command_has_migrated(tmp_path, command):
    path = tmp_path / "inference.db"

    assert command(path, "--check") == 1
    assert not path.exists()
    assert command(path) == 0
    assert command(path) == 0
    assert command(path, "--check") == 0
    assert sorted(_recorded(path)) == sorted(CHAIN.ids)


def test_the_command_runs_without_the_signing_credential(tmp_path, command):
    path = tmp_path / "inference.db"

    assert command(path, site_signing_key_file=str(tmp_path / "not-mounted")) == 0

    assert sorted(_recorded(path)) == sorted(CHAIN.ids)


def test_the_service_refuses_to_start_on_a_database_it_has_not_migrated(tmp_path, monkeypatch):
    """The composition checks the database before building anything, and
    leaves no file where none was migrated."""
    database = tmp_path / "inference.db"
    (tmp_path / "config.yml").write_text("")
    monkeypatch.setenv("CONFIG_DIRECTORY", str(tmp_path))
    monkeypatch.setenv("INFERENCE_DATABASE_URL", f"sqlite:///{database}")
    unload_service_modules()
    try:
        container = importlib.import_module("inference_service.container")
        with pytest.raises(IncompatibleDatabase) as refused:
            container.init()
    finally:
        unload_service_modules()

    assert f"`{COMMAND}`" in str(refused.value)
    assert container.resolved_keys_service is None
    assert not database.exists()
