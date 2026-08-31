from __future__ import annotations

import sqlite3

import pytest
from market_identity import Ed25519Signer, TrustedIdentitySet

from apicredits_storefront.services.issuance_evidence import (
    ApiCreditPrivateResultRepository,
    ApiCreditsIssuanceEvidenceService,
    IssuanceEvidenceConflict,
    IssuanceEvidenceRepository,
    PrivateResultAccessError,
)
from apicredits_storefront.utils.migrations import _migrate_issuance_evidence
from domains.apicredits.settlement.issuance_evidence import (
    ApiCreditsIssuanceEvidenceBodyV1,
)


@pytest.fixture
def repositories(tmp_path):
    db_path = tmp_path / "storefront.db"
    with sqlite3.connect(db_path) as connection:
        _migrate_issuance_evidence(connection)
    return (
        IssuanceEvidenceRepository(db_path),
        ApiCreditPrivateResultRepository(db_path),
    )


def _body(*, quantity: int = 5):
    issuer = Ed25519Signer(bytes(range(32)))
    owner = Ed25519Signer(bytes(range(1, 33))).identity
    claimant = Ed25519Signer(bytes(range(2, 34))).identity
    body = ApiCreditsIssuanceEvidenceBodyV1(
        condition_anchor="condition:1",
        obligation_ref="obligation:1",
        fulfillment_id="api-credit-fulfillment.v1:" + "a" * 64,
        grant_id="api-credit-fulfillment.v1:" + "a" * 64,
        service="inference",
        resource_id="quota-main",
        quantity=quantity,
        key_mode="new",
        key_id="ak_public",
        owner=owner,
        buyer=owner,
        claimant=claimant,
        issuer=issuer.identity,
        committed_at_unix=2_000_000_000,
        request_digest="sha256:" + "b" * 64,
    )
    return issuer, body


def test_evidence_exact_replay_is_idempotent_and_changed_replay_conflicts(repositories):
    evidence_repository, _ = repositories
    signer, body = _body()
    service = ApiCreditsIssuanceEvidenceService(
        evidence_repository,
        signer=signer,
        trusted_issuers=TrustedIdentitySet(identities=(signer.identity,)),
        clock=lambda: 2_000_000_010,
    )

    first = service.publish(body)
    assert service.publish(body) == first
    assert service.resolve("sha256:" + "f" * 64) is None
    assert service.resolve(first.evidence_digest) == first.evidence

    _, changed = _body(quantity=6)
    with pytest.raises(IssuanceEvidenceConflict):
        service.publish(changed)


def test_private_result_is_owner_exact_secret_safe_and_rotatable(repositories):
    _, private_repository = repositories
    _, body = _body()
    first = private_repository.store(
        fulfillment_id=body.fulfillment_id,
        owner=body.owner,
        key_id=body.key_id,
        secret="ak_public.first-secret",
    )
    assert "first-secret" not in repr(first)
    assert "secret" not in first.model_dump(mode="json")

    replacement = private_repository.store(
        fulfillment_id=body.fulfillment_id,
        owner=body.owner,
        key_id=body.key_id,
        secret="ak_public.replacement-secret",
    )
    loaded = private_repository.get(
        credentials_ref=replacement.credentials_ref,
        owner=body.owner,
    )
    assert loaded is not None
    assert loaded.secret == "ak_public.replacement-secret"

    other = Ed25519Signer(bytes(range(3, 35))).identity
    with pytest.raises(PrivateResultAccessError):
        private_repository.get(
            credentials_ref=first.credentials_ref,
            owner=other,
        )
