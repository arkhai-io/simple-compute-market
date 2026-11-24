"""Buyer posting and discovery through the deployed registry's HTTP routes."""

from base64 import urlsafe_b64encode
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import httpx
import injected_time
from market_core.rfq import (
    CloseRfq, CreateRfq, EditRfq, OfferResponse, RfqAccountClaim, RfqAccountRequest, RfqAudience, RfqDetail,
    RfqMutationReceipt, RfqOperation, RfqSearchPage, RfqSummary, RfqTarget, SearchRfqs,
)
from market_identity import Ed25519Signer, TrustedIdentitySet
import pytest
from registry_client import RegistryClient, RegistryClientError, authenticate_request, authentication_headers
from registry_client.auth import verify_authenticated_response
from registry_client.models import ListingRequest
from registry_client.rfq_public import RfqPublicRegistryClient
from registry_client.rfq_registry import RfqRegistryClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from core_registry.db.migrations import migrate_database
from core_registry.db.models import RfqPartyReference, RfqReplayReservation, RfqRequest, RfqTermsRevision
from core_registry.config import settings
from core_registry.main import create_app

# Deterministic test signers and digest material. Never use them on a public network.
_AUTHORITY = Ed25519Signer(bytes([21]) * 32)
_SUCCESSOR = Ed25519Signer(bytes([22]) * 32)
_OTHER_REGISTRY = Ed25519Signer(bytes([24]) * 32)
_SCHEMA = Path(__file__).resolve().parents[4] / "domains/compute/registry/rfq-schema.json"



def requirements(**changes):
    deadline = (injected_time.now_datetime() + timedelta(days=14)).isoformat(timespec="seconds")
    return {
        "shape": {"gpu_model": "B300", "gpu_count": 8}, "node_count": 100,
        "regions": ["region-a", "region-b"], "start_earliest": "2030-01-01",
        "start_latest": "2030-01-04", "term": {"unit": "month", "value": 6},
        "respond_by": deadline, "metadata": {"budget": "USD 20 per node-hour, negotiable"},
        "description": "Flexible start",
    } | changes


class Registry:
    def __init__(self, path, *, name, seed, configured, url=None):
        url = url or f"sqlite:///{path}"
        migrate_database(url)
        self.engine = create_engine(url)
        self.sessions = sessionmaker(self.engine, autoflush=False)
        self.signer = Ed25519Signer(seed)
        self.audience = RfqAudience(
            name=name, principal=self.signer.identity.model_dump(mode="json"),
        )
        identity_file = path.with_suffix(".credential")
        identity_file.write_bytes(urlsafe_b64encode(seed).rstrip(b"="))
        digest_file = path.with_suffix(".json")
        digest_file.write_text(json.dumps({
            "current": "fixture", "keys": {"fixture": bytes([25] * 32).hex()},
        }))
        contact_file = path.with_suffix(".contact-keys.json")
        # Deterministic encryption key for synthetic tests. Never use it on a public network.
        contact_file.write_text(json.dumps({
            "current": "fixture", "keys": {"fixture": bytes([26] * 32).hex()},
        }))
        self.configuration = {
            "database_url": url,
            "registry_authority_id": name,
            "registry_authority_scheme": "ed25519",
            "registry_authority_identifier": self.signer.identity.identifier,
            "registry_authority_credential_file": str(identity_file),
            "registry_descriptor_base_url": "http://registry.test",
            "registry_descriptor_display_name": "RFQ fixture",
            "registry_descriptor_operator_identity": "Test operator",
            "registry_descriptor_access_acquisition_pointer": None,
            "require_read_api_key": False,
            "require_write_api_key": False,
            "bootstrap_api_key": None,
            "registry_rfq_authorities": {
                "test-accounts": TrustedIdentitySet(identities=(_AUTHORITY.identity,)),
            },
            "registry_rfq_spec_path": str(_SCHEMA) if configured else None,
            "registry_rfq_replay_keys_file": str(digest_file),
            "registry_rfq_contact_keys_file": str(contact_file),
        }

    @asynccontextmanager
    async def running(self):
        with pytest.MonkeyPatch.context() as configuration:
            for name, value in self.configuration.items():
                configuration.setattr(settings, name, value)
            app = create_app(self.sessions)
            async with app.router.lifespan_context(app):
                yield app

    @asynccontextmanager
    async def supply_client(self, *, signer):
        async with self.running() as application, RegistryClient(
            "http://test", transport=httpx.ASGITransport(app=application), signer=signer,
            caller_role="seller", expected_registries=TrustedIdentitySet(identities=(self.signer.identity,)),
            registry_authority=self.audience.name,
        ) as client:
            yield client

    async def request(
        self, action, *, rfq_id=None, subject="test-buyer", inputs=None, status=200,
        signer=_AUTHORITY, audience=None, request_id=None,
    ):
        claim = RfqAccountClaim(namespace="test-accounts", subject=subject)
        inputs = inputs or {}
        async with self.running() as application, RfqRegistryClient(
            "http://test", signer=signer, audience=audience or self.audience,
            transport=httpx.ASGITransport(app=application),
        ) as client:
            try:
                if action == "create":
                    result = await client.create(claim, CreateRfq.model_validate(inputs), request_id=request_id)
                elif action == "search":
                    result = await client.search(claim, SearchRfqs.model_validate(inputs), request_id=request_id)
                elif action == "read":
                    result = await client.read(claim, rfq_id, request_id=request_id)
                elif action == "edit":
                    result = await client.edit(claim, rfq_id, EditRfq.model_validate(inputs), request_id=request_id)
                elif action == "close":
                    result = await client.close(claim, rfq_id, CloseRfq.model_validate(inputs), request_id=request_id)
                else:
                    raise AssertionError(action)
            except RegistryClientError as error:
                assert error.status_code == status, str(error)
                return {"detail": error.body}
        assert status == 200, result
        return result.model_dump(mode="json", exclude_none=True)

    async def create(self, body=None, **options):
        return RfqMutationReceipt.model_validate(await self.request(
            "create", inputs={"kind": "compute", "requirements": body or requirements()}, **options,
        ))


