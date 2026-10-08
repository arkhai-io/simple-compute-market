"""The lease-ready evidence route: wire model, contract, route service, client.

A storefront serves a deal's lease-ready evidence by its digest, signed with the
storefront's own proof, to the deal's parties only, each under its own role: the
buyer as ``buyer``, the claimant as ``seller``, the seller's administrator as
``admin``. An Alkahest deal publishes the digest on a public chain
and the evidence names the deal's parties, which is why the body is not public.

The route contract here is what the storefront's binding authenticates with and
what the typed client signs, so the two cannot disagree. The route service is
framework-free; the storefront binds it and supplies its collaborators. See
docs/development/ARCHITECTURE.md, "Route contracts and their HTTP binding".
"""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict

from .evidence import BareMetalLeaseReadyEvidence, CanonicalPrincipal

# -- wire model ---------------------------------------------------------------

EVIDENCE_SIGNATURE_PROTOCOL = "arkhai.bare-metal-evidence-signature.v1"


class BareMetalSignedLeaseReadyEvidence(BaseModel):
    """The evidence, the storefront that holds it, and its proof over the body."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol: Literal["arkhai.bare-metal-evidence-signature.v1"] = (
        EVIDENCE_SIGNATURE_PROTOCOL
    )
    seller_principal: CanonicalPrincipal
    evidence: BareMetalLeaseReadyEvidence
    # URL-safe base64, unpadded, of the seller's signature over the evidence's
    # canonical JSON.
    proof: str


# -- route contract -----------------------------------------------------------

EVIDENCE_METHOD = "GET"
EVIDENCE_PATH = "/api/v1/evidence/bare-metal/{evidence_digest}"
EVIDENCE_OPERATION = "resolve_bare_metal_lease_ready_evidence"
#: The roles a reader may sign as; which principals each admits depends on the
#: evidence (``BareMetalEvidenceRouteService.readers``).
EVIDENCE_READER_ROLES = ("buyer", "seller", "admin")

_HEX_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class BareMetalEvidenceContractError(ValueError):
    """A digest that names no evidence the route could serve."""


def evidence_resource(evidence_digest: str) -> str:
    """The resource a request signs: the digest's 64 hex characters.

    Accepts the digest with or without its ``sha256:`` prefix.
    """
    value = evidence_digest.removeprefix("sha256:")
    if _HEX_DIGEST.fullmatch(value) is None:
        raise BareMetalEvidenceContractError(
            "an evidence digest is 64 lower-case hex characters"
        )
    return value


def evidence_path(evidence_digest: str) -> str:
    return EVIDENCE_PATH.format(evidence_digest=evidence_resource(evidence_digest))


# -- route service ------------------------------------------------------------


class BareMetalEvidenceRouteError(Exception):
    """A refusal, carrying the HTTP status and detail the binding answers with."""

    def __init__(self, status_code: int, detail: Any) -> None:
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail


class BareMetalEvidenceRouteService:
    """Find a deal's evidence, say who may read it, and sign it for them."""

    def __init__(
        self,
        *,
        load_evidence: Callable[[str], Awaitable[BareMetalLeaseReadyEvidence | None]],
        seller_principal: CanonicalPrincipal,
        sign: Callable[[bytes], bytes],
        admin_principals: tuple[CanonicalPrincipal, ...],
    ) -> None:
        self._load = load_evidence
        self._seller = seller_principal
        self._sign = sign
        self._admins = tuple(admin_principals)

    async def evidence(self, evidence_digest: str) -> BareMetalLeaseReadyEvidence:
        """The evidence the path's digest names, or a 404 refusal."""
        try:
            resource = evidence_resource(evidence_digest)
        except BareMetalEvidenceContractError as exc:
            raise BareMetalEvidenceRouteError(404, "evidence not found") from exc
        evidence = await self._load("sha256:" + resource)
        if evidence is None:
            raise BareMetalEvidenceRouteError(404, "evidence not found")
        return evidence

    def readers(
        self, evidence: BareMetalLeaseReadyEvidence
    ) -> Mapping[str, tuple[CanonicalPrincipal, ...]]:
        """Who may read ``evidence``, by the role each signs as."""
        readers: dict[str, tuple[CanonicalPrincipal, ...]] = {
            "buyer": (evidence.buyer_principal,),
            "seller": (evidence.claimant_principal,),
            "admin": self._admins,
        }
        return readers

    def respond(
        self, evidence: BareMetalLeaseReadyEvidence
    ) -> BareMetalSignedLeaseReadyEvidence:
        """The evidence with the storefront's proof over its canonical form."""
        proof = base64.urlsafe_b64encode(
            self._sign(evidence.canonical_json().encode("utf-8"))
        ).rstrip(b"=").decode("ascii")
        return BareMetalSignedLeaseReadyEvidence(
            seller_principal=self._seller, evidence=evidence, proof=proof
        )


# -- typed client -------------------------------------------------------------


class _Transport(Protocol):
    def authenticated_request(self, method: str, path: str, **kwargs: Any) -> Any: ...


def _request(evidence_digest: str, role: str) -> tuple[tuple[str, str], dict[str, Any]]:
    if role not in EVIDENCE_READER_ROLES:
        raise BareMetalEvidenceContractError(f"no evidence reader signs as {role!r}")
    return (EVIDENCE_METHOD, evidence_path(evidence_digest)), {
        "role": role,
        "operation": EVIDENCE_OPERATION,
        "resource": evidence_resource(evidence_digest),
    }


def _parsed(payload: Any) -> BareMetalSignedLeaseReadyEvidence:
    # The evidence models are strict, so the JSON the transport decoded is
    # validated as JSON, where a timestamp's string form is its wire form.
    return BareMetalSignedLeaseReadyEvidence.model_validate_json(json.dumps(payload))


class BareMetalEvidenceClient:
    """Lease-ready evidence over an async storefront client's generic transport.

    ``role`` is the role the wrapped client signs as; the storefront admits the
    deal's parties under the roles ``EVIDENCE_READER_ROLES`` names.
    """

    def __init__(self, client: _Transport, *, role: str) -> None:
        self._client = client
        self._role = role

    async def lease_ready_evidence(
        self, evidence_digest: str, *, request_id: str | None = None
    ) -> BareMetalSignedLeaseReadyEvidence:
        args, kwargs = _request(evidence_digest, self._role)
        return _parsed(
            await self._client.authenticated_request(
                *args, **kwargs, request_id=request_id
            )
        )


class SyncBareMetalEvidenceClient:
    """The same, over a sync storefront client's generic transport."""

    def __init__(self, client: _Transport, *, role: str) -> None:
        self._client = client
        self._role = role

    def lease_ready_evidence(
        self, evidence_digest: str, *, request_id: str | None = None
    ) -> BareMetalSignedLeaseReadyEvidence:
        args, kwargs = _request(evidence_digest, self._role)
        return _parsed(
            self._client.authenticated_request(*args, **kwargs, request_id=request_id)
        )


__all__ = [
    "BareMetalEvidenceClient",
    "BareMetalEvidenceContractError",
    "BareMetalEvidenceRouteError",
    "BareMetalEvidenceRouteService",
    "BareMetalSignedLeaseReadyEvidence",
    "EVIDENCE_METHOD",
    "EVIDENCE_OPERATION",
    "EVIDENCE_PATH",
    "EVIDENCE_READER_ROLES",
    "EVIDENCE_SIGNATURE_PROTOCOL",
    "SyncBareMetalEvidenceClient",
    "evidence_path",
    "evidence_resource",
]
