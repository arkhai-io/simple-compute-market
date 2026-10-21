from __future__ import annotations

from importlib import metadata
from importlib.metadata import entry_points

from typer.testing import CliRunner

from arkhai_bare_metal_storefront.cli import ServeProcess, app
from arkhai_bare_metal_storefront.server import serving_port
from storefront_configuration import write_configuration


def test_console_entry_point_is_installed() -> None:
    matching = [
        entry_point
        for entry_point in entry_points(group="console_scripts")
        if entry_point.name == "bare-metal-storefront"
    ]

    assert len(matching) == 1
    assert matching[0].value == "arkhai_bare_metal_storefront.cli:app"


def test_storefront_contribution_entry_point_is_installed() -> None:
    matching = [
        entry_point
        for entry_point in entry_points(group="market.storefront_contributions")
        if entry_point.name == "bare_metal"
    ]

    assert len(matching) == 1
    assert matching[0].value == (
        "arkhai_bare_metal_storefront.contribution:"
        "BARE_METAL_STOREFRONT_CONTRIBUTION"
    )


def test_version_command_uses_distribution_metadata() -> None:
    # What the command prints is checked against the distribution metadata it
    # claims to read, not against a number spelled here that every release has
    # to remember to change.
    installed = metadata.version("arkhai-bare-metal-storefront")

    result = CliRunner().invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout == f"bare-metal-storefront version {installed}\n"


def test_serve_command_delegates_process_options() -> None:
    calls: list[dict[str, object]] = []
    process = ServeProcess(run=lambda **kwargs: calls.append(kwargs))

    result = CliRunner().invoke(
        app,
        [
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            "8123",
            "--root-path",
            "/seller/bare-metal",
        ],
        obj=process,
    )

    assert result.exit_code == 0
    assert calls == [
        {
            "host": "127.0.0.1",
            "port": 8123,
            "root_path": "/seller/bare-metal",
        }
    ]


def test_serve_leaves_the_port_to_configuration_unless_told() -> None:
    calls: list[dict[str, object]] = []
    process = ServeProcess(run=lambda **kwargs: calls.append(kwargs))

    result = CliRunner().invoke(app, ["serve"], obj=process)

    assert result.exit_code == 0
    assert calls == [{"host": "0.0.0.0", "port": None, "root_path": ""}]


def test_the_served_port_is_the_configured_one_unless_overridden(monkeypatch, tmp_path) -> None:
    write_configuration(monkeypatch, tmp_path, {"port": 9123})

    assert serving_port(None) == 9123
    assert serving_port(8123) == 8123