@pytest.fixture
def registries(tmp_path):
    prior = injected_time.installed()
    time = injected_time.InjectedTime(start=1_800_000_000)
    injected_time.install(time)
    opened = []

    def make(*, name="registry-a", seed=bytes([23]) * 32, configured=True, url=None):
        result = Registry(tmp_path / f"{name}.db", name=name, seed=seed, configured=configured, url=url)
        opened.append(result)
        return result

    try:
        yield make, time
    finally:
        for registry in opened:
            registry.engine.dispose()
        injected_time.install(prior)


async def test_discovery_excludes_supply(registries):
    make, _ = registries
    registry = make()
    listing = ListingRequest(
        listing_id="test-supply", storefront_url="https://seller.example/",
        listing_resource={"gpu_model": "H200", "region": "region-a"},
        accepted_escrows=[],
        settlement_options=[{
            "option_id": "a" * 64,
            "price": {"asset": "usd", "rates": [{"field": "amount", "per": "hour", "value": "100"}]},
            "settlement": {"schema": "example.payment.v1", "account_ref": "test-seller"},
        }],
        max_duration_seconds=3600,
    )
    async with registry.supply_client(signer=_OTHER_REGISTRY) as supply:
        published = await supply.publish_listing(listing)
    body = requirements()
    created = await registry.create(body, request_id="one-create")
    assert await registry.create(body, request_id="one-create") == created
    async with registry.supply_client(signer=_AUTHORITY) as supply:
        matching = await supply.list_listings()
        assert [row.id for row in matching.listings] == [published["listing_id"]]
        with pytest.raises(RegistryClientError) as refused:
            await supply.publish_listing(listing)
        assert refused.value.status_code == 403
        assert (await supply.get_listing(listing.listing_id)).publisher_id == published["publisher_id"]

    search = RfqSearchPage.model_validate(await registry.request(
        "search", subject="ordinary-account", inputs={
            "kind": "compute", "filters": {"gpu_model": "B300", "min_node_count": 100, "region": "region-b"},
        },
    ))
    assert len(search.results) == 1
    assert search.results[0].rfq_id == created.resource_id
    assert search.results[0].requirements == body
    found = await registry.request("read", subject="ordinary-account", rfq_id=created.resource_id)
    detail = RfqDetail.model_validate(found)
    assert detail.registry == registry.audience
    assert detail.requirements["term"] == {"value": 6, "unit": "month"}
    assert not {"buyer_subject", "buyer_namespace", "contact", "responses"} & found.keys()
    assert "test-buyer" not in found.values()

    empty = await registry.request(
        "search", inputs={"kind": "compute", "filters": {"min_node_count": 101}},
    )
    assert empty["results"] == []

    wrong_kind = await registry.request(
        "create", inputs={"kind": "unsupported", "requirements": body}, status=503,
    )
    assert wrong_kind["detail"] == "rfq_kind_not_supported"
    refused = make(name="registry-disabled", seed=bytes([24]) * 32, configured=False)
    conflict = await refused.request(
        "create", inputs={"kind": "compute", "requirements": body}, status=503,
    )
    assert conflict["detail"] == "rfq_not_available"
    with Session(refused.engine) as db:
        assert db.scalar(select(RfqRequest)) is None


