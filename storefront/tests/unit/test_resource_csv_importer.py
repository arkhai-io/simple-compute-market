from __future__ import annotations

import re
from pathlib import Path

import pytest

from market_storefront.utils.sqlite_client import SQLiteClient
from service.config_loader import EscrowTemplate, RateSlot


def _write_csv(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


@pytest.mark.asyncio
async def test_upsert_resources_from_csv_reports_matched_and_unrecognized(tmp_path: Path):
    db_path = str(tmp_path / "agent.db")
    csv_path = tmp_path / "resources.csv"
    sqlite_client = SQLiteClient(db_path=db_path)

    _write_csv(
        csv_path,
        "\n".join(
            [
                "resource_id,resource_type,resource_subtype,unit,value,state,attribute.gpu_model,attribute.sla,attribute.region,attribute.vm_host,attribute.topic",
                "compute-1,compute.gpu,h200,count,2,available,H200,99.0,\"California, US\",vm1,",
                "info-1,information.note,,,,available,,,,,market-overview",
            ]
        ),
    )

    report = await sqlite_client.upsert_resources_from_csv(csv_path=str(csv_path))
    resources = await sqlite_client.list_resources()

    assert report["total_rows"] == 2
    assert report["imported_count"] == 2
    assert report["failed_count"] == 0
    assert report["matched_count"] == 1
    assert report["unrecognized_count"] == 1
    assert report["invalid_count"] == 0

    assert len(resources) == 2
    by_id = {r["resource_id"]: r for r in resources}
    assert by_id["compute-1"]["resource_type"] == "compute.gpu"
    assert by_id["compute-1"]["attributes"]["vm_host"] == "vm1"
    assert by_id["info-1"]["resource_type"] == "information.note"
    assert by_id["info-1"]["attributes"]["topic"] == "market-overview"


@pytest.mark.asyncio
async def test_upsert_resources_from_csv_invalid_known_schema_row_fails(tmp_path: Path):
    db_path = str(tmp_path / "agent.db")
    csv_path = tmp_path / "resources_invalid.csv"
    sqlite_client = SQLiteClient(db_path=db_path)

    # Missing attribute.sla for known compute.gpu schema should fail validation.
    _write_csv(
        csv_path,
        "\n".join(
            [
                "resource_id,resource_type,resource_subtype,unit,value,state,attribute.gpu_model,attribute.region,attribute.vm_host",
                "compute-bad-1,compute.gpu,h200,count,2,available,H200,\"California, US\",vm1",
            ]
        ),
    )

    report = await sqlite_client.upsert_resources_from_csv(csv_path=str(csv_path))
    resources = await sqlite_client.list_resources()

    assert report["total_rows"] == 1
    assert report["imported_count"] == 0
    assert report["failed_count"] == 1
    assert report["matched_count"] == 0
    assert report["unrecognized_count"] == 0
    assert report["invalid_count"] == 1
    assert len(report["rows"]) == 1
    assert report["rows"][0]["schema_status"] == "invalid"
    assert resources == []


@pytest.mark.asyncio
async def test_upsert_resources_from_csv_persists_per_row_pricing(tmp_path: Path):
    """min_price and token columns are first-class CSV fields; they should
    round-trip from CSV → resources.min_price/token, ready for the publish
    loop to read."""
    db_path = str(tmp_path / "agent.db")
    csv_path = tmp_path / "resources_priced.csv"
    sqlite_client = SQLiteClient(db_path=db_path)

    usdc = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
    _write_csv(
        csv_path,
        "\n".join(
            [
                "resource_id,resource_type,resource_subtype,unit,value,state,min_price,token,attribute.gpu_model,attribute.sla,attribute.region,attribute.vm_host",
                f"compute-priced,compute.gpu,h200,count,1,available,150,{usdc},H200,99.0,\"California, US\",vm1",
                "compute-default,compute.gpu,h200,count,1,available,,,H200,99.0,\"California, US\",vm2",
            ]
        ),
    )

    report = await sqlite_client.upsert_resources_from_csv(csv_path=str(csv_path))
    resources = await sqlite_client.list_resources()

    assert report["imported_count"] == 2
    by_id = {r["resource_id"]: r for r in resources}
    assert by_id["compute-priced"]["min_price"] == "150"
    assert by_id["compute-priced"]["token"] == usdc
    # Empty cells become NULL, signaling "fall back to [seller.pricing] defaults".
    assert by_id["compute-default"]["min_price"] is None
    assert by_id["compute-default"]["token"] is None


@pytest.mark.asyncio
async def test_upsert_resources_from_csv_generates_resource_id_when_missing(tmp_path: Path):
    db_path = str(tmp_path / "agent.db")
    csv_path = tmp_path / "resources_no_id.csv"
    sqlite_client = SQLiteClient(db_path=db_path)

    _write_csv(
        csv_path,
        "\n".join(
            [
                "resource_id,resource_type,state,attribute.topic",
                ",information.note,available,alpha",
            ]
        ),
    )

    report = await sqlite_client.upsert_resources_from_csv(csv_path=str(csv_path))
    resources = await sqlite_client.list_resources()

    assert report["total_rows"] == 1
    assert report["imported_count"] == 1
    assert report["failed_count"] == 0
    assert len(resources) == 1

    generated_id = resources[0]["resource_id"]
    assert isinstance(generated_id, str)
    assert re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        generated_id,
    )


