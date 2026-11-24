"""Packaged compute schema, account admission and discovery on the registry."""

from datetime import timedelta
from hashlib import sha256
from uuid import uuid4

from arkhai_compute.rfq import validate_filters, validate_requirements
from e2e_harness.settings import settings
import injected_time
from market_core.rfq import CloseRfq, CreateRfq, RfqAccountClaim, RfqAudience, SearchRfqs
from market_identity import Ed25519Signer, Identity, TrustedIdentitySet, create_signer
import pytest
from registry_client import RegistryClientError, SyncRegistryClient
from registry_client.rfq_public import SyncRfqPublicRegistryClient
from registry_client.rfq_registry import SyncRfqRegistryClient

# Matches the verification pin in the development registry profile.
# This deterministic test authority must never be used on a public network.
_FIXTURE_AUTHORITY = Ed25519Signer(sha256(b"SCM development-only RFQ account authority").digest())


@pytest.mark.e2e_buyer_rfq_discovery
def test_ordinary_account_discovers_deployed_compute_rfqs():
    registry_url = str(settings.REGISTRY.API_URL)
    registry_authority = str(settings.REGISTRY.AUTHORITY_ID)
    registry_pin = Identity(
        scheme=str(settings.REGISTRY.get("authority_scheme", "eip191")),
        identifier=str(settings.REGISTRY.IDENTIFIER),
    )
    supply_signer = create_signer(
        str(settings.BUYER.get("marketplace_scheme", "eip191")),
        str(settings.BUYER.MARKETPLACE_CREDENTIAL),
    )
    with SyncRegistryClient(
        registry_url, signer=supply_signer, caller_role="buyer",
        expected_registries=TrustedIdentitySet(identities=(registry_pin,)),
        registry_authority=registry_authority,
    ) as supply:
        descriptor = supply.get_registry_descriptor()
        assert descriptor.authority.name == registry_authority
        audience = RfqAudience(name=descriptor.authority.name, principal=descriptor.authority.principals[0])
        assert audience.principal.model_dump(mode="json") == registry_pin.model_dump(mode="json")
        with (
            SyncRfqRegistryClient(registry_url, signer=_FIXTURE_AUTHORITY, audience=audience) as rfqs,
            SyncRfqPublicRegistryClient(registry_url, audience=audience) as anonymous,
        ):
            _exercise_rfq(rfqs, supply, audience, anonymous)


def _exercise_rfq(
    rfqs: SyncRfqRegistryClient, supply: SyncRegistryClient, audience: RfqAudience, anonymous: SyncRfqPublicRegistryClient,
) -> None:
    buyer, browser = (RfqAccountClaim(namespace="development", subject=uuid4().hex) for _ in range(2))
    now = injected_time.now_datetime()
    region = f"rfq-test-{uuid4().hex}"
    requirements = validate_requirements({
        "shape": {"gpu_model": "B300", "gpu_count": 8},
        "node_count": 100,
        "regions": [region],
        "start_earliest": (now.date() + timedelta(days=30)).isoformat(),
        "start_latest": (now.date() + timedelta(days=37)).isoformat(),
        "term": {"value": 6, "unit": "month"},
        "respond_by": (now + timedelta(days=14)).isoformat(timespec="seconds"),
        "metadata": {"budget": "USD 20 per node-hour, negotiable"},
    })
    with pytest.raises(RegistryClientError) as bad_requirement:
        rfqs.create(buyer, CreateRfq(kind="compute", requirements=dict(requirements) | {"node_count": 0}))
    assert bad_requirement.value.status_code == 422

    created = rfqs.create(buyer, CreateRfq(kind="compute", requirements=dict(requirements)))
    rfq_id = created.resource_id
    try:
        filters = validate_filters({"gpu_model": "B300", "min_node_count": 100, "region": region})
        search = rfqs.search(browser, SearchRfqs(kind="compute", filters=dict(filters)))
        assert [result.rfq_id for result in search.results] == [rfq_id]
        with pytest.raises(RegistryClientError) as bad_filter:
            rfqs.search(browser, SearchRfqs(kind="compute", filters={"min_node_count": "100"}))
        assert bad_filter.value.status_code == 422
        detail = rfqs.read(browser, rfq_id)
        assert detail.registry == audience
        assert detail.requirements == requirements
        assert detail.buyer_reference != buyer.subject
        assert not {"buyer_subject", "contact", "responses"} & detail.model_dump().keys()
        assert rfq_id not in {listing.id for listing in (supply.list_listings()).listings}
        assert anonymous.read(rfq_id) == search.results[0]
        assert anonymous.search(SearchRfqs(kind="compute", filters=dict(filters))).results == [search.results[0]]
    finally:
        rfqs.close(buyer, rfq_id, CloseRfq(version=created.version))
