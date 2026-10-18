"""`bare-metal-storefront publish` steps the running storefront's publication loop.

Application integration: the real app runs with its lifespan on a loopback port
(``loopback.serving``), its loops held, and the command -- reading its identity
and the storefront's ``base_url`` from the configuration files the server reads
-- runs one cycle, or previews one, through the administrator API. The cycle the
step runs is composed inside the storefront, by ``compose_publication_cycle``
from its runtime, with only the cycle class replaced by one recording what it
was handed and when it ran. The command opens no database: the configuration's
``db_path`` names a file that never comes to exist. Spec scenarios "An operator
runs the bare-metal publication command" and "Publication runs from the
command".
"""

from __future__ import annotations

import ast
import contextlib
import dataclasses
import inspect
import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from core_storefront.multi_registry_client import (
    MultiRegistryClient,
    RegistryAuthorityTrust,
)
from market_identity import Eip191Signer, TrustedIdentitySet
from storefront_client import SyncStorefrontClient
from typer.testing import CliRunner

from arkhai_bare_metal_storefront import publication_cli
from arkhai_bare_metal_storefront.cli import app as cli
from arkhai_bare_metal_storefront.config import IDENTITY_CREDENTIAL_ENV
from arkhai_bare_metal_storefront.lifecycle_steps import PUBLICATION
from arkhai_bare_metal_storefront.publication_composition import compose_publication_cycle
from arkhai_bare_metal_storefront.publication_service import (
    BareMetalRegistryConfiguration,
)
from arkhai_bare_metal_storefront.runtime import BareMetalStorefrontRuntime
from loopback import serving
from source_sites import SourceSite
from storefront_configuration import (
    SELLER,
    SELLER_CREDENTIAL,
    publishable_configuration,
    write_configuration,
)
from test_http_system import _app, _runtime as _http_runtime
from test_pool_overrides_api import _with_sites
from test_publication_cycle import SELLER_WALLET, alkahest_publication

# A development key; never used on any public network.
REGISTRY = Eip191Signer(bytes.fromhex("55" * 32))

_TRUST = RegistryAuthorityTrust(
    authority="registry.example",
    principals=TrustedIdentitySet(identities=(REGISTRY.identity,)),
)
REGISTRIES = BareMetalRegistryConfiguration(
    authorities={
        "https://registry.example": _TRUST,
        "https://registry-b.example": _TRUST,
    }
)
SITE_IDS = ("site-a", "site-b")

runner = CliRunner()


class RecordingCycle:
    """Stands in for the composed cycle, recording what it was handed."""

    constructed: list[RecordingCycle] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.runs: list[dict[str, Any]] = []
        RecordingCycle.constructed.append(self)

    async def run(self, *, dry_run: bool = False) -> dict[str, Any]:
        self.runs.append(
            {"dry_run": dry_run, "held": self.kwargs["site_projections"].status()}
        )
        return {"dry_run": dry_run, "actions": [{"action": "hold"}], "counts": {"hold": 1}}


@pytest.fixture(autouse=True)
def _no_recorded_cycles() -> Iterator[None]:
    RecordingCycle.constructed.clear()
    yield
    RecordingCycle.constructed.clear()


def _runtime(tmp_path, monkeypatch, **changes: Any) -> BareMetalStorefrontRuntime:
    """A storefront over two sites, publishing under Alkahest to two registries.

    Its administrator is the configured storefront identity, the one the
    command signs as, and each publication cycle is composed from it as the
    loop composes one, by the recording cycle class.
    """
    composition, clauses = alkahest_publication(tmp_path, monkeypatch, SELLER)
    sited = _with_sites(_http_runtime(str(tmp_path / "storefront.db")), *SITE_IDS)
    fields: dict[str, Any] = {
        "admin_principals": TrustedIdentitySet(identities=(SELLER.identity,)),
        "seller_evm_address": SELLER_WALLET,
        "settlement_composition": composition,
        "publication_clauses": clauses,
        "default_max_duration_seconds": 3600,
        "settlement_servicing_interval_seconds": 3600,
        "registry_configuration": REGISTRIES,
        "publication_cycle_factory": lambda runtime: compose_publication_cycle(
            runtime, cycle_factory=RecordingCycle
        ),
    }
    return dataclasses.replace(sited, **{**fields, **changes})


