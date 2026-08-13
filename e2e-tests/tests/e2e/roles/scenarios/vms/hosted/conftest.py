from __future__ import annotations

import importlib
import os
from pathlib import Path
from typing import Any

import pytest

from .boundaries import assert_wallet_free_config, hosted_selection_requested
from .control import HostedControlPrerequisiteError, ReleasedControlCli
from .driver import HostedScenarioDriver
from .funding import PrivateFundingDriver
from .recovery import HermeticRecoveryDriver
from .state import DealState

_HOSTED_MARKERS = frozenset({"e2e_hosted_settlement", "e2e_hosted_settlement_eas"})


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    hosted = [
        item
        for item in items
        if any(item.get_closest_marker(marker) is not None for marker in _HOSTED_MARKERS)
    ]
    selected = hosted_selection_requested(
        invocation_args=tuple(str(value) for value in config.invocation_params.args),
        marker_expression=str(config.option.markexpr or ""),
        environment_enabled=os.environ.get("ARKHAI_RUN_HOSTED_E2E") == "1",
    )
    if selected:
        return
    if hosted:
        config.hook.pytest_deselected(items=hosted)
        items[:] = [item for item in items if item not in hosted]


@pytest.fixture(scope="module", autouse=True)
def _ensure_provisioning_host_registered():
    yield


@pytest.fixture(scope="module", autouse=True)
def ensure_storefront_resumed():
    yield


@pytest.fixture(scope="module", autouse=True)
def reap_buyer_settle_subprocess():
    yield


@pytest.fixture(scope="module", autouse=True)
def release_reserved_resources():
    yield


@pytest.fixture(scope="function")
def deal_state() -> DealState:
    return DealState()


@pytest.fixture(scope="session")
def private_control() -> ReleasedControlCli:
    try:
        control = ReleasedControlCli.from_environment()
        control.verify_version()
    except HostedControlPrerequisiteError as exc:
        pytest.fail(str(exc), pytrace=False)
    return control


@pytest.fixture(scope="session")
def hosted_buyer_config() -> Path:
    name = "HOSTED_SETTLEMENT_E2E_BUYER_CONFIG"
    raw = os.environ.get(name, "").strip()
    if not raw:
        pytest.fail(
            f"selected hosted E2E scenario is missing prerequisite: {name}",
            pytrace=False,
        )
    path = Path(raw)
    if not path.is_file():
        pytest.fail(
            f"selected hosted E2E scenario requires existing {name}: {path}",
            pytrace=False,
        )
    try:
        assert_wallet_free_config(path)
    except AssertionError as exc:
        pytest.fail(str(exc), pytrace=False)
    return path


def _load_factory(name: str) -> Any:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.fail(
            f"selected hosted E2E scenario is missing prerequisite: {name}",
            pytrace=False,
        )
    module_name, separator, attribute = value.partition(":")
    if not separator or not module_name or not attribute:
        pytest.fail(f"{name} must be a module:callable reference", pytrace=False)
    try:
        factory = getattr(importlib.import_module(module_name), attribute)
    except (ImportError, AttributeError) as exc:
        pytest.fail(f"cannot load {name}={value!r}: {exc}", pytrace=False)
    if not callable(factory):
        pytest.fail(f"{name}={value!r} is not callable", pytrace=False)
    return factory


@pytest.fixture(scope="function")
def hosted_ports(hosted_buyer_config: Path) -> Any:
    from .network import create_hosted_ports

    return create_hosted_ports(buyer_config=hosted_buyer_config)


@pytest.fixture(scope="function")
def hosted_scenario_driver(
    hosted_ports: Any,
    private_control: ReleasedControlCli,
) -> HostedScenarioDriver:
    funding = PrivateFundingDriver(private_control)
    return HostedScenarioDriver(
        marketplace=hosted_ports.marketplace,
        funding=funding,
        effects=private_control,
        clock=private_control,
    )


@pytest.fixture(scope="function")
def hermetic_recovery_driver(
    hosted_scenario_driver: HostedScenarioDriver,
    hosted_ports: Any,
    private_control: ReleasedControlCli,
) -> HermeticRecoveryDriver:
    funding = hosted_scenario_driver.funding
    if not isinstance(funding, PrivateFundingDriver):
        raise TypeError("hermetic recovery requires PrivateFundingDriver")
    return HermeticRecoveryDriver(
        scenario=hosted_scenario_driver,
        control=private_control,
        funding=funding,
        restarter=hosted_ports.restarter,
    )


@pytest.fixture(scope="function")
def mechanism_port(hosted_ports: Any) -> Any:
    return hosted_ports.mechanisms


@pytest.fixture(scope="function")
def eas_condition_port(private_control: ReleasedControlCli) -> Any:
    profile = os.environ.get("HOSTED_SETTLEMENT_E2E_CONDITION_PROFILE", "")
    if profile != "local-eas":
        pytest.fail(
            "selected hosted EAS scenario requires "
            "HOSTED_SETTLEMENT_E2E_CONDITION_PROFILE=local-eas",
            pytrace=False,
        )
    factory = _load_factory("HOSTED_SETTLEMENT_E2E_EAS_FACTORY")
    return factory(control=private_control)
