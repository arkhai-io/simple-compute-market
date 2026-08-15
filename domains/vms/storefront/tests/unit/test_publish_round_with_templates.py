"""Publication-round coverage for typed settlement clauses."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from typing import Any

from market_identity import Identity
from market_settlement_runtime import SettlementPublicationClause

from market_storefront.cli_publish import _publish_command_round
from market_storefront.domain_runtime import (
    build_vm_storefront_domain,
    build_vm_storefront_registry,
)
from market_storefront.utils.sqlite_client import SQLiteClient


_VM_REGISTRY = build_vm_storefront_registry(build_vm_storefront_domain())


def _clause(
    mechanism: str,
    *,
    asset: str,
    rate: str,
    **mechanism_input: Any,
) -> dict[str, Any]:
    return SettlementPublicationClause(
        mechanism=mechanism,
        asset=asset,
        rate=rate,
        per="hour",
        mechanism_input=mechanism_input,
    ).model_dump(mode="json", exclude_defaults=True)


def _init_db(path: str) -> None:
    SQLiteClient(db_path=path, registry=_VM_REGISTRY)


def _insert_resource(
    path: str,
    resource_id: str,
    *,
    settlements: list[dict[str, Any]] | None,
) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """INSERT INTO resources
               (resource_id, resource_type, resource_subtype, unit, value, state,
                attributes, settlements)
               VALUES (?, 'compute.gpu', 'h100', 'count', 1, 'available', ?, ?)""",
            (
                resource_id,
                json.dumps(
                    {
                        "gpu_model": "H100",
                        "sla": 99.0,
                        "region": "NY",
                        "virtualization_type": "vm",
                    }
                ),
                json.dumps(settlements) if settlements is not None else None,
            ),
        )
        conn.execute(
            """INSERT INTO compute_capacity_pools
               (pool_id, resource_type, gpu_model, region, sla, total_gpu_count,
                status, settlements)
               VALUES (?, 'compute.gpu', 'H100', 'NY', 99.0, 1, 'active', ?)""",
            (
                resource_id,
                json.dumps(settlements) if settlements is not None else None,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _run_round(db_path: str, command_settlements, monkeypatch):
    published_payloads: list[dict[str, Any]] = []

    def compile_clauses(values):
        return tuple(
            SettlementPublicationClause.model_validate(value) for value in values
        )

    def publish_offer(
        agent_url,
        offer,
        accepted_escrows,
        demands,
        max_duration_seconds,
        **payload,
    ):
        asyncio.run(
            SQLiteClient(db_path=db_path, registry=_VM_REGISTRY).upsert_listing(
                listing_id="listing-1",
                status="open",
                created_at="2026-08-15T00:00:00Z",
                updated_at="2026-08-15T00:00:00Z",
                offer_resource=offer,
                fulfillment_resource=None,
                max_duration_seconds=max_duration_seconds,
                storefront_url=agent_url,
                seller_principal=Identity(
                    scheme="ed25519",
                    identifier=(
                        "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
                    ),
                ),
            )
        )
        published_payloads.append(
            {
                "agent_url": agent_url,
                "offer": offer,
                "accepted_escrows": accepted_escrows,
                "demands": demands,
                "max_duration_seconds": max_duration_seconds,
                **payload,
            }
        )
        return {"status": "created", "listing_id": "listing-1"}

    monkeypatch.setattr(
        "market_storefront.cli_publish._site_topology_sync",
        lambda: ("site-a", 1),
    )
    conn = sqlite3.connect(db_path)
    try:
        resource_ids = [
            str(row[0])
            for row in conn.execute("SELECT resource_id FROM resources").fetchall()
        ]
    finally:
        conn.close()
    monkeypatch.setattr(
        "market_storefront.cli_publish._member_availability_sync",
        lambda: {("site-a", resource_id): 1 for resource_id in resource_ids},
    )
    monkeypatch.setattr(
        "market_storefront.cli_publish._site_pool_projection_if_enabled",
        lambda: {
            "site-a": [
                {
                    "resource_pool_id": resource_id,
                    "pool_metadata": {
                        "policy_tags": {"deliverable_modes": ["vm"]},
                    },
                    "resources": [
                        {
                            "physical_resource_id": resource_id,
                            "capacity": {"gpu_count": 1},
                            "available": {"gpu_count": 1},
                            "attributes": {"gpu_model": "H100"},
                            "enabled": True,
                        }
                    ],
                }
                for resource_id in resource_ids
            ]
        },
    )
    monkeypatch.setattr("market_storefront.cli_publish._publish_offer", publish_offer)
    monkeypatch.setattr(
        "market_storefront.utils.config.storefront_domain_registry",
        lambda: _VM_REGISTRY,
    )
    monkeypatch.setattr(
        "market_storefront.cli_publish._compile_publication_clauses",
        compile_clauses,
    )
    monkeypatch.setattr(
        "market_storefront.cli_publish._demands_for_publication_clauses",
        lambda *_args, **_kwargs: [],
    )
    result = _publish_command_round(
        db_path=db_path,
        base_url="http://agent",
        wallet_address="",
        default_max_duration_seconds=None,
        command_settlements=command_settlements,
    )
    return result, published_payloads


def test_resource_settlements_replace_command_settlements(tmp_path, monkeypatch):
    db_path = str(tmp_path / "agent.db")
    _init_db(db_path)
    resource_clauses = [
        _clause(
            "fiat.stripe.v1",
            asset="usd",
            rate="125",
            funding_profile="card.v1",
            interaction="interactive",
            funds_flow="separate_charges_transfers",
        )
    ]
    _insert_resource(
        db_path,
        "compute-resource-clauses",
        settlements=resource_clauses,
    )
    command_clauses = (
        SettlementPublicationClause(
            mechanism="alkahest.v1",
            asset="0x9fe46736679d2d9a65f0992f2272de9f3c7fa6e0",
            rate="100",
            per="hour",
            mechanism_input={
                "chain": "anvil",
                "escrow_kind": "erc20_escrow_obligation_default",
            },
        ),
    )

    result, payloads = _run_round(db_path, command_clauses, monkeypatch)

    assert not result.failed
    assert len(result.published) == 1
    assert [clause["mechanism"] for clause in payloads[0]["settlements"]] == [
        "fiat.stripe.v1"
    ]


def test_command_dual_mechanism_order_reaches_listing(tmp_path, monkeypatch):
    db_path = str(tmp_path / "agent.db")
    _init_db(db_path)
    _insert_resource(db_path, "compute-command-clauses", settlements=None)
    command_clauses = (
        SettlementPublicationClause(
            mechanism="alkahest.v1",
            asset="0x9fe46736679d2d9a65f0992f2272de9f3c7fa6e0",
            rate="100",
            per="hour",
            mechanism_input={
                "chain": "anvil",
                "escrow_kind": "erc20_escrow_obligation_default",
            },
        ),
        SettlementPublicationClause(
            mechanism="fiat.stripe.v1",
            asset="usd",
            rate="125",
            per="hour",
            mechanism_input={
                "funding_profile": "card.v1",
                "interaction": "interactive",
                "funds_flow": "separate_charges_transfers",
            },
        ),
    )

    result, payloads = _run_round(db_path, command_clauses, monkeypatch)

    assert not result.failed
    assert [clause["mechanism"] for clause in payloads[0]["settlements"]] == [
        "alkahest.v1",
        "fiat.stripe.v1",
    ]
