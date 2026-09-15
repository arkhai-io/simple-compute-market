"""The credits service's own composition, over a live client.

`kit/site`'s integration suite covers the middleware against a stand-in app.
This covers *this service*: the real `main.app`, its two route tables composed
into one middleware, and its identity module resolving a credential and trust
sets from configuration.

The distinction matters because the bug being fixed was a composition bug, not
a middleware bug. The kit's router was mounted correctly and the kit's client
signed correctly; what was wrong was the gate sitting in front of them. A test
of either half in isolation would have passed throughout.

Configuration is written to a temp directory and the modules imported fresh,
because both `config` and `identity` resolve at import: that is deliberate --
an unreadable credential should fail while an operator is watching, not on a
request hours later -- and it means a test must control the environment before
the first import rather than patch afterwards.
"""

from __future__ import annotations

import importlib
import sys
import time
import uuid
from base64 import urlsafe_b64encode
from pathlib import Path
from typing import Any, Iterator

import httpx
import pytest
import pytest_asyncio
from market_identity import (
    EMPTY_BODY,
    Ed25519Signer,
    Identity,
    TrustedIdentitySet,
    RequestEnvelope,
    canonical_body_hash,
    sign_request,
)

AUTHORITY_SEED = b"credits-authority-seed-32-byte!!"
STOREFRONT_SIGNER = Ed25519Signer(b"credits-storefront-seed-32-byte!")
GATED_SIGNER = Ed25519Signer(b"credits-gatedapp-seed-32-bytes!!")
OPERATOR_SIGNER = Ed25519Signer(b"credits-operator-seed-32-bytes!!")
IMPOSTOR_SIGNER = Ed25519Signer(b"credits-impostor-seed-32-bytes!!")

_MODULES = ("main", "identity", "config", "container")

SIGNATURE_VERSION_HEADER = "X-Market-Signature-Version"
IDENTITY_SCHEME_HEADER = "X-Market-Identity-Scheme"
IDENTITY_IDENTIFIER_HEADER = "X-Market-Identity-Identifier"
ROLE_HEADER = "X-Market-Role"
REQUEST_ID_HEADER = "X-Market-Request-ID"
TIMESTAMP_HEADER = "X-Market-Timestamp"
SIGNATURE_HEADER = "X-Market-Signature"


def _write_config(directory: Path, *, with_identity: bool) -> Path:
    seed_file = directory / "site.ed25519"
    # Unpadded with a trailing newline, and left world-readable: that is
    # exactly how a committed dev identity arrives as a read-only bind mount.
    # A fixture with tidier bytes or tighter permissions would pass here while
    # the real thing failed in the stack.
    seed_file.write_bytes(urlsafe_b64encode(AUTHORITY_SEED).rstrip(b"=") + b"\n")
    seed_file.chmod(0o644)
    lines = [
        f'database_url = "sqlite:///{directory / "credits.db"}"',
        'storefront_admin_key = "fallback-secret"',
    ]
    if with_identity:
        lines += [
            f'site_signing_key_file = "{seed_file}"',
            "[trusted_principals]",
            f'seller = ["{STOREFRONT_SIGNER.identity.identifier}"]',
            f'service = ["{GATED_SIGNER.identity.identifier}"]',
            f'admin = ["{OPERATOR_SIGNER.identity.identifier}"]',
        ]
    config = directory / "config.yml"
    # dynaconf reads the TOML-shaped values this service already documents in
    # settings.toml; written as a config include so nothing here depends on
    # editing the committed defaults.
    (directory / "config.toml").write_text("\n".join(lines) + "\n")
    config.write_text("")
    return directory