async def test_a_recognized_route_signs_the_malformed_reference_refusal(registries):
    make, _ = registries
    registry = make()
    operation = RfqOperation.READ
    malformed = "invalid!reference"
    request = authenticate_request(
        signer=_AUTHORITY, role=RfqTarget.caller_role, method=RfqTarget.method,
        operation=operation.value, resource=RfqTarget.bind_resource(malformed), body={},
    )
    # Rejection path for a reference the typed client deliberately refuses.
    async with registry.running() as application, httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://test"
    ) as raw:
        response = await raw.post(operation.route.format(rfq_id=malformed), headers=authentication_headers(request), json={})
    assert response.status_code == 422
    verify_authenticated_response(
        headers=response.headers, expected_registries=TrustedIdentitySet(identities=(registry.signer.identity,)),
        request=request, status=response.status_code, body=response.json(),
    )


async def test_pagination_and_versioned_terms_are_bound_to_current_records(registries):
    make, _ = registries
    registry = make()
    first = await registry.create()
    second = await registry.create()
    query = {"kind": "compute", "filters": {"gpu_model": "B300"}, "page_size": 1}
    page = await registry.request("search", inputs=query)
    cursor = page["next_cursor"]
    one = page["results"][0]["rfq_id"]
    other_page = await registry.request("search", inputs=query | {"cursor": cursor})
    two = other_page["results"][0]["rfq_id"]
    assert {one, two} == {first.resource_id, second.resource_id}
    assert other_page.get("next_cursor") is None
    crossed = await registry.request(
        "search", inputs=query | {"cursor": cursor, "filters": {"region": "region-a"}}, status=409,
    )
    assert crossed["detail"] == "stale_rfq_cursor"

    stored = (await registry.request("read", rfq_id=one))["requirements"]
    equivalent_deadline = datetime.fromisoformat(stored["respond_by"]).astimezone(
        timezone(timedelta(hours=-2))
    ).isoformat()
    cosmetic = stored | {
        "regions": ["region-b", "region-a"], "description": "  Flexible start  ",
        "respond_by": equivalent_deadline,
    }
    edited = await registry.request(
        "edit", rfq_id=one, inputs={"version": 1, "requirements": cosmetic},
    )
    assert edited["version"] == 2 and edited["terms_revision"] == 1
    updated = await registry.request(
        "edit", rfq_id=one, inputs={
            "version": 2, "requirements": cosmetic | {"metadata": {"budget": "USD 10"}},
        },
    )
    assert updated["version"] == 3 and updated["terms_revision"] == 2
    with Session(registry.engine) as db:
        history = db.scalars(select(RfqTermsRevision).where(
            RfqTermsRevision.rfq_id == one,
        ).order_by(RfqTermsRevision.revision)).all()
    assert [item.revision for item in history] == [1, 2]
    assert history[0].requirements == stored
    assert history[1].requirements["metadata"] == {"budget": "USD 10"}

    assert (await registry.request(
        "close", rfq_id=one, inputs={"version": 2}, status=409,
    ))["detail"] == "stale_rfq_version"
    assert (await registry.request(
        "close", rfq_id=one, subject="ordinary-account", inputs={"version": 3}, status=404,
    ))["detail"] == "rfq_not_found"
    assert (await registry.request("close", rfq_id=one, inputs={"version": 3}))["state"] == "closed"
    assert (await registry.request("read", rfq_id=one))["state"] == "closed"
    await registry.request("read", rfq_id=one, subject="ordinary-account", status=404)
    await registry.request("search", inputs=query | {"cursor": cursor}, status=409)


