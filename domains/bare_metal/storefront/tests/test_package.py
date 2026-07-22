from __future__ import annotations

from importlib.metadata import entry_points

from typer.testing import CliRunner

from arkhai_bare_metal_storefront.cli import app


def test_console_entry_point_is_installed() -> None:
    matching = [
        entry_point
        for entry_point in entry_points(group="console_scripts")
        if entry_point.name == "bare-metal-storefront"
    ]

    assert len(matching) == 1
    assert matching[0].value == "arkhai_bare_metal_storefront.cli:app"


def test_version_command_uses_distribution_metadata() -> None:
    result = CliRunner().invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout == "bare-metal-storefront version 0.2.0\n"