def _load_app(directory: Path, monkeypatch, *, with_identity: bool):
    _write_config(directory, with_identity=with_identity)
    monkeypatch.setenv("CONFIG_DIRECTORY", str(directory))
    monkeypatch.setenv("APICREDITS_DATABASE_URL", f"sqlite:///{directory / 'credits.db'}")
    if with_identity:
        monkeypatch.setenv(
            "APICREDITS_SITE_SIGNING_KEY_FILE",
            str(directory / "site.ed25519"),
        )
        monkeypatch.setenv(
            "APICREDITS_TRUSTED_PRINCIPALS",
            "@json "
            + _json_roles(),
        )
    else:
        monkeypatch.delenv("APICREDITS_SITE_SIGNING_KEY_FILE", raising=False)
        monkeypatch.delenv("APICREDITS_TRUSTED_PRINCIPALS", raising=False)
    for name in _MODULES:
        sys.modules.pop(name, None)
    main = importlib.import_module("main")
    # `main` imports the container under an alias, so the module is reached
    # directly rather than through it.
    importlib.import_module("container").init()
    return main


def _json_roles() -> str:
    import json

    return json.dumps(
        {
            "seller": [STOREFRONT_SIGNER.identity.identifier],
            "service": [GATED_SIGNER.identity.identifier],
            "admin": [OPERATOR_SIGNER.identity.identifier],
        }
    )


@pytest.fixture
def signed_app(tmp_path: Path, monkeypatch) -> Iterator[Any]:
    main = _load_app(tmp_path, monkeypatch, with_identity=True)
    yield main.app
    for name in _MODULES:
        sys.modules.pop(name, None)


@pytest_asyncio.fixture
async def client(signed_app):
    transport = httpx.ASGITransport(app=signed_app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://credits-service"
    ) as http:
        yield http


def _headers(
    *,
    signer: Ed25519Signer,
    role: str,
    method: str,
    operation: str,
    resource: str,
    body: Any = EMPTY_BODY,
) -> dict[str, str]:
    authenticated = sign_request(
        signer=signer,
        envelope=RequestEnvelope(
            role=role,
            principal=signer.identity,
            method=method.upper(),
            operation=operation,
            resource=resource,
            request_id=str(uuid.uuid4()),
            timestamp=int(time.time()),
            body_hash=canonical_body_hash(body),
        ),
    )
    return {
        SIGNATURE_VERSION_HEADER: authenticated.protocol,
        IDENTITY_SCHEME_HEADER: authenticated.principal.scheme.value,
        IDENTITY_IDENTIFIER_HEADER: authenticated.principal.identifier,
        ROLE_HEADER: authenticated.role,
        REQUEST_ID_HEADER: authenticated.request_id,
        TIMESTAMP_HEADER: str(authenticated.timestamp),
        SIGNATURE_HEADER: authenticated.proof.value,
    }


def _assert_signed_by_authority(response: httpx.Response) -> None:
    assert response.headers.get(SIGNATURE_HEADER), (
        f"{response.request.method} {response.request.url.path} answered "
        f"{response.status_code} with no signature; the kit's client cannot "
        "read this outcome at all"
    )
    principal = Identity(
        scheme=response.headers[IDENTITY_SCHEME_HEADER],
        identifier=response.headers[IDENTITY_IDENTIFIER_HEADER],
    )
    assert principal == Ed25519Signer(AUTHORITY_SEED).identity


@pytest.mark.asyncio
async def test_the_storefronts_quota_registration_is_served(client):
    """The exact request that failed in the e2e run.

    `PUT /api/v1/capacity/resources/{id}` is what the storefront's demo seed
    calls at startup; it answered `401` under the admin-key gate, and the
    `401` was itself unsigned, so the seed failed on a missing response header
    rather than on the refusal.
    """
    response = await client.put(
        "/api/v1/capacity/resources/weather-quota",
        json={"total_units": 100, "resource_type": "api.credits"},
        headers=_headers(
            signer=STOREFRONT_SIGNER,
            role="seller",
            method="PUT",
            operation="capacity_resource_put",
            resource="weather-quota",
            body={"total_units": 100, "resource_type": "api.credits"},
        ),
    )
    assert response.status_code < 400, response.text
    _assert_signed_by_authority(response)