async def test_deadline_and_allocated_reference_survive_a_signer_change(registries):
    make, clock = registries
    registry = make()
    body = requirements()
    created = await registry.create(body)
    original = await registry.request("read", rfq_id=created.resource_id)
    registry.configuration["registry_rfq_authorities"] = {
        "test-accounts": TrustedIdentitySet(identities=(_SUCCESSOR.identity,)),
    }
    same = await registry.request("read", rfq_id=created.resource_id, signer=_SUCCESSOR)
    assert same["buyer_reference"] == original["buyer_reference"]

    clock.set(int(datetime.fromisoformat(body["respond_by"]).timestamp()))
    known = await registry.request("read", rfq_id=created.resource_id, signer=_SUCCESSOR)
    assert known["state"] == "expired"
    await registry.request(
        "read", rfq_id=created.resource_id, subject="ordinary-account", signer=_SUCCESSOR, status=404,
    )
    await registry.request(
        "edit", rfq_id=created.resource_id, signer=_SUCCESSOR, status=409,
        inputs={"version": 1, "requirements": requirements()},
    )



async def test_registry_identity_qualifies_even_an_identical_rfq_id(registries, tmp_path):
    make, _ = registries
    one = make()
    two = make(name="registry-b", seed=bytes([24]) * 32)
    first = await one.create()
    a = RfqDetail.model_validate(await one.request("read", rfq_id=first.resource_id))
    # The server generates IDs. Seed the second registry with the same ID to
    # exercise the independent authority boundary without replacing its generator.
    with Session(two.engine) as db:
        now = injected_time.now_datetime().replace(tzinfo=None)
        db.add(RfqRequest(
            rfq_id=first.resource_id, kind=a.kind, buyer_namespace="test-accounts",
            buyer_subject="test-buyer", requirements=a.requirements,
            version=1, terms_revision=1, created_at=now, respond_by=now + timedelta(days=14),
        ))
        db.flush()
        db.add_all([
            RfqPartyReference(
                rfq_id=first.resource_id, namespace="test-accounts", subject="test-buyer",
                reference="second-buyer-reference",
            ),
            RfqTermsRevision(rfq_id=first.resource_id, revision=1, requirements=a.requirements, created_at=now),
        ])
        db.commit()
    b = RfqDetail.model_validate(await two.request("read", rfq_id=first.resource_id))
    assert a.registry == one.audience and b.registry == two.audience
    assert a.buyer_reference != b.buyer_reference
    with pytest.raises(ValueError, match="wrong_principal"):
        await two.request("read", rfq_id=first.resource_id, audience=one.audience, status=401)

    # A valid preview for the first registry does not authorize contact sharing in the second.
    # Deterministic encryption key for synthetic tests. Never use it on a public network.
    key_file = tmp_path / "synthetic-contact.json"
    key_file.write_text(json.dumps({"current": "fixture", "keys": {"fixture": "42" * 32}}))
    two.configuration["registry_rfq_contact_keys_file"] = str(key_file)
    claim = RfqAccountClaim(namespace="test-accounts", subject="respondent", can_share_contact=True)
    offer = OfferResponse(
        version=b.version, terms_revision=b.terms_revision, counterparty=a.buyer_reference,
        consent_to_share=True, contact={"email": "respondent@example.test"},
    )
    async with two.running() as application, RfqRegistryClient(
        "http://test", signer=_AUTHORITY, audience=two.audience,
        transport=httpx.ASGITransport(app=application),
    ) as scoped:
        with pytest.raises(RegistryClientError, match="rfq_counterparty_changed"):
            await scoped.respond(claim, b.rfq_id, offer)
        valid = offer.model_copy(update={"counterparty": b.buyer_reference})
        assert (await scoped.respond(claim, b.rfq_id, valid)).state == "pending"


async def test_admission_requires_the_contact_key_configuration(registries):
    make, _ = registries
    registry = make()
    registry.configuration["registry_rfq_contact_keys_file"] = None
    async with registry.running() as application, RfqRegistryClient(
        "http://test", signer=_AUTHORITY, audience=registry.audience,
        transport=httpx.ASGITransport(app=application),
    ) as client:
        buyer = RfqAccountClaim(namespace="test-accounts", subject="buyer")
        with pytest.raises(RegistryClientError, match="rfq_not_available"):
            await client.search(buyer, SearchRfqs(kind="compute"))



