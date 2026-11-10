"""The storefront's mediation client is built with the CA bundle its credential names.

Over ``test_payment_settlement``'s harness: the storefront's settle and lifecycle
routes in an in-process app, with real SQLite persistence and the storefront's
lifecycle class, built by the harness from a dispute configuration document, and
the payments service replaced at ``PaymentsClient`` by the kit's fake. Every
mediation client sends through an injected transport that records the attempt and
raises the connection error an unresolvable name produces. Servicing is stepped by
calling the lifecycle's cycle, the step the ``settlement-servicing`` loop runs, and
the deal is read through the canonical lifecycle client, as a buyer reads it.

A mediation client loads its CA bundle when it is built, so a credential naming a
bundle that does not exist is one no client can be built from: the storefront
reports the deal for repair, as for a missing credential, logs why the credential
is unusable, and never contacts the authority. The same credential naming no
bundle reaches the authority. That a client given a bundle verifies the authority
under it alone is the mediation kit's TLS test.
"""

from __future__ import annotations

import logging

import httpx
import pytest
from market_deal_lifecycle_client import LifecycleClient
from market_deal_lifecycle_contracts.models import Rejected, Unknown
from market_identity import TrustedIdentitySet

from tests.integration.test_payment_settlement import BUYER, NEGOTIATION, SELLER, make

# A dispute authority under .invalid, a top-level domain reserved never to
# resolve, with a record key that has no usable private half. Public development
# values; never use them on a public network.
AUTHORITY = {
    "interface": "arkhai.mediation.v1",
    "origin": "https://dispute.invalid",
    "account": "00000000-0000-4000-8000-0000000000d1",
    "record_key": "ed25519:lMg0OhYvDsBJf2G3MtLHgbPX3spRLUCV20o7HY7AFOI",
    "params": {},
}
# The seller's credential toward that authority: a public development value
# nothing at .invalid ever reads.
CREDENTIAL = "dev-vm-dispute-trust-credential"


@pytest.mark.asyncio
@pytest.mark.parametrize("bundle", ["none", "missing"])
async def test_the_authority_outcome_follows_whether_the_credentials_ca_bundle_loads(
    make, tmp_path, bundle, caplog,
):
    caplog.set_level(logging.WARNING, logger="market_storefront.deal_lifecycle")
    path = str(tmp_path / "absent" / "ca.pem")
    trust = {} if bundle == "none" else {"ca_bundle_path": path}
    attempts: list[str] = []

    def unresolvable(request: httpx.Request) -> httpx.Response:
        attempts.append(request.url.path)
        raise httpx.ConnectError("[Errno -2] Name or service not known", request=request)

    identity = {key: AUTHORITY[key] for key in ("interface", "origin", "account", "record_key")}
    h = await make(
        authority=AUTHORITY,
        disputes={"DisputeCredential": [identity | {"api_key": CREDENTIAL} | trust]},
        mediation_transport=httpx.MockTransport(unresolvable),
    )
    h.serve()
    await h.settle()
    await h.delivered()

    assert await h.lifecycle.cycle() == 1
    async with LifecycleClient(
        "http://test", BUYER, TrustedIdentitySet(identities=(SELLER.identity,)),
        transport=h.transport,
    ) as buyer:
        view = await buyer.read(NEGOTIATION)

    unusable = [record.getMessage() for record in caplog.records
                if "is unusable" in record.getMessage()]
    if bundle == "none":
        assert attempts, "a credential naming no bundle reaches the authority"
        assert isinstance(view.authority.outcome, Unknown), view
        assert unusable == []
    else:
        assert attempts == []
        assert isinstance(view.authority.outcome, Rejected), view
        assert view.authority.outcome.reason.startswith("repair required"), view
        # The repair reason names the credential missing; the log says why it is
        # unusable, without the credential.
        assert unusable and all("FileNotFoundError" in message and path in message
                                and CREDENTIAL not in message for message in unusable), unusable