@pytest.mark.asyncio
async def test_the_capacity_event_feed_is_served_to_the_storefront(client):
    """The other route the storefront was locked out of.

    Its poller drives derived-listing reconciliation, so a `401` here is a
    storefront that never learns its own inventory changed.
    """
    # Signed over the canonical body, not over nothing. A GET carries no
    # body, and this route's behavior is decided entirely by `after` and
    # `limit`, so the authority folds those into the signed material --
    # see `market_site.auth.canonical_site_request_body`, and
    # `canonical_provisioning_request_body`'s matching entry for the same
    # path. Signing `EMPTY_BODY` here asserted the feed was reachable by a
    # caller that signs the way this test did; `market_site_client`, which
    # is the only caller there is, signs the query.
    from market_site.auth import canonical_site_request_body

    query = {"after": 0, "limit": 1}
    response = await client.get(
        "/api/v1/capacity/events?after=0&limit=1",
        headers=_headers(
            signer=STOREFRONT_SIGNER,
            role="seller",
            method="GET",
            operation="capacity_events",
            resource="",
            body=canonical_site_request_body(
                "GET", "/api/v1/capacity/events", query=query
            ),
        ),
    )
    assert response.status_code == 200, response.text
    _assert_signed_by_authority(response)


@pytest.mark.asyncio
async def test_an_unsigned_request_is_refused_with_a_signed_refusal(client):
    response = await client.get(
        "/api/v1/capacity/snapshot",
        headers={REQUEST_ID_HEADER: str(uuid.uuid4())},
    )
    assert response.status_code == 401
    _assert_signed_by_authority(response)


@pytest.mark.asyncio
async def test_the_gated_application_may_consume_but_not_issue(client):
    """The role split the widening was for.

    One shared secret could not express that the gated application spends
    credits while the storefront mints them. These two assertions are why the
    two components now hold different roles.
    """
    issue = await client.post(
        "/api/v1/issuance",
        json={"fulfillment_id": "f-1"},
        headers=_headers(
            signer=GATED_SIGNER,
            role="service",
            method="POST",
            operation="credits_issue",
            resource="f-1",
            body={"fulfillment_id": "f-1"},
        ),
    )
    assert issue.status_code == 403, issue.text
    _assert_signed_by_authority(issue)

    consume = await client.post(
        "/api/v1/keys/key-1/consume",
        json={"units": 1},
        headers=_headers(
            signer=GATED_SIGNER,
            role="service",
            method="POST",
            operation="credits_key_consume",
            resource="key-1",
            body={"units": 1},
        ),
    )
    # Reaches the handler: an unknown key is a 404 from the service, not a
    # 403 from authentication. What is asserted is that authentication
    # admitted the caller, not that the key exists.
    assert consume.status_code != 403, consume.text
    _assert_signed_by_authority(consume)


@pytest.mark.asyncio
async def test_the_storefront_may_not_consume_credits(client):
    """And the converse, so the split is not one-directional."""
    response = await client.post(
        "/api/v1/keys/key-1/consume",
        json={"units": 1},
        headers=_headers(
            signer=STOREFRONT_SIGNER,
            role="seller",
            method="POST",
            operation="credits_key_consume",
            resource="key-1",
            body={"units": 1},
        ),
    )
    assert response.status_code == 403
    _assert_signed_by_authority(response)


@pytest.mark.asyncio
async def test_an_untrusted_principal_in_a_valid_role_is_refused(client):
    response = await client.get(
        "/api/v1/capacity/snapshot",
        headers=_headers(
            signer=IMPOSTOR_SIGNER,
            role="seller",
            method="GET",
            operation="capacity_snapshot",
            resource="",
        ),
    )
    assert response.status_code == 403
    _assert_signed_by_authority(response)