@pytest.mark.parametrize("public_supply", [False, True])
async def test_open_rfq_discovery_uses_supply_visibility(registries, public_supply):
    make, clock = registries
    registry = make()
    registry.configuration["require_read_api_key"] = not public_supply
    if not public_supply:
        registry.configuration["registry_descriptor_access_acquisition_pointer"] = "https://keys.example.test"
    terms = requirements(metadata={"deposit": "30% upfront, balance monthly"})
    created = await registry.create(terms, request_id="buyer-created")
    # The public projection must exclude private records that actually exist.
    claim = RfqAccountClaim(namespace="test-accounts", subject="respondent", can_share_contact=True)
    async with registry.running() as application, RfqRegistryClient(
        "http://test", signer=_AUTHORITY, audience=registry.audience, transport=httpx.ASGITransport(app=application),
    ) as seller:
        visible = await seller.read(claim, created.resource_id)
        await seller.respond(claim, created.resource_id, OfferResponse(
            version=visible.version, terms_revision=visible.terms_revision,
            counterparty=visible.buyer_reference, consent_to_share=True,
            contact={"email": "private-contact@example.test"},
        ))
    closed = await registry.create(request_id="buyer-created-second")
    _ = await registry.request("close", rfq_id=closed.resource_id, inputs={"version": closed.version})
    target = RfqTarget(RfqOperation.READ, created.resource_id)
    request_headers = {"X-Market-Request-ID": "guest-lookup"}

    async with registry.running() as application:
        transport = httpx.ASGITransport(app=application)
        async with RfqPublicRegistryClient(
            "http://test", audience=registry.audience, transport=transport,
        ) as guest:
            forwarded = await guest.forward(target, RfqAccountRequest(
                registry=registry.audience, request_id="guest-forward", inputs={},
            ))
            assert forwarded.proof
            if public_supply:
                read = await guest.read(created.resource_id, request_id="guest-lookup")
                assert forwarded.status == 200
                assert RfqSummary.model_validate(forwarded.body) == read
                found = await guest.search(SearchRfqs(kind="compute"), request_id="guest-lookup")
                assert read.registry == registry.audience
                assert read.rfq_id == created.resource_id
                assert read.requirements == terms
                assert found.results == [read]
                assert "private-contact@example.test" not in read.model_dump_json()
                for reference in (closed.resource_id, "unknown"):
                    with pytest.raises(RegistryClientError) as refused:
                        await guest.read(reference, request_id="guest-lookup")
                    assert refused.value.status_code == 404
                    assert refused.value.body == "rfq_not_found"
            else:
                assert forwarded.status == 401
                with pytest.raises(RegistryClientError) as unreadable:
                    await guest.read(created.resource_id, request_id="guest-lookup")
                with pytest.raises(RegistryClientError) as unsearchable:
                    await guest.search(SearchRfqs(kind="compute"), request_id="guest-lookup")
                for error in (unreadable.value, unsearchable.value):
                    assert error.status_code == 401
                    assert error.body == "rfq_auth_required"

        async with RfqRegistryClient(
            "http://test", signer=_OTHER_REGISTRY, audience=registry.audience, transport=transport,
        ) as untrusted:
            with pytest.raises(RegistryClientError) as refused:
                await untrusted.read(claim, created.resource_id)
            assert refused.value.status_code == 401

        # Rejection paths the public client cannot construct.
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as raw:
            failed_proof = await raw.post(target.path, headers=request_headers | {"X-Market-Signature": ""})
            assert failed_proof.status_code == 401
            denied_inbox = await raw.post(f"/rfqs/{created.resource_id}/responses/list", headers=request_headers)
            assert denied_inbox.status_code == 401

    with Session(registry.engine) as db:
        assert db.scalar(select(RfqReplayReservation).where(RfqReplayReservation.request_id == "guest-lookup")) is None
    account_read = await registry.request("read", rfq_id=created.resource_id, subject="eligible-account")
    assert account_read["buyer_reference"]

    if public_supply:
        clock.set(int(datetime.fromisoformat(terms["respond_by"]).timestamp()))
        async with registry.running() as application, RfqPublicRegistryClient(
            "http://test", audience=registry.audience, transport=httpx.ASGITransport(app=application),
        ) as guest:
            with pytest.raises(RegistryClientError) as expired:
                await guest.read(created.resource_id)
            assert expired.value.status_code == 404
            assert expired.value.body == "rfq_not_found"