@contextlib.contextmanager
def _configured_for(monkeypatch, tmp_path: Path, base_url: str) -> Iterator[Path]:
    """The command's configuration: the storefront's identity and ``base_url``,
    and a ``db_path`` the command must never open."""
    db_path = tmp_path / "command-must-not-open.db"
    document = publishable_configuration(db_path)
    document["base_url"] = base_url
    write_configuration(monkeypatch, tmp_path, document)
    monkeypatch.setenv(IDENTITY_CREDENTIAL_ENV, SELLER_CREDENTIAL)
    yield db_path
    assert not db_path.exists(), "the command opened a database"


def _sites(runtime: BareMetalStorefrontRuntime) -> dict[str, SourceSite]:
    return {site_id: runtime.capacity_client.site(site_id) for site_id in SITE_IDS}


def test_the_command_runs_one_cycle_of_the_running_storefronts_loop(
    monkeypatch, tmp_path
):
    """The cycle runs in the storefront over the projections its startup
    loaded, handed every configured site and registry and the configured lease
    bound; the command loads, polls, and opens nothing itself."""
    runtime = _runtime(tmp_path, monkeypatch)
    with serving(_app(runtime)) as base_url:
        polled = {site_id: site.calls for site_id, site in _sites(runtime).items()}
        with _configured_for(monkeypatch, tmp_path, base_url):
            result = runner.invoke(cli, ["publish"])
        after = {site_id: site.calls for site_id, site in _sites(runtime).items()}
        outcome = runtime.loops.last_outcome(PUBLICATION)
        state = runtime.loops.snapshot()[PUBLICATION].state

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "dry_run": False,
        "actions": [{"action": "hold"}],
        "counts": {"hold": 1},
    }
    (cycle,) = RecordingCycle.constructed
    assert cycle.kwargs["site_projections"] is runtime.site_projections
    assert cycle.kwargs["site_ids"] == list(SITE_IDS)
    assert cycle.kwargs["sqlite_client"] is runtime.db
    assert cycle.kwargs["seller_principal"] == SELLER.identity
    assert cycle.kwargs["storefront_url"] == runtime.storefront_url
    assert cycle.kwargs["registry_urls"] == (
        "https://registry.example",
        "https://registry-b.example",
    )
    assert cycle.kwargs["default_max_duration_seconds"] == 3600
    assert cycle.kwargs["derivation"] is runtime.publication_derivation
    # The storefront's startup loaded both sites; the step polled nothing more.
    (run,) = cycle.runs
    assert run["dry_run"] is False
    assert {
        site_id: {family: status.state for family, status in families.items()}
        for site_id, families in run["held"].items()
    } == {
        site_id: {"resource_pool": "loaded", "capacity_bucket": "loaded"}
        for site_id in SITE_IDS
    }
    assert after == polled
    # The storefront ran it as an operator's step of its loop, which stays held.
    assert (outcome.trigger, outcome.completed) == ("step", True)
    assert state == "paused"


def test_the_registry_transport_is_every_configured_registry(monkeypatch, tmp_path):
    """The storefront hands its cycle a factory for exactly the configured
    registries, each pinned to its configured authority."""
    runtime = _runtime(tmp_path, monkeypatch)
    with serving(_app(runtime)) as base_url:
        with _configured_for(monkeypatch, tmp_path, base_url):
            result = runner.invoke(cli, ["publish"])

    assert result.exit_code == 0, result.output
    client = RecordingCycle.constructed[0].kwargs["registry_client_factory"]()
    assert isinstance(client, MultiRegistryClient)
    assert client.urls == ["https://registry.example", "https://registry-b.example"]


