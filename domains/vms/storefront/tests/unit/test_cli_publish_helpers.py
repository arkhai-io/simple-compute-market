"""Unit tests for `market-storefront publish` DB helpers.

The `--watch` mode's correctness hinges on these two functions:

- `_open_order_resource_ids(db)` — returns the set of resource_ids that
  currently have an open sell order, so `--watch` can skip them.
- `_publish_command_round(...)` — given a `skip_ids`, publishes one listing per
  available resource NOT in the skip set.

Testing these against a real SQLite schema catches the most likely
regression: `--watch` publishing duplicate orders for the same resource
on every cycle.
"""

from __future__ import annotations

import json
import sqlite3
from typing import ClassVar
from unittest.mock import patch

import pytest
from domains.vms.listings.reconciler import (
    listing_resource_key,
)
from market_identity import Ed25519Signer, TrustedIdentitySet
from market_settlement_runtime import SettlementPublicationClause

from market_storefront import cli_publish
from market_storefront.cli_publish import (
    _available_resources,
    _bare_metal_publication_source_selection,
    _open_listing_ids,
    _open_listing_resource_keys,
    _open_order_resource_ids,
    _publication_adapters,
    _publication_source_selection,
    _site_pool_projection_sync,
    _stale_open_listing_ids,
)
from tests._settings_overrides import settings_overrides

_SITE_SIGNER = Ed25519Signer(b"\x51" * 32)
_SITE_AUTHORITIES = TrustedIdentitySet(
    identities=(Ed25519Signer(b"\x52" * 32).identity,)
)


@pytest.fixture(autouse=True)
def _site_projection_identity(monkeypatch):
    from market_storefront.utils import config as agent_config

    monkeypatch.setattr(
        agent_config, "resolve_marketplace_signer", lambda: _SITE_SIGNER
    )
    monkeypatch.setattr(
        agent_config, "get_provisioning_authorities", lambda: _SITE_AUTHORITIES
    )


