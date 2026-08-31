"""Immutable issuance evidence and private credential result persistence."""

from __future__ import annotations

import hashlib
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol

from domains.apicredits.settlement.issuance_evidence import (
    ApiCreditsIssuanceEvidenceBodyV1,
    ExpectedApiCreditsIssuanceEvidenceV1,
    SignedApiCreditsIssuanceEvidenceV1,
    canonical_signed_issuance_evidence,
    decode_signed_issuance_evidence,
    encode_portable_issuance_fulfillment_ref,
    issuance_evidence_digest,
    sign_api_credits_issuance_evidence,
    verify_api_credits_issuance_evidence,
)
from market_identity import Identity, Signer, TrustedIdentitySet
from pydantic import BaseModel, ConfigDict, Field


class IssuanceEvidenceConflict(RuntimeError):
    """An immutable evidence or credential identity was reused with changed data."""


class PrivateResultAccessError(PermissionError):
    """A canonical principal does not own the requested private result."""


class FulfillmentPublisher(Protocol):
    async def publish_fulfillment(
        self,
        *,
        condition_anchor: str,
        evidence: str | None,
    ) -> str: ...


class ApiCreditPrivateResult(BaseModel):
    """Domain-private bearer result; serialization and repr omit the secret."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    credentials_ref: str
    fulfillment_id: str
    owner: Identity
    key_id: str
    secret: str = Field(min_length=1, max_length=512, exclude=True, repr=False)


@dataclass(frozen=True)
class EvidencePublication:
    evidence_digest: str
    evidence: SignedApiCreditsIssuanceEvidenceV1
    canonical_evidence: str


@dataclass(frozen=True)
class PortableEvidencePublication:
    evidence_digest: str
    attestation_uid: str
    fulfillment_ref: str


class IssuanceEvidenceRepository:
    """SQLite repository keyed by digest and unique fulfillment identity."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)

    def store(
        self,
        evidence: SignedApiCreditsIssuanceEvidenceV1,
    ) -> EvidencePublication:
        canonical = canonical_signed_issuance_evidence(evidence)
        digest = issuance_evidence_digest(evidence)
        fulfillment_id = evidence.body.fulfillment_id
        connection = sqlite3.connect(self._db_path, timeout=30)
        try:
            connection.execute("BEGIN IMMEDIATE")
            by_digest = connection.execute(
                "SELECT fulfillment_id, signed_evidence "
                "FROM api_credit_issuance_evidence WHERE evidence_digest = ?",
                (digest,),
            ).fetchone()
            by_fulfillment = connection.execute(
                "SELECT evidence_digest, signed_evidence "
                "FROM api_credit_issuance_evidence WHERE fulfillment_id = ?",
                (fulfillment_id,),
            ).fetchone()
            if by_digest is not None:
                if by_digest != (fulfillment_id, canonical):
                    raise IssuanceEvidenceConflict(
                        "evidence digest is already bound to changed evidence"
                    )
                connection.commit()
                return EvidencePublication(digest, evidence, canonical)
            if by_fulfillment is not None:
                if by_fulfillment != (digest, canonical):
                    raise IssuanceEvidenceConflict(
                        "fulfillment_id is already bound to changed evidence"
                    )
                connection.commit()
                return EvidencePublication(digest, evidence, canonical)
            connection.execute(
                "INSERT INTO api_credit_issuance_evidence"
                "(evidence_digest, fulfillment_id, signed_evidence, created_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    digest,
                    fulfillment_id,
                    canonical,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            connection.commit()
            return EvidencePublication(digest, evidence, canonical)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get(self, evidence_digest: str) -> SignedApiCreditsIssuanceEvidenceV1 | None:
        connection = sqlite3.connect(self._db_path, timeout=30)
        try:
            row = connection.execute(
                "SELECT signed_evidence FROM api_credit_issuance_evidence "
                "WHERE evidence_digest = ?",
                (evidence_digest,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        evidence = decode_signed_issuance_evidence(str(row[0]))
        if issuance_evidence_digest(evidence) != evidence_digest:
            raise IssuanceEvidenceConflict(
                "stored issuance evidence no longer matches its digest"
            )
        return evidence


class ApiCreditPrivateResultRepository:
    """Owner-authenticated storage for a newly issued bearer credential."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)

    @staticmethod
    def credentials_ref(fulfillment_id: str, owner: Identity) -> str:
        digest = hashlib.sha256(
            (
                fulfillment_id
                + "\0"
                + owner.scheme.value
                + "\0"
                + owner.identifier
            ).encode("utf-8")
        ).hexdigest()
        return f"api-credit-credential.v1:{digest}"

    def store(
        self,
        *,
        fulfillment_id: str,
        owner: Identity,
        key_id: str,
        secret: str,
    ) -> ApiCreditPrivateResult:
        reference = self.credentials_ref(fulfillment_id, owner)
        public_binding = (
            fulfillment_id,
            owner.scheme.value,
            owner.identifier,
            key_id,
        )
        connection = sqlite3.connect(self._db_path, timeout=30)
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT fulfillment_id, owner_scheme, owner_id, key_id, secret "
                "FROM api_credit_private_results WHERE credentials_ref = ? ",
                (reference,),
            ).fetchone()
            by_fulfillment = connection.execute(
                "SELECT credentials_ref, owner_scheme, owner_id, key_id, secret "
                "FROM api_credit_private_results WHERE fulfillment_id = ?",
                (fulfillment_id,),
            ).fetchone()
            if row is not None and row[:4] != public_binding:
                raise IssuanceEvidenceConflict(
                    "credentials_ref is already bound to a changed private result"
                )
            expected_by_fulfillment = (
                reference,
                owner.scheme.value,
                owner.identifier,
                key_id,
            )
            if (
                by_fulfillment is not None
                and by_fulfillment[:4] != expected_by_fulfillment
            ):
                raise IssuanceEvidenceConflict(
                    "fulfillment_id is already bound to a changed private result"
                )
            if row is None and by_fulfillment is None:
                connection.execute(
                    "INSERT INTO api_credit_private_results"
                    "(credentials_ref, fulfillment_id, owner_scheme, owner_id, "
                    " key_id, secret, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        reference,
                        fulfillment_id,
                        owner.scheme.value,
                        owner.identifier,
                        key_id,
                        secret,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
            elif row is not None and row[4] != secret:
                connection.execute(
                    "UPDATE api_credit_private_results SET secret = ? "
                    "WHERE credentials_ref = ?",
                    (secret, reference),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return ApiCreditPrivateResult(
            credentials_ref=reference,
            fulfillment_id=fulfillment_id,
            owner=owner,
            key_id=key_id,
            secret=secret,
        )

    def get(
        self,
        *,
        credentials_ref: str,
        owner: Identity,
    ) -> ApiCreditPrivateResult | None:
        connection = sqlite3.connect(self._db_path, timeout=30)
        try:
            row = connection.execute(
                "SELECT fulfillment_id, owner_scheme, owner_id, key_id, secret "
                "FROM api_credit_private_results WHERE credentials_ref = ?",
                (credentials_ref,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        stored_owner = Identity(scheme=row[1], identifier=row[2])
        if stored_owner != owner:
            raise PrivateResultAccessError("private result belongs to another principal")
        return ApiCreditPrivateResult(
            credentials_ref=credentials_ref,
            fulfillment_id=row[0],
            owner=stored_owner,
            key_id=row[3],
            secret=row[4],
        )


class ApiCreditsIssuanceEvidenceService:
    """Signs, verifies, stores, resolves, and digest-publishes issuance evidence."""

    def __init__(
        self,
        repository: IssuanceEvidenceRepository,
        *,
        signer: Signer,
        trusted_issuers: TrustedIdentitySet,
        clock: Callable[[], int] = lambda: int(time.time()),
        max_future_skew_seconds: int = 30,
    ) -> None:
        if signer.identity not in trusted_issuers:
            raise ValueError("evidence signer is not in the trusted issuer set")
        self._repository = repository
        self._signer = signer
        self._trusted_issuers = trusted_issuers
        self._clock = clock
        self._max_future_skew_seconds = max_future_skew_seconds

    def publish(
        self,
        body: ApiCreditsIssuanceEvidenceBodyV1,
    ) -> EvidencePublication:
        evidence = sign_api_credits_issuance_evidence(body, self._signer)
        self._verify_self_consistent(evidence)
        return self._repository.store(evidence)

    def resolve(
        self,
        evidence_digest: str,
    ) -> SignedApiCreditsIssuanceEvidenceV1 | None:
        evidence = self._repository.get(evidence_digest)
        if evidence is None:
            return None
        self._verify_self_consistent(evidence)
        return evidence

    def resolve_verified(
        self,
        evidence_digest: str,
        *,
        expected: ExpectedApiCreditsIssuanceEvidenceV1,
    ) -> SignedApiCreditsIssuanceEvidenceV1 | None:
        evidence = self._repository.get(evidence_digest)
        if evidence is None:
            return None
        verify_api_credits_issuance_evidence(
            evidence,
            expected=expected,
            trusted_issuers=self._trusted_issuers,
            now_unix=self._clock(),
            max_future_skew_seconds=self._max_future_skew_seconds,
        )
        return evidence

    async def publish_portable(
        self,
        body: ApiCreditsIssuanceEvidenceBodyV1,
        *,
        publisher: FulfillmentPublisher,
        resolver_id: str,
    ) -> PortableEvidencePublication:
        publication = self.publish(body)
        attestation_uid = await publisher.publish_fulfillment(
            condition_anchor=body.condition_anchor,
            evidence=publication.canonical_evidence,
        )
        fulfillment_ref = encode_portable_issuance_fulfillment_ref(
            resolver_id=resolver_id,
            attestation_uid=attestation_uid,
            evidence_digest=publication.evidence_digest,
        )
        return PortableEvidencePublication(
            evidence_digest=publication.evidence_digest,
            attestation_uid=attestation_uid,
            fulfillment_ref=fulfillment_ref,
        )

    def _verify_self_consistent(
        self,
        evidence: SignedApiCreditsIssuanceEvidenceV1,
    ) -> None:
        body = evidence.body
        expected = ExpectedApiCreditsIssuanceEvidenceV1(
            condition_anchor=body.condition_anchor,
            obligation_ref=body.obligation_ref,
            fulfillment_id=body.fulfillment_id,
            grant_id=body.grant_id,
            service=body.service,
            resource_id=body.resource_id,
            quantity=body.quantity,
            key_mode=body.key_mode,
            key_id=body.key_id,
            owner=body.owner,
            buyer=body.buyer,
            claimant=body.claimant,
            issuer=body.issuer,
            request_digest=body.request_digest,
            funding_expiration_unix=body.committed_at_unix,
        )
        verify_api_credits_issuance_evidence(
            evidence,
            expected=expected,
            trusted_issuers=self._trusted_issuers,
            now_unix=self._clock(),
            max_future_skew_seconds=self._max_future_skew_seconds,
        )
