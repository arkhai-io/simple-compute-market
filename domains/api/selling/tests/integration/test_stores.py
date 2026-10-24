"""The selling stores against real SQLite, in tables named from a neutral domain's prefix."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from typing import Any

import pytest
from arkhai_api.evidence import IssuanceEvidenceBodyV1
from arkhai_api.issuance import issuance_result_model
from market_core import SettlementEvidence
from market_identity import TrustedIdentitySet

from arkhai_api_selling.evidence_store import (
    IssuanceEvidenceConflict,
    IssuanceEvidenceRepository,
    IssuanceEvidenceService,
    PrivateResultAccessError,
    PrivateResultRepository,
)
from arkhai_api_selling.issuance import persist_delivery, prepare_issuance_request, progress_result
from arkhai_api_selling.persistence import StorefrontSQLiteClient
from arkhai_api_selling.settlement_store import SettlementRepository
from tests.bundles import BUYER, CLAIMANT, EXAMPLE, ISSUER, STRANGER, create_tables, with_extension


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "storefront.db"
    create_tables(path)
    return path


def _body(*, quantity: int = 5) -> IssuanceEvidenceBodyV1:
    return IssuanceEvidenceBodyV1(
        domain=EXAMPLE.label.name,
        condition_anchor="condition:1",
        obligation_ref="obligation:1",
        fulfillment_id="example-fulfillment.v1:" + "a" * 64,
        grant_id="example-fulfillment.v1:" + "a" * 64,
        service="alpha",
        resource_id="quota-a",
        quantity=quantity,
        key_mode="new",
        key_id="ak_public",
        owner=BUYER,
        buyer=BUYER,
        claimant=CLAIMANT,
        issuer=ISSUER.identity,
        committed_at_unix=2_000_000_000,
        request_digest="sha256:" + "b" * 64,
    )


def _service(db_path) -> IssuanceEvidenceService:
    return IssuanceEvidenceService(
        IssuanceEvidenceRepository(db_path, EXAMPLE),
        contributions=EXAMPLE,
        signer=ISSUER,
        trusted_issuers=TrustedIdentitySet(identities=(ISSUER.identity,)),
        clock=lambda: 2_000_000_010,
    )


def test_evidence_exact_replay_is_idempotent_and_changed_replay_conflicts(db_path):
    service = _service(db_path)

    first = service.publish(_body())
    assert service.publish(_body()) == first
    assert service.resolve("sha256:" + "f" * 64) is None
    assert service.resolve(first.evidence_digest) == first.evidence
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM example_issuance_evidence").fetchone() == (1,)

    with pytest.raises(IssuanceEvidenceConflict):
        service.publish(_body(quantity=6))


def test_evidence_is_signed_under_the_bundles_label(db_path):
    publication = _service(db_path).publish(_body())
    assert publication.evidence.body.protocol == "arkhai.example.issuance-evidence.v1"
    assert _service(db_path).body(**_body().model_dump(exclude={"protocol", "capability", "domain"})) == _body()


def test_private_result_is_owner_exact_secret_safe_and_rotatable(db_path):
    repository = PrivateResultRepository(db_path, EXAMPLE)
    body = _body()
    first = repository.store(
        fulfillment_id=body.fulfillment_id, owner=BUYER, key_id=body.key_id,
        secret="ak_public.first-secret",
    )
    assert first.credentials_ref.startswith("example-credential.v1:")
    assert "first-secret" not in repr(first)
    assert "secret" not in first.model_dump(mode="json")

    replacement = repository.store(
        fulfillment_id=body.fulfillment_id, owner=BUYER, key_id=body.key_id,
        secret="ak_public.replacement-secret",
    )
    loaded = repository.get(credentials_ref=replacement.credentials_ref, owner=BUYER)
    assert loaded is not None and loaded.secret == "ak_public.replacement-secret"

    with pytest.raises(PrivateResultAccessError):
        repository.get(credentials_ref=first.credentials_ref, owner=STRANGER)


def _evidence(status: str = "verified", negotiation_id: str = "neg-1") -> SettlementEvidence:
    return SettlementEvidence(
        negotiation_id, "opaque.future.v1", f"ref-{negotiation_id}", status,
        {"kind": EXAMPLE.settlement_evidence_kind, "schema_version": 1,
         "agreement_digest": "a" * 64, "source": {"verified_source": "fixture"},
         "delivery": {"owner": BUYER.model_dump(mode="json"),
                      "listing_resource": {"product": "alpha", "quota": "quota-a"},
                      "quantity": 3, "key_mode": "new", "key_id": None, "listing_id": "L-1"}},
    )


def test_verified_evidence_is_immutable_and_refund_intent_stops_delivery(db_path):
    repository = SettlementRepository(str(db_path), EXAMPLE)
    repository.store(_evidence())
    assert repository.get("neg-1").status == "verified"
    with pytest.raises(ValueError, match="immutable"):
        repository.store(_evidence(status="failed"))

    repository.checkpoint("neg-1", public_ref="neg-1", status="provisioning")
    assert repository.record_refund_intent("neg-1") == {"status": "verified", "delivery_started": False}
    assert repository.claim_delivery_start("neg-1") is False
    repository.abandon_refund_intent("neg-1", prior_status="verified")
    assert repository.claim_delivery_start("neg-1") is True


def test_public_progress_refuses_credentials(db_path):
    repository = SettlementRepository(str(db_path), EXAMPLE)
    with pytest.raises(ValueError, match="private results"):
        repository.checkpoint("neg-1", public_ref="neg-1", status="ready", public_result={"secret": "s"})


def test_another_bundles_envelope_is_refused(db_path):
    other = SettlementEvidence(
        "neg-2", "opaque.future.v1", "ref-2", "verified",
        {**_evidence().evidence, "kind": "other.settlement-evidence.v1"},
    )
    with pytest.raises(ValueError, match="unsupported"):
        SettlementRepository(str(db_path), EXAMPLE).store(other)


def test_progress_is_read_by_negotiation_or_public_reference(db_path):
    repository = SettlementRepository(str(db_path), EXAMPLE)
    repository.checkpoint("neg-1", public_ref="0xdeal", status="provisioning")

    assert repository.progress("neg-1")["public_ref"] == "0xdeal"
    assert repository.progress("0xdeal")["negotiation_id"] == "neg-1"
    with pytest.raises(ValueError, match="established identity"):
        repository.checkpoint("neg-1", public_ref="0xother", status="ready")


def _accept(db_path, negotiation_id: str, mechanism: str, created_at: str) -> None:
    """An accepted thread under ``mechanism``, created at ``created_at``."""
    agreement = json.dumps({"settlement": {"mechanism": mechanism}})
    client = StorefrontSQLiteClient(str(db_path), EXAMPLE)
    with sqlite3.connect(db_path) as conn:
        client.insert_negotiation_thread(
            conn,
            negotiation_id=negotiation_id,
            our_listing_id="L-1",
            their_listing_id="",
            our_agent_id="https://seller.example",
            their_agent_id="https://buyer.example",
            buyer_principal=BUYER,
            seller_principal=CLAIMANT,
            owner_id="https://seller.example",
        )
        conn.execute(
            "UPDATE negotiation_threads SET terminal_state = 'success', agreement_bytes = ?, created_at = ? "
            "WHERE negotiation_id = ?",
            (agreement.encode(), created_at, negotiation_id),
        )


def test_unsettled_negotiations_are_the_open_deals_of_one_mechanism_oldest_first(db_path):
    repository = SettlementRepository(str(db_path), EXAMPLE)
    _accept(db_path, "neg-1", "opaque.future.v1", "2026-01-01T00:00:01Z")
    _accept(db_path, "neg-2", "opaque.future.v1", "2026-01-01T00:00:00Z")
    _accept(db_path, "neg-3", "other.v1", "2026-01-01T00:00:02Z")
    _accept(db_path, "neg-4", "opaque.future.v1", "2026-01-01T00:00:03Z")
    repository.store(_evidence())
    repository.checkpoint("neg-1", public_ref="neg-1", status="ready")
    repository.store(_evidence(negotiation_id="neg-4"))
    repository.checkpoint("neg-4", public_ref="neg-4", status="provisioning")

    # neg-1 is delivered; neg-2 has no evidence; neg-3 is another mechanism's;
    # neg-4 is verified and still delivering.
    assert repository.unsettled_negotiations(mechanism="opaque.future.v1", limit=10) == ["neg-2", "neg-4"]
    assert repository.unsettled_negotiations(mechanism="opaque.future.v1", limit=1) == ["neg-2"]


@pytest.mark.parametrize("terminal", ["ready", "failed"])
def test_terminal_progress_is_never_written_back(db_path, terminal):
    repository = SettlementRepository(str(db_path), EXAMPLE)
    repository.checkpoint("neg-1", public_ref="neg-1", status="provisioning")
    repository.checkpoint("neg-1", public_ref="neg-1", status=terminal, reason="first")

    for other in {"provisioning", "ready", "failed"} - {terminal}:
        with pytest.raises(ValueError, match=f"already {terminal}"):
            repository.checkpoint("neg-1", public_ref="neg-1", status=other)
    replayed = repository.checkpoint(
        "neg-1", public_ref="neg-1", status=terminal, reason="again", public_result={"key_id": "ak_x"}
    )
    assert (replayed["status"], replayed["reason"], replayed["public_result"]) == (terminal, "first", {})


def test_a_refund_completes_only_from_refunding(db_path):
    repository = SettlementRepository(str(db_path), EXAMPLE)
    repository.store(_evidence())
    repository.complete_refund("neg-1")
    assert repository.get("neg-1").status == "verified"

    repository.record_refund_intent("neg-1")
    repository.complete_refund("neg-1")
    assert repository.get("neg-1").status == "refunded"


class _Storefront:
    """The storefront repository surface the issuance helpers read, over the real stores."""

    def __init__(self, db_path) -> None:
        self.db_path = str(db_path)
        self._settlement = SettlementRepository(self.db_path, EXAMPLE)

    async def load_settlement_evidence(self, *, negotiation_id: str) -> SettlementEvidence | None:
        return await asyncio.to_thread(self._settlement.get, negotiation_id)

    async def save_issuance_progress(self, *, negotiation_id: str, **fields: Any) -> dict[str, Any]:
        return await asyncio.to_thread(self._settlement.checkpoint, negotiation_id, **fields)


def _issued(evidence: SettlementEvidence, *, extension=None) -> dict[str, Any]:
    request = prepare_issuance_request(EXAMPLE, evidence=evidence)
    issuance = issuance_result_model(EXAMPLE.label)(
        fulfillment_id=request.fulfillment_id, grant_id=request.fulfillment_id,
        negotiation_id=request.negotiation_id, owner=request.owner, service=request.service,
        resource_id=request.resource_id, quantity=request.quantity, key_mode="new",
        key_id="ak_new", balance=3, request_digest=request.request_digest,
        committed_at_unix=1_790_000_000, already_issued=False, secret="ak_new.s3cret",
    )
    result = {
        "status": "fulfilled", "message": "issued", "fulfillment_uid": issuance.fulfillment_id,
        "connection_details": "{}", "issuance": issuance,
        "tenant_credentials": {"key_id": "ak_new", "balance": 3, "secret": "ak_new.s3cret"},
    }
    if extension is not None:
        result["public_extension"] = extension
    return result


async def test_a_delivery_keeps_its_secret_private_beside_an_extension_and_returns_it_to_its_owner(db_path):
    store = _Storefront(db_path)
    evidence = _evidence()
    store._settlement.store(evidence)
    bundle = with_extension(lambda _listing, _result: {})

    row = await persist_delivery(
        bundle, store, evidence, _issued(evidence, extension={"materialization": {"product": "alpha"}}),
        public_ref="neg-1",
    )

    assert row["status"] == "ready"
    assert row["public_result"]["materialization"] == {"product": "alpha"}
    assert "s3cret" not in json.dumps(row["public_result"])
    assert row["credentials_ref"].startswith("example-credential.v1:")

    answer = await progress_result(EXAMPLE, store, row, buyer=BUYER, seller=CLAIMANT)
    assert answer.status_code == 200
    assert answer.payload["tenant_credentials"]["secret"] == "ak_new.s3cret"
    with pytest.raises(PermissionError):
        await progress_result(EXAMPLE, store, row, buyer=STRANGER, seller=CLAIMANT)