def _init_db(path: str) -> None:
    """Create the minimal subset of the agent schema the helpers touch."""
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE resources (
                pk INTEGER PRIMARY KEY AUTOINCREMENT,
                resource_id TEXT NOT NULL UNIQUE,
                resource_type TEXT NOT NULL,
                resource_subtype TEXT,
                unit TEXT,
                value NUMERIC,
                state TEXT,
                attributes TEXT,
                min_price TEXT,
                token TEXT,
                max_duration_seconds INTEGER,
                accepted_escrows TEXT,
                settlements TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE listings (
                listing_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                offer_resource TEXT,
                demand_resource TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE compute_allocations (
                allocation_id TEXT PRIMARY KEY,
                resource_id TEXT NOT NULL,
                listing_id TEXT,
                escrow_uid TEXT,
                gpu_count INTEGER NOT NULL,
                state TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                released_at TEXT
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def _insert_resource(
    path: str,
    resource_id: str,
    state: str,
    attrs: dict,
    *,
    gpu_count: int = 1,
    min_price: str | None = None,
    token: str | None = None,
    max_duration_seconds: int | None = None,
) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """INSERT INTO resources
               (resource_id, resource_type, resource_subtype, unit, value, state, attributes,
                min_price, token, max_duration_seconds)
               VALUES (?, 'compute.gpu', 'rtx4090', 'count', ?, ?, ?, ?, ?, ?)""",
            (
                resource_id,
                gpu_count,
                state,
                json.dumps(attrs),
                min_price,
                token,
                max_duration_seconds,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_allocation(
    path: str,
    allocation_id: str,
    resource_id: str,
    gpu_count: int,
    state: str,
) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """INSERT INTO compute_allocations
               (allocation_id, resource_id, gpu_count, state)
               VALUES (?, ?, ?, ?)""",
            (allocation_id, resource_id, gpu_count, state),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_order(
    path: str, order_id: str, status: str, resource_id: str | None
) -> None:
    offer = {
        "gpu_model": "RTX 4090",
        "gpu_count": 1,
        "sla": 95.0,
        "region": "New York, US",
    }
    if resource_id:
        offer["resource_id"] = resource_id
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "INSERT INTO listings (listing_id, status, offer_resource) VALUES (?, ?, ?)",
            (order_id, status, json.dumps(offer)),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# _open_order_resource_ids
# ---------------------------------------------------------------------------


def test_open_order_resource_ids_empty_when_no_orders(tmp_path):
    db = str(tmp_path / "agent.db")
    _init_db(db)
    assert _open_order_resource_ids(db) == set()


def test_open_order_resource_ids_picks_up_open_orders(tmp_path):
    db = str(tmp_path / "agent.db")
    _init_db(db)
    _insert_order(db, "o1", "open", "compute-001")
    _insert_order(db, "o2", "open", "compute-002")
    assert _open_order_resource_ids(db) == {"compute-001", "compute-002"}


def test_open_order_resource_ids_ignores_closed_orders(tmp_path):
    db = str(tmp_path / "agent.db")
    _init_db(db)
    _insert_order(db, "o1", "open", "compute-001")
    _insert_order(db, "o2", "closed", "compute-002")
    _insert_order(db, "o3", "expired", "compute-003")
    assert _open_order_resource_ids(db) == {"compute-001"}


def test_open_order_resource_ids_skips_orders_without_resource_id(tmp_path):
    db = str(tmp_path / "agent.db")
    _init_db(db)
    _insert_order(db, "o1", "open", None)
    _insert_order(db, "o2", "open", "compute-002")
    assert _open_order_resource_ids(db) == {"compute-002"}


def test_open_listing_resource_keys_include_gpu_slice(tmp_path):
    db = str(tmp_path / "agent.db")
    _init_db(db)
    _insert_order(db, "o1", "open", "compute-001")
    _insert_order(db, "o2", "open", "compute-002")
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "UPDATE listings SET offer_resource = ? WHERE listing_id = ?",
            (
                json.dumps(
                    {
                        "resource_id": "compute-002",
                        "gpu_model": "RTX 4090",
                        "gpu_count": 2,
                        "sla": 95.0,
                        "region": "New York, US",
                    }
                ),
                "o2",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    assert _open_listing_resource_keys(db) == {
        listing_resource_key("default", "compute-001", 1),
        listing_resource_key("default", "compute-002", 2),
    }


# ---------------------------------------------------------------------------
# _publish_command_round
# ---------------------------------------------------------------------------


def test_available_resources_derives_slices_from_gpu_capacity(tmp_path):
    db = str(tmp_path / "agent.db")
    _init_db(db)
    _insert_resource(
        db,
        "compute-4x",
        "available",
        {"gpu_model": "RTX 4090", "sla": 95.0, "region": "NY"},
        gpu_count=4,
    )

    rows = _available_resources(db)

    assert [r["gpu_count"] for r in rows] == [1, 2, 3, 4]
    assert {r["resource_key"] for r in rows} == {
        listing_resource_key("default", "compute-4x", n) for n in (1, 2, 3, 4)
    }


def test_available_resources_closes_oversized_slices_when_capacity_held(
    tmp_path,
    monkeypatch,
):
    db = str(tmp_path / "agent.db")
    _init_db(db)
    _insert_resource(
        db,
        "compute-4x",
        "available",
        {"gpu_model": "RTX 4090", "sla": 95.0, "region": "NY"},
        gpu_count=4,
    )
    # The site authority says 2 of 4 units are consumed.
    monkeypatch.setattr(
        cli_publish,
        "_member_availability_sync",
        lambda: {(None, "compute-4x"): 2, ("default", "compute-4x"): 2},
    )

    rows = _available_resources(db)

    assert [r["gpu_count"] for r in rows] == [1, 2]


class TestPoolHintResolutionSettings:
    """Unit coverage for cli_publish._pool_hint_resolution_settings --
    confirms the real `[pricing]` config is actually read, not just that
    the reconciler-side resolver logic (tested independently in
    test_pool_descriptors.py / test_reconciler.py) is correct in
    isolation."""

    def test_reads_defaults_from_settings_toml(self):
        settings = cli_publish._pool_hint_resolution_settings()
        assert settings.accept_pool_declared_sla is False
        assert settings.default_sla == 0.0

    def test_reads_an_explicit_override(self):
        with settings_overrides(
            **{
                "pricing.accept_pool_declared_sla": True,
                "pricing.default_sla": 42.0,
            }
        ):
            settings = cli_publish._pool_hint_resolution_settings()
        assert settings.accept_pool_declared_sla is True
        assert settings.default_sla == 42.0

    def test_flat_pricing_defaults_become_the_tier_1_fallback(self):
        with settings_overrides(
            **{
                "pricing.default_min_price": "1.00",
                "pricing.default_token_address": "0xflat",
                "pricing.default_max_duration_seconds": 60,
            }
        ):
            settings = cli_publish._pool_hint_resolution_settings()
        assert settings.gpu_pricing_flat_default.min_price == "1.00"
        assert settings.gpu_pricing_flat_default.token == "0xflat"
        assert settings.gpu_pricing_flat_default.max_duration_seconds == 60

    def test_unset_flat_pricing_defaults_are_none_not_empty_string(self):
        """An unset default_min_price/token/... must fall through as
        None so lower-priority resolution tiers still have a chance --
        propagating "" would be treated as a real (if empty) value."""
        settings = cli_publish._pool_hint_resolution_settings()
        assert settings.gpu_pricing_flat_default.min_price is None
        assert settings.gpu_pricing_flat_default.token is None

    def test_per_model_gpu_pricing_defaults_read_from_config(self):
        with settings_overrides(
            **{
                "pricing.defaults": {
                    "gpu": {
                        "H100": {"min_price": "5.00"},
                        "A100": {"min_price": "3.00"},
                    },
                },
            }
        ):
            settings = cli_publish._pool_hint_resolution_settings()
        assert settings.gpu_pricing_defaults_by_model["H100"].min_price == "5.00"
        assert settings.gpu_pricing_defaults_by_model["A100"].min_price == "3.00"

    def test_command_clauses_replace_per_model_settlement_defaults(self):
        model_default = {
            "mechanism": "fiat.stripe.v1",
            "asset": "usd",
            "rate": "2",
            "per": "hour",
            "mechanism_input": {
                "method": "card",
                "funds_flow": "separate_charges_transfers",
            },
        }
        command_clause = SettlementPublicationClause(
            mechanism="alkahest.v1",
            asset="0x" + "12" * 20,
            rate="3",
            per="hour",
            mechanism_input={
                "chain": "base_sepolia",
                "escrow_kind": "erc20_escrow_obligation_default",
            },
        )
        with settings_overrides(
            **{
                "pricing.defaults": {"gpu": {"H100": {"settlements": [model_default]}}},
            }
        ):
            settings = cli_publish._pool_hint_resolution_settings((command_clause,))

        assert settings.gpu_pricing_defaults_by_model["H100"].settlements == [
            command_clause.model_dump(mode="json", exclude_defaults=True)
        ]

    def test_no_configured_gpu_defaults_is_an_empty_mapping_not_an_error(self):
        settings = cli_publish._pool_hint_resolution_settings()
        assert settings.gpu_pricing_defaults_by_model == {}


def test_stale_open_listing_ids_finds_slices_above_available_capacity(
    tmp_path, monkeypatch
):
    db = str(tmp_path / "agent.db")
    _init_db(db)
    _insert_resource(
        db,
        "compute-4x",
        "available",
        {"gpu_model": "RTX 4090", "sla": 95.0, "region": "NY"},
        gpu_count=4,
    )
    for gpu_count in (1, 2, 3, 4):
        _insert_order(db, f"listing-{gpu_count}x", "open", "compute-4x")
        conn = sqlite3.connect(db)
        try:
            conn.execute(
                "UPDATE listings SET offer_resource = ? WHERE listing_id = ?",
                (
                    json.dumps(
                        {
                            "resource_id": "compute-4x",
                            "gpu_model": "RTX 4090",
                            "gpu_count": gpu_count,
                            "sla": 95.0,
                            "region": "NY",
                        }
                    ),
                    f"listing-{gpu_count}x",
                ),
            )
            conn.commit()
        finally:
            conn.close()
    monkeypatch.setattr(
        cli_publish,
        "_member_availability_sync",
        lambda: {(None, "compute-4x"): 2, ("default", "compute-4x"): 2},
    )

    assert _stale_open_listing_ids(db) == ["listing-3x", "listing-4x"]

    # No authority answer → never close on ignorance.
    monkeypatch.setattr(cli_publish, "_member_availability_sync", lambda: None)
    assert _stale_open_listing_ids(db) == []


def test_vm_publish_adapters_do_not_include_bare_metal() -> None:
    assert [adapter.name for adapter in _publication_adapters()] == ["vms"]


def test_publication_selection_can_compose_bare_metal(monkeypatch) -> None:
    def fake_build_source(name, **_kwargs):
        from core_storefront.publication_sources import PublicationSource

        return PublicationSource(
            name=name,
            open_keys=lambda _db: set(),
            close_stale=lambda _db, _url: [],
            available_candidates=lambda _db: [],
            skip_keys=lambda _candidate: set(),
            offer_resource=lambda candidate: candidate,
            record_published=lambda *_args: None,
            reopen_existing=lambda *_args: None,
            reopen_error_label="reopen fake",
        )

    monkeypatch.setattr(
        "core_storefront.publication_runner.build_publication_source",
        fake_build_source,
    )

    assert [
        source.name
        for source in _bare_metal_publication_source_selection().build_sources()
    ] == ["bare_metal"]
    assert [
        source.name
        for source in _publication_source_selection(
            ("vms", "bare_metal")
        ).build_sources()
    ] == ["vms", "bare_metal"]


def test_open_order_ids_returns_only_open(tmp_path):
    """--abort-all's target set is just `status='open'` listings."""
    db = str(tmp_path / "agent.db")
    _init_db(db)
    _insert_order(db, "o1", "open", "compute-001")
    _insert_order(db, "o2", "closed", "compute-002")
    _insert_order(db, "o3", "open", None)
    _insert_order(db, "o4", "expired", "compute-004")
    assert set(_open_listing_ids(db)) == {"o1", "o3"}


# ---------------------------------------------------------------------------
# _site_pool_projection_sync -- CLI's own synchronous projection fetch
# ---------------------------------------------------------------------------


class _FakeSiteCapacityClient:
    """Async site-client double matching the signed projection API."""

    _outcomes_by_url: ClassVar[dict[str, object]] = {}

    def __init__(
        self,
        base_url,
        signer,
        expected_authorities,
        *,
        timeout,
    ):
        assert signer is _SITE_SIGNER
        assert expected_authorities == _SITE_AUTHORITIES
        assert timeout == 10
        self.base_url = base_url

    async def resource_pool_projection(self):
        outcome = self._outcomes_by_url[self.base_url]
        if isinstance(outcome, Exception):
            raise outcome
        assert callable(outcome)
        return outcome()


def _fake_site_capacity_client_class(outcomes_by_url):
    return type(
        "_ConfiguredFakeSiteCapacityClient",
        (_FakeSiteCapacityClient,),
        {"_outcomes_by_url": outcomes_by_url},
    )


class TestSitePoolProjectionSync:
    def test_one_site_succeeds(self):
        rows = [{"resource_pool_id": "gpu-pool", "resources": []}]
        fake_client = _fake_site_capacity_client_class(
            {"http://site-a": lambda: {"resource_pools": rows}}
        )
        with (
            settings_overrides(**{"capacity.sites": {"site-a": "http://site-a"}}),
            patch("market_site_client.SiteCapacityClient", fake_client),
        ):
            result = _site_pool_projection_sync()
        assert result == {"site-a": rows}

    def test_successful_empty_resource_pools_is_kept_not_dropped(self):
        """An authoritative empty projection remains distinguishable from failure."""
        fake_client = _fake_site_capacity_client_class(
            {"http://site-a": lambda: {"resource_pools": []}}
        )
        with (
            settings_overrides(**{"capacity.sites": {"site-a": "http://site-a"}}),
            patch("market_site_client.SiteCapacityClient", fake_client),
        ):
            result = _site_pool_projection_sync()
        assert result == {"site-a": []}

    def test_one_site_fails_others_still_reported(self):
        rows_b = [{"resource_pool_id": "gpu-pool-b", "resources": []}]
        fake_client = _fake_site_capacity_client_class(
            {
                "http://site-a": RuntimeError("connection refused"),
                "http://site-b": lambda: {"resource_pools": rows_b},
            }
        )
        with (
            settings_overrides(
                **{
                    "capacity.sites": {
                        "site-a": "http://site-a",
                        "site-b": "http://site-b",
                    }
                }
            ),
            patch("market_site_client.SiteCapacityClient", fake_client),
        ):
            result = _site_pool_projection_sync()
        assert result == {"site-b": rows_b}
        assert "site-a" not in result

    def test_all_sites_fail_returns_none(self):
        fake_client = _fake_site_capacity_client_class(
            {"http://site-a": RuntimeError("connection refused")}
        )
        with (
            settings_overrides(**{"capacity.sites": {"site-a": "http://site-a"}}),
            patch("market_site_client.SiteCapacityClient", fake_client),
        ):
            result = _site_pool_projection_sync()
        assert result is None

    def test_no_sites_configured_returns_none(self):
        with settings_overrides(
            **{
                "capacity.sites": {},
                "capacity.authority_url": "",
                "provisioning.service_url": "",
            }
        ):
            result = _site_pool_projection_sync()
        assert result is None

    def test_projection_client_error_is_treated_as_failure(self):
        fake_client = _fake_site_capacity_client_class(
            {"http://site-a": RuntimeError("HTTP 500")}
        )
        with (
            settings_overrides(**{"capacity.sites": {"site-a": "http://site-a"}}),
            patch("market_site_client.SiteCapacityClient", fake_client),
        ):
            result = _site_pool_projection_sync()
        assert result is None


class TestSitePoolProjectionIfEnabled:
    def test_flag_disabled_returns_none_without_fetching(self):
        with settings_overrides(**{"capacity.use_site_projection_for_listings": False}):
            assert cli_publish._site_pool_projection_if_enabled() is None

    def test_flag_enabled_fetches(self):
        rows = [{"resource_pool_id": "gpu-pool", "resources": []}]
        fake_client = _fake_site_capacity_client_class(
            {"http://site-a": lambda: {"resource_pools": rows}}
        )
        with (
            settings_overrides(
                **{
                    "capacity.use_site_projection_for_listings": True,
                    "capacity.sites": {"site-a": "http://site-a"},
                }
            ),
            patch("market_site_client.SiteCapacityClient", fake_client),
        ):
            result = cli_publish._site_pool_projection_if_enabled()
        assert result == {"site-a": rows}
