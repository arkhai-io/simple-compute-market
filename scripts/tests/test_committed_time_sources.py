"""No committed configuration outside the lanes' own sets a party's time to injected.

Injected time is a test control every production image carries; a deployment's
configuration never turns it on, and nothing in a service refuses it, since no
service can tell it runs in production. So the configuration this repository
commits for a deployment or an operator to start from is held to wall time
here:

- the chart defaults, each chart's ``values.yaml`` and the umbrella's;
- the local Helm releases' values, ``helm/local-values.yaml`` and
  ``helm/bare-metal-release-values.yaml``;
- the production examples: each chart's ``examples/*values*.yaml``, the seller's
  and the registry's production Compose stacks (``compose/seller.yml``,
  ``compose/registry.yml``) and the registry's env file an operator copies
  (``config.registry.env.example``);
- the shipped presets: the defaults and profiles each service packages
  (``settings.toml``, provisioning's packaged ``config/*.yml``), and the
  storefront files committed for an operator that no lane mounts
  (``storefront.bob.toml``, ``storefront.credits.toml``).

Each file is parsed as its consumer parses it — YAML, TOML, or ``KEY=VALUE``
lines — with keys in any case, and its tree searched for a setting choosing
injected time: ``time.source`` under any spelling of its section (``[Time]
source`` for a storefront), ``TIME_SOURCE`` (the registry's), a variable ending
``_TIME_SOURCE`` (the lane doubles' and the sample app's), or an override
variable ending ``_TIME__SOURCE`` (a Dynaconf service's). A refusal names the
file and the setting's path, which names the party. The search reads the files,
not what Helm or Compose would render from them, so it refuses a setting even
where a chart would drop it.

Outside the check: the configuration the lanes mount, which a lane may set to
injected time — their Compose files, the identities and profiles under
``dev-env/``, ``storefront.*.lane.toml``, and the storefront files the lanes
share with the full local stack (``storefront.alice.toml``,
``storefront.dev.toml``); the end-to-end runner's profiles, which configure no
party; and the charts' render fixtures under ``helm/fixtures/``.
"""

from __future__ import annotations

import tomllib
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The production examples and presets beside the charts.
PRODUCTION_FILES = (
    "compose/seller.yml",
    "compose/registry.yml",
    "config.registry.env.example",
    "domains/vms/storefront/storefront.bob.toml",
    "domains/apicredits/storefront/storefront.credits.toml",
)

#: The defaults each service packages in its wheel.
PACKAGED_DEFAULTS = (
    "domains/apicredits/service/src/apicredits_service/settings.toml",
    "domains/apicredits/storefront/src/apicredits_storefront/settings.toml",
    "domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/settings.toml",
    "domains/vms/storefront/src/market_storefront/settings.toml",
    "provisioning/compute/service/src/compute_provisioning_service/settings.toml",
)

#: The profiles provisioning packages, which its image loads by default.
PACKAGED_PROFILES = "provisioning/compute/service/src/compute_provisioning_service/config"


def chart_examples() -> list[Path]:
    return sorted((REPO_ROOT / "helm").glob("charts/*/examples/*values*.yaml"))


def packaged_profiles() -> list[Path]:
    return sorted((REPO_ROOT / PACKAGED_PROFILES).glob("*.yml"))


def checked_files() -> list[Path]:
    """Every committed configuration file this check holds to wall time."""
    helm = REPO_ROOT / "helm"
    return [
        helm / "values.yaml",
        helm / "local-values.yaml",
        helm / "bare-metal-release-values.yaml",
        *sorted(helm.glob("charts/*/values.yaml")),
        *chart_examples(),
        *(REPO_ROOT / path for path in PRODUCTION_FILES),
        *(REPO_ROOT / path for path in PACKAGED_DEFAULTS),
        *packaged_profiles(),
    ]