@pytest.mark.asyncio
async def test_csv_accepted_escrows_column_round_trips_through_sqlite(tmp_path: Path):
    """``accepted_escrows`` CSV cells parse against the templates catalog at
    import time and store the materialized entries JSON-encoded; the
    resource list deserializes them back to plain lists ready for the
    publish loop."""
    db_path = str(tmp_path / "agent.db")
    csv_path = tmp_path / "resources_templates.csv"
    sqlite_client = SQLiteClient(db_path=db_path)

    usdc_template = EscrowTemplate(
        name="usdc",
        chain="anvil",
        escrow_address="0x" + "ab" * 20,
        literal_fields={"token": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"},
        rate_slots={"amount": RateSlot(field="amount", per="hour")},
    )

    _write_csv(
        csv_path,
        "\n".join([
            "resource_id,resource_type,state,accepted_escrows,attribute.topic",
            "info-1,information.note,available,usdc=200,market-overview",
        ]),
    )

    report = await sqlite_client.upsert_resources_from_csv(
        csv_path=str(csv_path),
        templates={"usdc": usdc_template},
    )
    resources = await sqlite_client.list_resources()

    assert report["imported_count"] == 1
    assert len(resources) == 1
    accepted = resources[0]["accepted_escrows"]
    assert accepted == [
        {
            "chain_name": "anvil",
            "escrow_address": "0x" + "ab" * 20,
            "literal_fields": {"token": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"},
            "rates": [{"field": "amount", "per": "hour", "value": "200"}],
        }
    ]


@pytest.mark.asyncio
async def test_csv_accepted_escrows_column_without_templates_errors(tmp_path: Path):
    """When the CSV references templates but the storefront passes no
    templates catalog, the import surfaces a row-level error rather than
    silently dropping the column."""
    db_path = str(tmp_path / "agent.db")
    csv_path = tmp_path / "resources_no_templates.csv"
    sqlite_client = SQLiteClient(db_path=db_path)

    _write_csv(
        csv_path,
        "\n".join([
            "resource_id,resource_type,state,accepted_escrows,attribute.topic",
            "info-1,information.note,available,usdc=200,market-overview",
        ]),
    )

    report = await sqlite_client.upsert_resources_from_csv(csv_path=str(csv_path))
    assert report["imported_count"] == 0
    assert report["failed_count"] == 1
    assert "no escrow_templates configured" in report["rows"][0]["errors"][0]


@pytest.mark.asyncio
async def test_csv_accepted_escrows_empty_cell_stores_null(tmp_path: Path):
    """An empty ``accepted_escrows`` cell is fine — the resource still
    imports, the column round-trips as ``None``."""
    db_path = str(tmp_path / "agent.db")
    csv_path = tmp_path / "resources_empty_ae.csv"
    sqlite_client = SQLiteClient(db_path=db_path)

    _write_csv(
        csv_path,
        "\n".join([
            "resource_id,resource_type,state,accepted_escrows,attribute.topic",
            "info-1,information.note,available,,market-overview",
        ]),
    )

    report = await sqlite_client.upsert_resources_from_csv(csv_path=str(csv_path))
    resources = await sqlite_client.list_resources()

    assert report["imported_count"] == 1
    assert resources[0]["accepted_escrows"] is None
