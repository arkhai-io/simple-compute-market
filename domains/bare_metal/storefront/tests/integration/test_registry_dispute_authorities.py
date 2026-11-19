"""A bare-metal storefront reads again, at publication, a registry it could not read.

The running app's real settlement composition relies on its registry's
recommended dispute authorities alone. Startup reads the registry's descriptor
through the runtime's registry configuration, whose client is the in-process
registry double, failing until the test gives it the registry's descriptor; each
publication step and settlement status run through the app's typed client.

Every account, key and address here is a deterministic development value; none
may be used on a public network.
"""

from __future__ import annotations

import pytest
from market_core import RegistryDescriptor
from market_identity import Ed25519Signer

from recurring_world import DISPUTE_ENTRY, MECHANISM, recurring_world
from test_publication_cycle import REGISTRY_URL

pytestmark = pytest.mark.asyncio

_REGISTRY_SIGNER = Ed25519Signer(b"\x5b" * 32)


def _descriptor() -> RegistryDescriptor:
    """The registry's descriptor, as its client returns it once verified,
    recommending the payments authority."""
    return RegistryDescriptor.model_validate({
        "access": {"posture": "public"},
        "authority": {
            "name": "registry",
            "principals": [_REGISTRY_SIGNER.identity.model_dump(mode="json")],
        },
        "baseUrl": REGISTRY_URL,
        "displayName": "Test Registry",
        "operatorIdentity": "Test Operator",
        "schema": {"id": "compute.market", "version": "1"},
        "recommendedDisputeAuthorities": [DISPUTE_ENTRY.model_dump(mode="json")],
    })


def _payment_options(listing) -> list[dict]:
    return [
        option for option in listing.extra["settlement_options"]
        if option["settlement"]["schema"] == MECHANISM
    ]


async def test_a_storefront_that_started_before_its_registry_publishes_once_it_answers(tmp_path):
    """Spec scenario "A storefront starts before its registry": once the
    registry answers, the next publication step reads it and the listing
    carries the payments option its authority allows, with no restart."""
    # No recurring treatment is declared, so the payments option is the once one.
    async with recurring_world(tmp_path, treatments=None, registry_recommendations=True) as world:
        report = await world.publish()
        (published,) = [item for item in report["actions"] if item["action"] == "publish"]
        listing_id = str(published["listing_id"])
        unread = await world.admin.get_listing(listing_id)
        status = await world.admin.get_system_status()

        world.registries.descriptors[REGISTRY_URL] = _descriptor()
        await world.publish()
        read = await world.admin.get_listing(listing_id)

    # The Alkahest option needs no dispute authority, so the listing publishes
    # while the registry is unread, with no payments option.
    assert [option["settlement"]["schema"] for option in unread.extra["settlement_options"]] == [
        "alkahest.v1"
    ]
    assert _payment_options(unread) == []
    (payments,) = [item for item in status.settlement if item["mechanism"] == MECHANISM]
    assert payments["ready"] is True and payments["blockers"] == []
    assert [entry["registry"] for entry in
            payments["public_details"]["dispute_authorities_unread"]] == [REGISTRY_URL]
    (option,) = _payment_options(read)
    assert option["lifecycle"]["adjudication"]["dispute"]["account"] == DISPUTE_ENTRY.account
    # Startup's read, the first step's, and the step after the registry answered.
    assert world.registries.descriptor_reads == [[REGISTRY_URL]] * 3
