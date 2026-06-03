"""Phase 4 of the escrow-templates rollout: row-level templates drive
publishing instead of CHAINS broadcast + min_price/token synthesis.

These tests exercise the new branch in ``_publish_round``: when a row
carries materialized ``accepted_escrows`` (written by the CSV importer's
Phase-3 DSL parser), publishing reads it straight, scales rate values
against the entry's chain, and skips the legacy ``get_erc20_escrow_obligation_nontierable``
call entirely. Multi-chain rows can now select chains row by row
instead of every row broadcasting to every configured chain.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from market_storefront.cli_publish import _publish_round, _scale_template_entries
from service.clients.token import ERC20TokenMetadata, TokenResolutionError
from service.config_loader import ChainConfig


_USDC_BASE = "0x036cbd53842c5426634e7929541ec2318f3dcf7e"
_USDC_OPT = "0x0b2c639c533813f4aa9d7837caf62653d097ff85"
_TOKEN_DECIMALS = {
    _USDC_BASE: ("USDC", 6),
    _USDC_OPT: ("USDC", 6),
}


def _chain(name: str, chain_id: int) -> ChainConfig:
    return ChainConfig(
        name=name,
        rpc_url=f"http://rpc.{name}",
        chain_id=chain_id,
        alkahest_address_config_path=None,
    )


@pytest.fixture
def chains() -> dict[str, ChainConfig]:
    return {
        "base-sepolia": _chain("base-sepolia", 84532),
        "optimism-sepolia": _chain("optimism-sepolia", 11155420),
    }


@pytest.fixture(autouse=True)
def _stub_resolve_token(monkeypatch, chains):
    def fake_resolve(address, *, rpc_url, chain_id, refresh=False):
        key = address.lower()
        if key not in _TOKEN_DECIMALS:
            raise TokenResolutionError(f"untested address: {address}")
        sym, dec = _TOKEN_DECIMALS[key]
        return ERC20TokenMetadata(
            symbol=sym, contract_address=key, decimals=dec, chain_id=chain_id,
        )

    monkeypatch.setattr("service.clients.token.resolve_token", fake_resolve)
    from market_storefront.utils import config as agent_config
    monkeypatch.setattr(agent_config, "CHAINS", chains, raising=False)


def _init_db(path: str) -> None:
    """Schema that matches the real Phase-3 schema (with accepted_escrows)."""
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
                accepted_escrows TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE listings (
                listing_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                offer_resource TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def _insert_resource(
    path: str,
    resource_id: str,
    *,
    accepted_escrows: list[dict] | None = None,
    min_price: str | None = None,
    token: str | None = None,
) -> None:
    attrs = json.dumps({"gpu_model": "H100", "sla": 99.0, "region": "NY"})
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """INSERT INTO resources
               (resource_id, resource_type, resource_subtype, unit, value, state,
                attributes, min_price, token, accepted_escrows)
               VALUES (?, 'compute.gpu', 'h100', 'count', 1, 'available', ?, ?, ?, ?)""",
            (
                resource_id,
                attrs,
                min_price,
                token,
                json.dumps(accepted_escrows) if accepted_escrows is not None else None,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _round_kwargs(**overrides):
    base = dict(
        base_url="http://agent",
        wallet_address="",
        private_key=None,
        default_min_price=None,
        default_token_address=None,
        default_max_duration_seconds=None,
        rpc_url="http://rpc",
        chain_id=84532,
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# _scale_template_entries
# ---------------------------------------------------------------------------


def test_scale_template_entries_scales_by_decimals(chains):
    entries = [{
        "chain_name": "base-sepolia",
        "escrow_address": "0xabc" + "0" * 37,
        "literal_fields": {"token": _USDC_BASE},
        "rates": [{"field": "amount", "per": "hour", "value": "2"}],
    }]
    result = _scale_template_entries(entries, chains)
    assert len(result) == 1
    entry = result[0]
    assert entry["rates"] == [{"field": "amount", "per": "hour", "value": "2000000"}]
    assert entry["literal_fields"] == {"token": _USDC_BASE}
    assert entry["chain_name"] == "base-sepolia"
    assert "fields" not in entry
    assert "price_per_hour" not in entry


def test_scale_template_entries_preserves_zero(chains):
    entries = [{
        "chain_name": "base-sepolia",
        "escrow_address": "0xabc" + "0" * 37,
        "literal_fields": {"token": _USDC_BASE},
        "rates": [{"field": "amount", "per": "hour", "value": "0"}],
    }]
    result = _scale_template_entries(entries, chains)
    assert result[0]["rates"][0]["value"] == "0"


def test_scale_template_entries_unknown_chain_errors(chains):
    entries = [{
        "chain_name": "mars-sepolia",
        "escrow_address": "0xabc",
        "literal_fields": {"token": _USDC_BASE},
        "rates": [{"field": "amount", "per": "hour", "value": "1"}],
    }]
    with pytest.raises(ValueError, match="unknown chain 'mars-sepolia'"):
        _scale_template_entries(entries, chains)


def test_scale_template_entries_unresolvable_token_errors(chains):
    entries = [{
        "chain_name": "base-sepolia",
        "escrow_address": "0xabc",
        "literal_fields": {"token": "0x" + "ff" * 20},
        "rates": [{"field": "amount", "per": "hour", "value": "1"}],
    }]
    with pytest.raises(ValueError, match="unresolvable on chain"):
        _scale_template_entries(entries, chains)


def test_scale_template_entries_missing_token_errors(chains):
    entries = [{
        "chain_name": "base-sepolia",
        "escrow_address": "0xabc",
        "literal_fields": {},
        "rates": [{"field": "amount", "per": "hour", "value": "1"}],
    }]
    with pytest.raises(ValueError, match="missing literal_fields.token"):
        _scale_template_entries(entries, chains)


def test_scale_template_entries_rejects_negative(chains):
    entries = [{
        "chain_name": "base-sepolia",
        "escrow_address": "0xabc",
        "literal_fields": {"token": _USDC_BASE},
        "rates": [{"field": "amount", "per": "hour", "value": "-1"}],
    }]
    with pytest.raises(ValueError, match="negative"):
        _scale_template_entries(entries, chains)


def test_scale_template_entries_rejects_overprecision(chains):
    # USDC has 6 decimals; 0.0000001 would need 7.
    entries = [{
        "chain_name": "base-sepolia",
        "escrow_address": "0xabc",
        "literal_fields": {"token": _USDC_BASE},
        "rates": [{"field": "amount", "per": "hour", "value": "0.0000001"}],
    }]
    with pytest.raises(ValueError, match="more decimals"):
        _scale_template_entries(entries, chains)


# ---------------------------------------------------------------------------
# _publish_round template branch
# ---------------------------------------------------------------------------


def test_publish_round_uses_row_templates(tmp_path, monkeypatch):
    """Row with materialized accepted_escrows publishes those entries
    directly (scaled), and never touches the legacy CHAINS-broadcast path."""
    db = str(tmp_path / "agent.db")
    _init_db(db)
    _insert_resource(
        db, "compute-001",
        accepted_escrows=[{
            "chain_name": "base-sepolia",
            "escrow_address": "0xee" + "0" * 38,
            "literal_fields": {"token": _USDC_BASE},
            "rates": [{"field": "amount", "per": "hour", "value": "2"}],
        }],
    )

    calls: list[dict] = []
    monkeypatch.setattr(
        "market_storefront.cli_publish._publish_offer",
        lambda agent_url, offer, accepted_escrows, *a, **k: (
            calls.append({"offer": offer, "accepted_escrows": accepted_escrows})
            or {"status": "created", "listing_id": "l1"}
        ),
    )

    def boom_alkahest(*a, **k):
        pytest.fail(
            "Template path must not call get_erc20_escrow_obligation_nontierable"
        )

    from service.clients import alkahest as alkahest_mod
    monkeypatch.setattr(
        alkahest_mod, "get_erc20_escrow_obligation_nontierable", boom_alkahest,
    )

    published, failed, _ = _publish_round(db_path=db, **_round_kwargs())
    assert len(published) == 1
    assert not failed
    entry = calls[0]["accepted_escrows"][0]
    assert entry["chain_name"] == "base-sepolia"
    assert entry["escrow_address"] == "0xee" + "0" * 38
    assert entry["rates"][0]["value"] == "2000000"
    assert entry["literal_fields"] == {"token": _USDC_BASE}


def test_publish_round_template_multi_chain_emits_one_entry_per_chain(
    tmp_path, monkeypatch,
):
    """The whole point of templates: a single row can pick which chains
    to publish to, instead of every row broadcasting to every chain."""
    db = str(tmp_path / "agent.db")
    _init_db(db)
    _insert_resource(
        db, "compute-multi",
        accepted_escrows=[
            {
                "chain_name": "base-sepolia",
                "escrow_address": "0xbb" + "0" * 38,
                "literal_fields": {"token": _USDC_BASE},
                "rates": [{"field": "amount", "per": "hour", "value": "2"}],
            },
            {
                "chain_name": "optimism-sepolia",
                "escrow_address": "0xcc" + "0" * 38,
                "literal_fields": {"token": _USDC_OPT},
                "rates": [{"field": "amount", "per": "hour", "value": "3"}],
            },
        ],
    )

    captured: list[dict] = []
    monkeypatch.setattr(
        "market_storefront.cli_publish._publish_offer",
        lambda agent_url, offer, accepted_escrows, *a, **k: (
            captured.append({"escrows": accepted_escrows})
            or {"status": "created", "listing_id": "l-multi"}
        ),
    )

    published, failed, _ = _publish_round(db_path=db, **_round_kwargs())
    assert len(published) == 1
    assert not failed
    chains_seen = [e["chain_name"] for e in captured[0]["escrows"]]
    assert chains_seen == ["base-sepolia", "optimism-sepolia"]
    values = [e["rates"][0]["value"] for e in captured[0]["escrows"]]
    assert values == ["2000000", "3000000"]


def test_publish_round_template_ignores_row_min_price(tmp_path, monkeypatch):
    """When templates are present they're the source of truth; the row's
    min_price/token columns are ignored. Confirms a single rate value
    flows from the slot, not from min_price."""
    db = str(tmp_path / "agent.db")
    _init_db(db)
    _insert_resource(
        db, "compute-002",
        min_price="999",  # would scale to a huge number; must be ignored
        token=_USDC_OPT,  # different chain — must be ignored
        accepted_escrows=[{
            "chain_name": "base-sepolia",
            "escrow_address": "0xee" + "0" * 38,
            "literal_fields": {"token": _USDC_BASE},
            "rates": [{"field": "amount", "per": "hour", "value": "5"}],
        }],
    )
    captured: list[dict] = []
    monkeypatch.setattr(
        "market_storefront.cli_publish._publish_offer",
        lambda agent_url, offer, accepted_escrows, *a, **k: (
            captured.append({"escrows": accepted_escrows})
            or {"status": "created", "listing_id": "l1"}
        ),
    )
    published, _, _ = _publish_round(db_path=db, **_round_kwargs())
    assert len(published) == 1
    entry = captured[0]["escrows"][0]
    assert entry["chain_name"] == "base-sepolia"
    assert entry["literal_fields"]["token"] == _USDC_BASE
    assert entry["rates"][0]["value"] == "5000000"  # not 999 * 10^6


def test_publish_round_template_bad_chain_fails_row(tmp_path, monkeypatch):
    db = str(tmp_path / "agent.db")
    _init_db(db)
    _insert_resource(
        db, "compute-bad-chain",
        accepted_escrows=[{
            "chain_name": "ethereum",  # not in CHAINS
            "escrow_address": "0xff" + "0" * 38,
            "literal_fields": {"token": _USDC_BASE},
            "rates": [{"field": "amount", "per": "hour", "value": "1"}],
        }],
    )
    monkeypatch.setattr(
        "market_storefront.cli_publish._publish_offer",
        lambda *a, **k: pytest.fail("should not publish"),
    )
    _, failed, _ = _publish_round(db_path=db, **_round_kwargs())
    assert len(failed) == 1
    assert failed[0][0]["resource_id"] == "compute-bad-chain"
    assert "unknown chain" in failed[0][1]


def test_publish_round_template_unresolvable_token_fails_row(tmp_path, monkeypatch):
    db = str(tmp_path / "agent.db")
    _init_db(db)
    _insert_resource(
        db, "compute-bad-token",
        accepted_escrows=[{
            "chain_name": "base-sepolia",
            "escrow_address": "0xff" + "0" * 38,
            "literal_fields": {"token": "0x" + "de" * 20},  # not in stub
            "rates": [{"field": "amount", "per": "hour", "value": "1"}],
        }],
    )
    monkeypatch.setattr(
        "market_storefront.cli_publish._publish_offer",
        lambda *a, **k: pytest.fail("should not publish"),
    )
    _, failed, _ = _publish_round(db_path=db, **_round_kwargs())
    assert len(failed) == 1
    assert "unresolvable" in failed[0][1]


def test_publish_round_no_template_falls_back_to_legacy(tmp_path, monkeypatch):
    """Rows without accepted_escrows still use the min_price/token + CHAINS
    broadcast path. Backward compat during the rollout."""
    db = str(tmp_path / "agent.db")
    _init_db(db)
    _insert_resource(
        db, "compute-legacy",
        min_price="2", token=_USDC_BASE,
    )

    from service.clients import alkahest as alkahest_mod
    monkeypatch.setattr(
        alkahest_mod, "get_erc20_escrow_obligation_nontierable",
        lambda chain_name, *, config_path=None: "0x" + "cd" * 20,
    )
    captured: list[dict] = []
    monkeypatch.setattr(
        "market_storefront.cli_publish._publish_offer",
        lambda agent_url, offer, accepted_escrows, *a, **k: (
            captured.append({"escrows": accepted_escrows})
            or {"status": "created", "listing_id": "l1"}
        ),
    )
    published, failed, _ = _publish_round(db_path=db, **_round_kwargs())
    assert len(published) == 1
    assert not failed
    # Legacy path broadcasts to every chain in CHAINS — confirms the
    # fallback is engaged when no template is set on the row.
    seen_chains = [e["chain_name"] for e in captured[0]["escrows"]]
    assert set(seen_chains) == {"base-sepolia", "optimism-sepolia"}