@pytest.mark.asyncio
async def test_the_operator_role_reaches_a_seller_route(client):
    """`admin` is admitted everywhere, which is what makes it useful.

    The previous per-route enumeration is what left the operator role unable
    to reach some routes and inhibited testing.
    """
    response = await client.get(
        "/api/v1/capacity/snapshot",
        headers=_headers(
            signer=OPERATOR_SIGNER,
            role="admin",
            method="GET",
            operation="capacity_snapshot",
            resource="",
        ),
    )
    assert response.status_code == 200, response.text
    _assert_signed_by_authority(response)


@pytest.mark.asyncio
async def test_liveness_is_reachable_without_a_credential(client):
    for path in ("/health", "/api/v1/system/health"):
        response = await client.get(path)
        assert response.status_code == 200, (
            f"{path} requires a credential; an orchestrator holds none and "
            "would report this container unhealthy"
        )


def test_a_deployment_without_an_identity_keeps_the_shared_secret_gate(
    tmp_path: Path, monkeypatch
):
    """The fallback, asserted so it stays a fallback.

    A service holding trust sets but no credential could verify a request and
    answer it unsigned, which is the one failure the kit's client cannot read.
    Both halves are required before signed authentication engages.
    """
    main = _load_app(tmp_path, monkeypatch, with_identity=False)
    try:
        assert not main.signed_authentication_enabled()
        mounted = [m.cls.__name__ for m in main.app.user_middleware]
        assert any("AdminKey" in name for name in mounted), mounted
        assert not any("SiteAuth" in name for name in mounted), mounted
    finally:
        for name in _MODULES:
            sys.modules.pop(name, None)


# ---------------------------------------------------------------------------
# The canonical clients against this service
#
# The tests above sign by hand, which is right for exercising the middleware's
# own branches -- a hand-built envelope can express inputs no client will
# construct. It is also why a client/authority disagreement is invisible to
# them: both sides of the assertion are this suite's view of the envelope.
#
# These drive the real `CreditsServiceClient` (seller) and real `TokensClient`
# (service role) over `ASGITransport` against `signed_app` -- the real
# composition, the real route tables, a real database. Nothing about the
# envelope, the canonical body, or the response verification is reconstructed
# locally, so a client that signs what this service does not verify fails
# here rather than in a deployed stack.
# ---------------------------------------------------------------------------


def _seller_client(signed_app):
    from domains.apicredits.settlement import CreditsServiceClient

    return CreditsServiceClient(
        "http://credits-service",
        transport=httpx.ASGITransport(app=signed_app),
        signer=STOREFRONT_SIGNER,
        expected_authorities=TrustedIdentitySet(
            identities=(Ed25519Signer(AUTHORITY_SEED).identity,),
        ),
    )


def _gated_client(signed_app):
    # `arkhai-apicredits-middleware[signed]` is a declared dev dependency of
    # this service precisely so its boundary can be tested against the real
    # client rather than a hand-built envelope.
    from apicredits_middleware.client import TokensClient
    from apicredits_middleware.signing import (
        AuthoritySigning,
        build_trusted_authorities,
    )

    return TokensClient(
        service_url="http://credits-service",
        http=httpx.AsyncClient(
            transport=httpx.ASGITransport(app=signed_app),
            base_url="http://credits-service",
        ),
        signing=AuthoritySigning(
            signer=GATED_SIGNER,
            expected_authorities=build_trusted_authorities(
                [
                    {
                        "scheme": Ed25519Signer(AUTHORITY_SEED).identity.scheme.value,
                        "identifier": Ed25519Signer(AUTHORITY_SEED).identity.identifier,
                    }
                ]
            ),
        ),
    )