def _read(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".toml":
        return tomllib.loads(text)
    if path.name.endswith((".env", ".env.example")):
        return dict(
            line.split("=", 1)
            for line in (raw.strip() for raw in text.splitlines())
            if line and not line.startswith("#") and "=" in line
        )
    return yaml.safe_load(text)


def _chooses_injected(name: str, value: Any) -> bool:
    upper = name.upper()
    return (upper == "TIME_SOURCE" or upper.endswith(("_TIME_SOURCE", "_TIME__SOURCE"))) and (
        str(value).strip().strip("\"'") == "injected"
    )


def _injected_settings(value: Any, path: tuple[str, ...] = ()) -> Iterator[str]:
    """The dotted path of every setting under ``value`` choosing injected time."""
    if isinstance(value, Mapping):
        for key, item in value.items():
            name = str(key)
            here = (*path, name)
            if _chooses_injected(name, item):
                yield ".".join(here)
            elif name.lower() == "time" and isinstance(item, Mapping):
                for inner, choice in item.items():
                    if str(inner).lower() == "source" and choice == "injected":
                        yield ".".join((*here, str(inner)))
            yield from _injected_settings(item, here)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            # A Compose service's `environment` may be a list of KEY=VALUE.
            if isinstance(item, str) and "=" in item:
                name, choice = item.split("=", 1)
                if _chooses_injected(name, choice):
                    yield ".".join((*path, name))
            yield from _injected_settings(item, (*path, str(index)))


def refusals(files: Iterable[Path], *, root: Path = REPO_ROOT) -> list[str]:
    """One line per file and setting that chooses injected time."""
    found = []
    for path in files:
        for setting in _injected_settings(_read(path)):
            found.append(
                f'{path.relative_to(root)}: {setting} is "injected"; committed '
                "configuration outside the lanes runs on wall time"
            )
    return found


def test_every_checked_file_exists_and_each_family_is_found():
    missing = [str(path.relative_to(REPO_ROOT)) for path in checked_files() if not path.exists()]

    assert missing == []
    assert (
        REPO_ROOT / "helm/charts/bare-metal-storefront/examples/production-values.yaml"
        in chart_examples()
    )
    assert {path.name for path in packaged_profiles()} >= {"config.yml", "config-seller.yml"}


def test_no_committed_configuration_outside_the_lanes_injects_time():
    assert refusals(checked_files()) == []


def _copy(tmp_path: Path, relative: str) -> Path:
    """A copy of a committed file under a temporary root, at its own path."""
    target = tmp_path / relative
    target.parent.mkdir(parents=True)
    target.write_text((REPO_ROOT / relative).read_text(encoding="utf-8"), encoding="utf-8")
    return target


SUFFIX = '"injected"; committed configuration outside the lanes runs on wall time'


@pytest.mark.parametrize("section", ("Time", "time"))
def test_a_production_example_setting_injected_time_is_refused_naming_it(tmp_path, section):
    """`deployment-state`'s "A production example sets injected time"."""
    relative = "helm/charts/bare-metal-storefront/examples/production-values.yaml"
    example = _copy(tmp_path, relative)
    values = yaml.safe_load(example.read_text(encoding="utf-8"))
    values.setdefault("config", {})[section] = {"source": "injected"}
    example.write_text(yaml.safe_dump(values), encoding="utf-8")

    assert refusals([example], root=tmp_path) == [
        f"{relative}: config.{section}.source is {SUFFIX}"
    ]


def test_a_packaged_profile_compose_service_env_file_or_double_injecting_time_is_refused(
    tmp_path,
):
    profile = _copy(tmp_path, f"{PACKAGED_PROFILES}/config-seller.yml")
    profile.write_text(
        profile.read_text(encoding="utf-8") + "\ntime:\n  source: injected\n", encoding="utf-8"
    )
    compose = tmp_path / "seller.yml"
    compose.write_text(
        "services:\n  provisioning:\n    environment:\n"
        "      - PROVISIONING_TIME__SOURCE=injected\n",
        encoding="utf-8",
    )
    env = tmp_path / "config.registry.env.example"
    env.write_text("# development values\nTIME_SOURCE=injected\nLOG_LEVEL=info\n", encoding="utf-8")
    doubles = tmp_path / "values.yaml"
    doubles.write_text(
        "payments-lane-double:\n  env:\n    PAYMENTS_LANE_DOUBLE_TIME_SOURCE: injected\n",
        encoding="utf-8",
    )
    wall = tmp_path / "wall.yaml"
    wall.write_text(
        "config:\n  Time:\n    source: wall\nenv:\n  MEDIATION_LANE_DOUBLE_TIME_SOURCE: wall\n",
        encoding="utf-8",
    )

    assert refusals([profile, compose, env, doubles, wall], root=tmp_path) == [
        f"{PACKAGED_PROFILES}/config-seller.yml: time.source is {SUFFIX}",
        f"seller.yml: services.provisioning.environment.PROVISIONING_TIME__SOURCE is {SUFFIX}",
        f"config.registry.env.example: TIME_SOURCE is {SUFFIX}",
        f"values.yaml: payments-lane-double.env.PAYMENTS_LANE_DOUBLE_TIME_SOURCE is {SUFFIX}",
    ]
