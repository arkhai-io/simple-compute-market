"""The storefront's mediation client is built with the CA bundle its credential names.

Over ``test_payment_settlement_client``'s harness: the storefront's runtime and
lifecycle composition behind the in-process app, a payment deal settled through
it, and the settlement composition's dispute configuration replaced to hold a
credential for the deal's authority, as the harness itself replaces the
composition. A mediation client loads its CA bundle when it is built, so a
credential naming a bundle that does not exist is one no client can be built
from: the deal, read through the canonical lifecycle client as a buyer reads it,
is reported for repair, as for a missing credential, and the storefront logs why
the credential is unusable. The same credential naming
no bundle builds the deal's client. That a client given a bundle verifies the
authority under it alone is the mediation kit's TLS test.
"""

import logging
from dataclasses import replace

import httpx
import pytest
from market_deal_lifecycle_client import LifecycleClient
from market_deal_lifecycle_contracts.models import Rejected
from market_deal_servicing import SellerSession
from market_deal_servicing.evidence import transaction
from market_identity import TrustedIdentitySet
from market_storefront_kit.dispute_configuration import RegistryDisputePolicy

from integration.test_payment_settlement_client import BUYER, SELLER, enabled, harness  # noqa: F401 - fixtures

# The seller's credential toward the deal's authority: a public development
# value no authority reads.
CREDENTIAL = "dev-bare-metal-dispute-trust-credential"


def _deal_with_credential(h, **trust):
    lifecycle = h.runtime.lifecycle
    with transaction(lifecycle.path) as conn:
        deal = SellerSession(conn).read(h.negotiation_id)
    identity = dict(zip(("interface", "origin", "account", "record_key"), deal.dispute.identity))
    disputes = RegistryDisputePolicy.from_document(
        {"DisputeCredential": [identity | {"api_key": CREDENTIAL} | trust]}
    )
    object.__setattr__(
        h.runtime, "settlement_composition", replace(h.runtime.settlement_composition, disputes=disputes),
    )
    return lifecycle, deal


@pytest.mark.asyncio
async def test_a_credential_whose_ca_bundle_cannot_be_loaded_reports_the_deal_for_repair(
    harness, tmp_path, caplog,
):
    caplog.set_level(logging.WARNING, logger="arkhai_bare_metal_storefront.lifecycle")
    h = harness
    h.serve()
    await h.settle()
    path = str(tmp_path / "absent" / "ca.pem")
    lifecycle, _ = _deal_with_credential(h, ca_bundle_path=path)

    async with LifecycleClient(
        "http://test", BUYER, TrustedIdentitySet(identities=(SELLER.identity,)),
        transport=httpx.ASGITransport(app=h.app),
    ) as buyer:
        view = await buyer.read(h.negotiation_id)

    assert isinstance(view.authority.outcome, Rejected), view
    assert view.authority.outcome.reason.startswith("repair required"), view
    assert lifecycle.clients == {}
    # The repair reason names the credential missing; the log says why it is
    # unusable, without the credential.
    unusable = [record.getMessage() for record in caplog.records
                if "is unusable" in record.getMessage()]
    assert unusable and all("FileNotFoundError" in message and path in message
                            and CREDENTIAL not in message for message in unusable), unusable


@pytest.mark.asyncio
async def test_a_credential_naming_no_ca_bundle_builds_the_deals_client(harness, caplog):
    # The composition's dispute port, built for the deal's binding: no request is
    # sent, since the authority's origin is the harness's and nothing answers it.
    caplog.set_level(logging.WARNING, logger="arkhai_bare_metal_storefront.lifecycle")
    h = harness
    h.serve()
    await h.settle()
    lifecycle, deal = _deal_with_credential(h)

    lifecycle.dispute(deal.dispute_binding)

    [client] = lifecycle.clients.values()
    assert client.authority.identity == deal.dispute.identity
    assert not [record for record in caplog.records if "is unusable" in record.getMessage()]
    await client.close()
