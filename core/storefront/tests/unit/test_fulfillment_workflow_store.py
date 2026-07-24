import asyncio
import sqlite3

from core_storefront.sqlite_client import SQLiteClient


def _run(awaitable):
    return asyncio.run(awaitable)


def _client(tmp_path):
    return SQLiteClient(str(tmp_path / "storefront.db"))


def _insert_escrow(client, escrow_uid="escrow-1"):
    assert _run(client.insert_escrow(
        escrow_uid=escrow_uid,
        negotiation_id="neg-1",
        chain_name="local",
        escrow_address="0xescrow",
    ))


def test_capacity_hold_persists_trusted_site_id(tmp_path):
    client = _client(tmp_path)
    _run(client.save_capacity_hold(
        negotiation_id="neg-1",
        listing_id="listing-1",
        capacity_reservation_id="reservation-1",
        site_id="site-b",
        payload={"site": "untrusted-payload-value"},
    ))

    loaded = _run(client.load_capacity_hold(negotiation_id="neg-1"))

    assert loaded["site_id"] == "site-b"
    assert loaded["capacity_reservation_id"] == "reservation-1"


def test_fulfillment_workflow_round_trips_without_credentials(tmp_path):
    client = _client(tmp_path)
    _insert_escrow(client)
    assert _run(client.create_fulfillment_workflow(
        escrow_uid="escrow-1",
        site_id="site-b",
        capacity_reservation_id="reservation-1",
        schedule_request={"market": "vms", "requirements": {"gpu_count": 1}},
        begin_request={"fulfillment_request": {"kind": "vms.fulfillment"}},
    ))
    _run(client.update_fulfillment_workflow(
        escrow_uid="escrow-1",
        phase="accepted",
        settlement_resource={"settlement_resource_id": "host-1"},
        fulfillment_id="fulfillment-1",
        provisioned_resources=[{"domain_resource_ref": "vm-1"}],
        credential_generation=2,
    ))

    restarted = SQLiteClient(client.db_path)
    workflow = _run(restarted.load_fulfillment_workflow(escrow_uid="escrow-1"))

    assert workflow["site_id"] == "site-b"
    assert workflow["fulfillment_id"] == "fulfillment-1"
    assert workflow["credential_generation"] == 2
    assert workflow["provisioned_resources"] == [{"domain_resource_ref": "vm-1"}]
    with sqlite3.connect(client.db_path) as conn:
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(storefront_fulfillments)")
        }
        raw = conn.execute(
            "SELECT schedule_request, begin_request, provisioned_resources "
            "FROM storefront_fulfillments"
        ).fetchone()
    assert "credentials" not in columns
    assert "password" not in "".join(str(value) for value in raw)


def test_claims_are_non_overlapping_and_expired_claims_recover(tmp_path):
    client = _client(tmp_path)
    _insert_escrow(client, "escrow-1")
    assert _run(client.create_fulfillment_workflow(
        escrow_uid="escrow-1",
        site_id="site-a",
        capacity_reservation_id="reservation-1",
        schedule_request={},
        begin_request={},
    ))

    first = _run(client.claim_due_fulfillment_workflows(
        worker_id="worker-a", now_unix=100, lease_seconds=10,
    ))
    overlapping = _run(client.claim_due_fulfillment_workflows(
        worker_id="worker-b", now_unix=105, lease_seconds=10,
    ))
    reclaimed = _run(client.claim_due_fulfillment_workflows(
        worker_id="worker-b", now_unix=111, lease_seconds=10,
    ))

    assert [row["escrow_uid"] for row in first] == ["escrow-1"]
    assert overlapping == []
    assert [row["claimed_by"] for row in reclaimed] == ["worker-b"]


def test_chain_and_provisioning_fulfillment_ids_remain_distinct(tmp_path):
    client = _client(tmp_path)
    _insert_escrow(client)
    _run(client.update_escrow(
        escrow_uid="escrow-1", fulfillment_uid="chain-attestation-1"
    ))
    assert _run(client.create_fulfillment_workflow(
        escrow_uid="escrow-1",
        site_id="site-a",
        capacity_reservation_id="reservation-1",
        schedule_request={},
        begin_request={},
    ))
    _run(client.update_fulfillment_workflow(
        escrow_uid="escrow-1", fulfillment_id="provisioning-fulfillment-1"
    ))

    escrow = _run(client.load_escrow(escrow_uid="escrow-1"))
    workflow = _run(client.load_fulfillment_workflow(escrow_uid="escrow-1"))

    assert escrow["fulfillment_uid"] == "chain-attestation-1"
    assert workflow["fulfillment_id"] == "provisioning-fulfillment-1"