def test_dry_run_previews_one_cycle_and_records_no_outcome(monkeypatch, tmp_path):
    runtime = _runtime(tmp_path, monkeypatch)
    with serving(_app(runtime)) as base_url:
        with _configured_for(monkeypatch, tmp_path, base_url):
            result = runner.invoke(cli, ["publish", "--dry-run"])
        outcome = runtime.loops.last_outcome(PUBLICATION)

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["dry_run"] is True
    (cycle,) = RecordingCycle.constructed
    assert [run["dry_run"] for run in cycle.runs] == [True]
    assert outcome is None


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"registry_configuration": None}, "no registry is configured for publication"),
        ({"site_projections": None}, "site projection state is unavailable"),
    ],
)
def test_a_cycle_the_storefront_cannot_compose_fails_the_command(
    monkeypatch, tmp_path, changes, reason
):
    runtime = _runtime(tmp_path, monkeypatch, **changes)
    with serving(_app(runtime)) as base_url:
        with _configured_for(monkeypatch, tmp_path, base_url):
            result = runner.invoke(cli, ["publish"])
        outcome = runtime.loops.last_outcome(PUBLICATION)

    assert result.exit_code == 1
    assert reason in result.output
    assert RecordingCycle.constructed == []
    assert (outcome.completed, outcome.stage) == (False, "compose")


def test_the_flag_names_the_storefront_in_place_of_the_configured_url(
    monkeypatch, tmp_path
):
    runtime = _runtime(tmp_path, monkeypatch)
    with serving(_app(runtime)) as base_url:
        with _configured_for(monkeypatch, tmp_path, "http://127.0.0.1:9"):
            result = runner.invoke(cli, ["publish", "--storefront-url", base_url])

    assert result.exit_code == 0, result.output
    assert len(RecordingCycle.constructed) == 1


def test_an_override_reports_applied_after_the_command_runs_with_no_generation_recorded(
    monkeypatch, tmp_path
):
    """The running storefront judges an override against the projection it
    holds of the site, so once the command has run a cycle it reports the
    override applied, and no generation is recorded for the purpose. Spec
    scenario "Publication runs from the command"."""
    runtime = _runtime(tmp_path, monkeypatch)
    record = tmp_path / "override.json"
    record.write_text(
        json.dumps(
            {
                "site_id": "site-a",
                "pool_id": "pool-a",
                "offering_mode": "bare_metal",
                "terms": {"max_duration_seconds": 60},
            }
        )
    )
    with serving(_app(runtime)) as base_url:
        with _configured_for(monkeypatch, tmp_path, base_url):
            written = runner.invoke(cli, ["pool-override", "set", "--file", str(record)])
            published = runner.invoke(cli, ["publish"])
        with SyncStorefrontClient(
            base_url,
            signer=SELLER,
            caller_role="admin",
            expected_publishers=TrustedIdentitySet(identities=(SELLER.identity,)),
        ) as admin:
            status = admin.get_system_status()

    assert written.exit_code == 0, written.output
    assert published.exit_code == 0, published.output
    assert [
        (entry["site_id"], entry["pool_id"], entry["state"])
        for entry in status.extra["pool_overrides"]
    ] == [("site-a", "pool-a", "applied")]
    # Read directly: no route reports the storefront's tables.
    with contextlib.closing(sqlite3.connect(runtime.db.db_path)) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
    assert "bare_metal_accepted_site_generations" not in tables


def test_the_command_never_opens_the_storefront_database():
    """No module the command runs imports the storefront's database layer."""
    tree = ast.parse(inspect.getsource(publication_cli))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }

    assert "sqlite3" not in imported
    assert not any(
        name.endswith(("sqlite_client", "runtime", "publication_composition"))
        for name in imported
    )


def test_without_the_storefront_identity_it_refuses_before_connecting(
    monkeypatch, tmp_path
):
    write_configuration(monkeypatch, tmp_path)
    monkeypatch.delenv(IDENTITY_CREDENTIAL_ENV, raising=False)

    result = runner.invoke(cli, ["publish", "--storefront-url", "http://127.0.0.1:9"])

    assert result.exit_code != 0
    assert "ARKHAI_IDENTITY_CREDENTIAL" in result.output
