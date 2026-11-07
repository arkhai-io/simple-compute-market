"""The service refuses a configuration stating a retired setting.

A refused start has no typed-client surface, so this runs the in-process
application's own lifespan, which runs the service's startup steps in order.
That the packaged configuration states no retired setting is a property of the
configuration loader's output, shown in ``tests/unit/test_config.py``.
The migration command reads no operational configuration, so it does not
refuse one; ``test_migration_reads_no_configuration.py`` shows that.
"""

from __future__ import annotations

import os

import pytest

from compute_provisioning_service import config as config_module
from compute_provisioning_service.config import RetiredSettingsError, settings
from compute_provisioning_service.main import app


def _configure(monkeypatch: pytest.MonkeyPatch, **environment: str) -> None:
    """Set values through the service's environment layer, reload them with
    the service's own loader, and give the result to the settings object the
    service's modules read."""
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(
        settings, "_source", config_module._load_bootstrap(os.environ).settings
    )


@pytest.mark.asyncio
async def test_the_application_refuses_the_retired_playbook_setting_before_any_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch, PROVISIONING_PLAYBOOK_PATH="/opt/vm-operations.yaml")
    # The step after the refusal exports ANSIBLE_CONFIG; its absence afterwards
    # shows the refusal came first.
    monkeypatch.delenv("ANSIBLE_CONFIG", raising=False)

    with pytest.raises(RetiredSettingsError, match="vm_playbook_path"):
        async with app.router.lifespan_context(app):
            pass

    assert "ANSIBLE_CONFIG" not in os.environ


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "environment",
    [
        {"PROVISIONING_INVENTORY_INI": ""},
        {"PROVISIONING_INVENTORY_PATH": "/opt/inventory/provisioning-hosts.ini"},
    ],
    ids=["empty inventory_ini", "inventory_path"],
)
async def test_the_application_refuses_a_retired_inventory_setting_before_any_step(
    monkeypatch: pytest.MonkeyPatch, environment: dict[str, str]
) -> None:
    (name,) = environment
    _configure(monkeypatch, **environment)
    monkeypatch.delenv("ANSIBLE_CONFIG", raising=False)

    with pytest.raises(RetiredSettingsError) as refused:
        async with app.router.lifespan_context(app):
            pass

    setting = name.removeprefix("PROVISIONING_").lower()
    assert f"{setting} (state host_definitions_path instead)" in str(refused.value)
    assert "ANSIBLE_CONFIG" not in os.environ
