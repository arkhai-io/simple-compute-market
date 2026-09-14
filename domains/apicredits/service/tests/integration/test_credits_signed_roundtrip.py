"""The gated app's signed calls are accepted by the real credits gate.

Parity between the client's operation table and the service's is necessary
but not sufficient: the request also has to carry the right role, hash the
body the way the service rehashes it, and send the exact bytes it hashed.
Each of those fails as "signature did not verify", which a table comparison
cannot see.

So this drives the real `TokensClient` over `httpx.ASGITransport` against a
real `SiteAuthMiddleware` composed with the real
`CREDITS_ROUTE_CONTRACTS` and real ed25519 signers -- the same arrangement
the provisioning service's integration suite uses. Nothing about the
envelope is stubbed; only the handler bodies are.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from market_identity import Identity, TrustedIdentitySet, create_signer
from market_site.auth import SiteAuthMiddleware
from middleware.route_contracts import CREDITS_ROUTE_CONTRACTS
from apicredits_middleware.client import TokensClient
from apicredits_middleware.signing import (
    AuthoritySigning,
    build_signer,
    build_trusted_authorities,
)

#: The monorepo root, five levels up from this file, for the committed dev
#: identities. Nothing else is resolved by path: both clients and the
#: authority's route table are installed or importable here.
_REPO = Path(__file__).resolve().parents[5]
_IDENTITIES = _REPO / "dev-env/identities"


def _contracts():
    return CREDITS_ROUTE_CONTRACTS


def _only_role(role: str, identity: Identity):
    """Resolver admitting exactly one identity in exactly one role."""

    trusted = TrustedIdentitySet(identities=(identity,))

    def resolve(requested: str) -> TrustedIdentitySet:
        if requested != role:
            raise KeyError(f"no trusted principals for role {requested!r}")
        return trusted

    return resolve


def _seed(name: str) -> str:
    return (_IDENTITIES / f"{name}.ed25519").read_text(encoding="utf-8").strip()


@pytest.fixture(scope="module")
def signers():
    """The committed dev identities, so the test pins the deployed pair.

    Using the real seeds means a rotation that forgot to update the trust
    entries in `compose.yml` fails here too.
    """
    return {
        "authority": create_signer("ed25519", _seed("api-credits-service")),
        "gated_app": create_signer("ed25519", _seed("api-credits-gated-app")),
    }


@pytest.fixture
def gated_app_client(signers):
    """A `TokensClient` signing as the gated app, wired to the real gate."""
    authority = signers["authority"]
    gated = signers["gated_app"]

    app = FastAPI()

    @app.post("/api/v1/keys/{key_id}/verify")
    async def verify(key_id: str, request: Request):
        return {"valid": True, "status": "active", "balance": 41}

    @app.post("/api/v1/keys/{key_id}/consume")
    async def consume(key_id: str, request: Request):
        return {"ok": True, "balance": 40, "consumed": 1, "duplicate": False}

    @app.post("/api/v1/keys/consume-batch")
    async def consume_batch(request: Request):
        body = await request.json()
        return {
            "results": [
                {"ok": True, "balance": 39, "consumed": 1}
                for _ in body.get("items", [])
            ]
        }

    app.add_middleware(
        SiteAuthMiddleware,
        signer_provider=lambda: authority,
        # A callable, not a mapping: the middleware resolves per role and
        # a per-role resolver has no value meaning "trust nobody", so an
        # unknown role raises and becomes a signed 403 naming the gap.
        expected_principals=_only_role("service", gated.identity),
        contracts=_contracts(),
        max_timestamp_skew=300,
        excluded_paths=frozenset({"/health"}),
    )

    signing = AuthoritySigning(
        signer=build_signer(_seed("api-credits-gated-app")),
        expected_authorities=build_trusted_authorities(
            [
                {
                    "scheme": "ed25519",
                    "identifier": authority.identity.identifier,
                }
            ]
        ),
    )
    http = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://credits-service",
    )
    return TokensClient(
        service_url="http://credits-service", http=http, signing=signing,
    )


async def test_verify_is_accepted_and_its_response_verified(gated_app_client):
    result = await gated_app_client.verify(key_id="key-1", secret="s3cret")
    assert result.valid is True
    assert result.balance == 41


async def test_consume_is_accepted_and_its_response_verified(gated_app_client):
    result = await gated_app_client.consume(key_id="key-1", amount=1)
    assert result.ok is True, result
    assert result.consumed == 1


async def test_consume_batch_signs_the_empty_resource_and_is_accepted(
    gated_app_client,
):
    """The one route whose resource is not a path segment."""
    results = await gated_app_client.consume_batch(
        [{"key_id": "key-1", "amount": 1}, {"key_id": "key-2", "amount": 1}]
    )
    assert [r.ok for r in results] == [True, True], results


async def test_an_untrusted_gated_app_is_refused(signers):
    """A signature from an identity outside the trust set does not pass.

    Guards the test above against being vacuous: if the gate admitted
    anything, the acceptance results would prove nothing.
    """
    authority = signers["authority"]
    app = FastAPI()

    @app.post("/api/v1/keys/{key_id}/verify")
    async def verify(key_id: str, request: Request):
        return {"valid": True, "status": "active", "balance": 41}

    app.add_middleware(
        SiteAuthMiddleware,
        signer_provider=lambda: authority,
        # Trusts the authority's own identity in the `service` role, so the
        # gated app's genuine signature is from an untrusted principal.
        expected_principals=_only_role(
            "service",
            Identity(
                scheme="ed25519",
                identifier=authority.identity.identifier,
            ),
        ),
        contracts=_contracts(),
        max_timestamp_skew=300,
        excluded_paths=frozenset({"/health"}),
    )

    signing = AuthoritySigning(
        signer=build_signer(_seed("api-credits-gated-app")),
        expected_authorities=build_trusted_authorities(
            [
                {
                    "scheme": "ed25519",
                    "identifier": authority.identity.identifier,
                }
            ]
        ),
    )
    client = TokensClient(
        service_url="http://credits-service",
        http=httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://credits-service",
        ),
        signing=signing,
    )

    # Denied, and the gate's refusal is itself signed, so the client can read
    # it rather than failing on a missing response-auth header.
    result = await client.verify(key_id="key-1", secret="s3cret")
    assert result.valid is False


# ---------------------------------------------------------------------------
# The storefront's half of the same boundary, signing as `seller`.
#
# Separate identity, separate scheme (the storefront signs eip191 in
# deployment, ed25519 here is irrelevant to what is being checked: the
# envelope is scheme-neutral and `create_signer` dispatches), and a
# different operation set. `credits_issue` is the one whose signed resource
# comes out of the request body, so it gets its own case.
# ---------------------------------------------------------------------------


@pytest.fixture
def storefront_client(signers):
    from domains.apicredits.settlement import CreditsServiceClient

    authority = signers["authority"]
    seller = create_signer("ed25519", _seed("api-credits-registry"))

    app = FastAPI()

    @app.get("/api/v1/keys/{key_id}")
    async def get_key(key_id: str):
        return {"key_id": key_id, "status": "active", "balance": 7}

    @app.post("/api/v1/keys/{key_id}/revoke")
    async def revoke(key_id: str):
        return {"key_id": key_id, "status": "revoked"}

    @app.post("/api/v1/keys/{key_id}/adjust")
    async def adjust(key_id: str, request: Request):
        body = await request.json()
        return {"key_id": key_id, "balance": 7 + int(body["delta"])}

    @app.get("/api/v1/issuance/{fulfillment_id}")
    async def get_issuance(fulfillment_id: str):
        # 404 rather than a synthesized grant: this case exists to show the
        # signed GET is accepted and its *refusal* verifies, and fabricating
        # a full `CreditIssuanceResult` here would test the model, not the
        # envelope. Under the old shared-secret gate an unsigned 404 was
        # exactly what the kit's client could not read.
        return JSONResponse({"error": "not_found"}, status_code=404)

    app.add_middleware(
        SiteAuthMiddleware,
        signer_provider=lambda: authority,
        expected_principals=_only_role("seller", seller.identity),
        contracts=_contracts(),
        max_timestamp_skew=300,
        excluded_paths=frozenset({"/health"}),
    )

    return CreditsServiceClient(
        "http://credits-service",
        transport=httpx.ASGITransport(app=app),
        signer=seller,
        expected_authorities=TrustedIdentitySet(
            identities=(authority.identity,),
        ),
    )


async def test_storefront_get_key_is_accepted(storefront_client):
    key = await storefront_client.get_key("key-1")
    assert key == {"key_id": "key-1", "status": "active", "balance": 7}


async def test_storefront_revoke_is_accepted(storefront_client):
    result = await storefront_client.revoke_key("key-1")
    assert result["status"] == "revoked"


async def test_storefront_adjust_signs_its_body(storefront_client):
    """A body-bearing POST: the bytes hashed must be the bytes sent."""
    result = await storefront_client.adjust_key_balance(
        "key-1", delta=-3, reason="rollback:test"
    )
    assert result["balance"] == 4


async def test_storefront_issuance_get_refusal_is_signed_and_readable(
    storefront_client,
):
    """A signed 404 reads as "no such grant", not as an auth failure."""
    assert await storefront_client.get_credit_issuance("fulfil-1") is None


async def test_storefront_signing_requires_both_halves():
    """Signing requests without verifying responses is refused outright.

    Not a style preference: it would authenticate the question and accept
    an unauthenticated answer, which is the weaker of the two properties
    silently replacing the stronger.
    """
    from domains.apicredits.settlement import CreditsServiceClient

    signer = create_signer("ed25519", _seed("api-credits-registry"))
    with pytest.raises(ValueError, match="together"):
        CreditsServiceClient("http://credits-service", signer=signer)
    with pytest.raises(ValueError, match="together"):
        CreditsServiceClient(
            "http://credits-service",
            expected_authorities=TrustedIdentitySet(
                identities=(signer.identity,),
            ),
        )