async def _seed_quota(signed_app, resource_id: str = "weather-quota", units: int = 100):
    """Register the quota an issuance draws on, through the capacity client.

    Issuance refuses when no quota resource can cover the request, which is
    the service behaving correctly -- credits are backed by declared capacity
    rather than minted on demand. The seller declares that capacity through
    `SiteCapacityAdminClient`, so seeding it here brings the third canonical
    client onto the same real application and makes the flow the deployed one.
    """
    from market_site_client import SiteCapacityAdminClient

    client = SiteCapacityAdminClient(
        "http://credits-service",
        signer=STOREFRONT_SIGNER,
        expected_authorities=TrustedIdentitySet(
            identities=(Ed25519Signer(AUTHORITY_SEED).identity,),
        ),
        transport=httpx.ASGITransport(app=signed_app),
    )
    return await client.register_resource(
        resource_id,
        total_units=units,
        resource_type="api.credits",
        attributes={"service": "weather-api"},
    )


def _issuance_request(obligation_ref: str, quantity: int = 5):
    """One issuance request, with its grant key derived rather than invented.

    `fulfillment_id` is a digest of the obligation reference, and the contract
    refuses a pair that does not agree -- which is what makes an issuance
    idempotent per obligation rather than per caller-chosen string.
    """
    from domains.apicredits.settlement.credits_client import (
        CreditIssuanceRequest,
        CreditKeyTarget,
        credit_issuance_request_digest,
        derive_credit_fulfillment_id,
    )

    fields: dict[str, Any] = {
        "fulfillment_id": derive_credit_fulfillment_id(obligation_ref),
        "obligation_ref": obligation_ref,
        "mechanism": "alkahest.v1",
        "owner": STOREFRONT_SIGNER.identity,
        "service": "weather-api",
        "resource_id": "weather-quota",
        "quantity": quantity,
        "key": CreditKeyTarget(mode="new"),
    }
    # The digest binds every field above, so it is computed rather than
    # supplied: a literal would be a second source of truth for what the
    # request says, and the contract refuses the two disagreeing.
    return CreditIssuanceRequest(
        **fields, request_digest=credit_issuance_request_digest(**fields)
    )


@pytest.mark.asyncio
async def test_the_canonical_clients_transact_against_this_service(signed_app):
    """Seller issues, gated app verifies and spends. Both canonical clients.

    The one shape the review found missing: real client, real transport, real
    application, real database. It is deliberately one flow rather than a
    matrix -- issuance is the only way a key exists, so a gated client cannot
    be exercised against this service without the seller client first, and
    running them together is what proves the two roles' envelopes are both
    accepted by the same composed authority.
    """
    await _seed_quota(signed_app)
    seller = _seller_client(signed_app)
    issued = await seller.submit_credit_issuance(_issuance_request("obl-1"))

    assert issued.quantity == 5
    assert issued.balance == 5

    # Spend, not verify: `CreditIssuanceResult` deliberately excludes the
    # bearer secret from serialization, and `verify` needs it. `consume` is
    # keyed by the grant alone, so it exercises the gated app's signed
    # envelope against this authority without the test holding material the
    # contract declines to hand back.
    gated = _gated_client(signed_app)
    spent = await gated.consume(
        key_id=issued.key_id, amount=2, idempotency_key="i-1"
    )
    assert spent.ok is True, spent
    assert spent.balance == 3

    # The same signed request again resolves to the recorded consumption
    # rather than spending twice -- the handler-side half of the exact-retry
    # contract, which is why `credits_key_consume` stays replay-safe.
    again = await gated.consume(
        key_id=issued.key_id, amount=2, idempotency_key="i-1"
    )
    assert again.balance == 3, again


@pytest.mark.asyncio
async def test_the_seller_client_reads_back_what_it_issued(signed_app):
    """`get_key` and `get_credit_issuance` over the same signed boundary."""
    await _seed_quota(signed_app)
    seller = _seller_client(signed_app)
    issued = await seller.submit_credit_issuance(_issuance_request("obl-2", 7))

    key = await seller.get_key(issued.key_id)
    assert key["balance"] == 7

    from domains.apicredits.settlement.credits_client import (
        derive_credit_fulfillment_id,
    )

    grant = await seller.get_credit_issuance(
        derive_credit_fulfillment_id("obl-2")
    )
    assert grant is not None
