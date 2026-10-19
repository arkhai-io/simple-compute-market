"""`bare-metal-storefront publish` steps the running storefront's publication loop.

Application integration: the real app runs with its lifespan on a loopback port
(``loopback.serving``), its loops held, and the command -- reading its identity
and the storefront's ``base_url`` from the configuration files the server reads
-- runs one cycle, or previews one, through the administrator API. The cycle the
step runs is composed inside the storefront, by ``compose_publication_cycle``
from its runtime, with only the cycle class replaced by ``RecordingCycle``, which
records what it was handed and when it ran. So these tests prove the path from
the command through the typed client to the step route, and the composition the
storefront hands its cycle; the real cycle behind the step is
``test_http_system.py``'s. The command opens no database: the configuration's
``db_path`` names a file that never comes to exist, and running the command
loads none of the storefront's database or runtime modules. Spec scenario "An
operator runs the bare-metal publication command".
"""

from __future__ import annotations

import ast
import contextlib
import dataclasses
import json
import subprocess
import sys
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
from test_http_system import _app, _derivation_runtime, _runtime as _http_runtime
from test_pool_overrides_api import _with_sites
from test_publication_cycle import SELLER_WALLET, Site, alkahest_publication, member, pool

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


def _publication_status(base_url: str) -> dict[str, Any]:
    """The publication loop as the running storefront's status reports it."""
    with SyncStorefrontClient(
        base_url,
        signer=SELLER,
        caller_role="admin",
        expected_publishers=TrustedIdentitySet(identities=(SELLER.identity,)),
    ) as admin:
        return admin.get_system_status().lifecycle[PUBLICATION]


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
        publication = _publication_status(base_url)

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
    assert publication["state"] == "paused"
    assert publication["last_outcome"]["trigger"] == "step"
    assert publication["last_outcome"]["completed"] is True


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
        publication = _publication_status(base_url)

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["dry_run"] is True
    (cycle,) = RecordingCycle.constructed
    assert [run["dry_run"] for run in cycle.runs] == [True]
    assert publication["last_outcome"] is None


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
        outcome = _publication_status(base_url)["last_outcome"]

    assert result.exit_code == 1
    assert reason in result.output
    assert RecordingCycle.constructed == []
    assert (outcome["completed"], outcome["stage"]) == (False, "compose")


@pytest.mark.parametrize("flag", ["--storefront-url", "-a"])
def test_the_flag_names_the_storefront_in_place_of_the_configured_url(
    monkeypatch, tmp_path, flag
):
    runtime = _runtime(tmp_path, monkeypatch)
    with serving(_app(runtime)) as base_url:
        with _configured_for(monkeypatch, tmp_path, "http://127.0.0.1:9"):
            result = runner.invoke(cli, ["publish", flag, base_url])

    assert result.exit_code == 0, result.output
    assert len(RecordingCycle.constructed) == 1


def test_a_storefront_nothing_answers_for_is_reported_without_a_traceback(
    monkeypatch, tmp_path
):
    with _configured_for(monkeypatch, tmp_path, "http://127.0.0.1:9"):
        result = runner.invoke(cli, ["publish"])

    assert result.exit_code == 1
    assert "no storefront answered at http://127.0.0.1:9 (ConnectError)" in result.output
    assert "Traceback" not in result.output


def test_abort_all_closes_every_open_listing_as_its_seller(monkeypatch, tmp_path):
    """Two listings a real cycle published, through the command, are closed by
    ``--abort-all`` as their seller, and the next cycle leaves them closed."""
    site = Site(pool("pool-1", member("r1", "pool-1"), member("r2", "pool-1")))
    runtime = dataclasses.replace(
        _derivation_runtime(tmp_path, monkeypatch, {"site-a": site}),
        admin_principals=TrustedIdentitySet(identities=(SELLER.identity,)),
    )
    with serving(_app(runtime)) as base_url:
        with _configured_for(monkeypatch, tmp_path, base_url):
            published = runner.invoke(cli, ["publish"])
            aborted = runner.invoke(cli, ["publish", "--abort-all"])
            again = runner.invoke(cli, ["publish"])
        with SyncStorefrontClient(base_url) as public:
            still_open = public.list_listings(status="open").listings
            closed = public.list_listings(status="closed").listings

    assert published.exit_code == 0, published.output
    assert json.loads(published.output)["counts"]["publish"] == 2
    assert aborted.exit_code == 0, aborted.output
    assert sorted(json.loads(aborted.output)["closed"]) == sorted(
        listing.listing_id for listing in closed
    )
    assert again.exit_code == 0, again.output
    assert json.loads(again.output)["counts"].get("publish") is None
    assert still_open == []
    assert {listing.extra["closed_by"] for listing in closed} == {"seller"}


def test_abort_all_is_not_previewed(monkeypatch, tmp_path):
    result = runner.invoke(cli, ["publish", "--abort-all", "--dry-run"])

    assert result.exit_code != 0
    assert "--abort-all cannot be combined with --dry-run" in result.output


_LOADED_BY_PUBLISH = """
import sys
from typer.testing import CliRunner
from arkhai_bare_metal_storefront.cli import app

result = CliRunner().invoke(app, ["publish"])
assert result.exit_code == 1, result.output
print(sorted(name for name in sys.modules if name.startswith("arkhai_bare_metal_storefront")))
"""


def test_the_command_loads_none_of_the_storefronts_database_or_runtime(
    monkeypatch, tmp_path
):
    """In a fresh interpreter, every module ``publish`` imports while it runs,
    against a storefront nothing answers for, is listed: none is the
    storefront's database layer, its runtime, or its publication composition."""
    directory = write_configuration(
        monkeypatch, tmp_path, publishable_configuration(tmp_path / "never.db")
    )
    monkeypatch.setenv(IDENTITY_CREDENTIAL_ENV, SELLER_CREDENTIAL)
    document = json.loads((directory / "storefront.json").read_text())
    document["base_url"] = "http://127.0.0.1:9"
    (directory / "storefront.json").write_text(json.dumps(document))

    completed = subprocess.run(
        [sys.executable, "-c", _LOADED_BY_PUBLISH],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )

    loaded = set(ast.literal_eval(completed.stdout.strip().splitlines()[-1]))
    assert "arkhai_bare_metal_storefront.publication_cli" in loaded
    for module in ("sqlite_client", "runtime", "publication_composition", "migrations"):
        assert f"arkhai_bare_metal_storefront.{module}" not in loaded
    assert not (tmp_path / "never.db").exists()


def test_without_the_storefront_identity_it_refuses_before_connecting(
    monkeypatch, tmp_path
):
    write_configuration(monkeypatch, tmp_path)
    monkeypatch.delenv(IDENTITY_CREDENTIAL_ENV, raising=False)

    result = runner.invoke(cli, ["publish", "--storefront-url", "http://127.0.0.1:9"])

    assert result.exit_code != 0
    assert "ARKHAI_IDENTITY_CREDENTIAL" in result.output
