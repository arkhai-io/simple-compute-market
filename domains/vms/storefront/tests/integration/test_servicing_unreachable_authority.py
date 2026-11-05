"""A VM payment deal stays running while its pinned dispute authority cannot be reached.

Over ``test_payment_settlement``'s harness: the storefront's settle and lifecycle
routes in an in-process app, with real SQLite persistence and the real lifecycle
composition, and the payments service replaced at ``PaymentsClient`` by the
kit's fake. The Agreement pins an authority under ``.invalid``, and the
storefront holds an identity-bound dispute credential for it that resolves,
stated either as the token itself (``api_key``, as a secret overlay states it) or
as a variable; the harness passes the merged dispute document, not the files the
storefront's loader would merge it from. Every
mediation client sends through an injected transport raising the connection
error a name that never resolves produces, so no network is needed. Servicing is
stepped by calling the lifecycle's cycle, the step the ``settlement-servicing``
loop runs; the deal is then read through the canonical lifecycle client, as a
buyer reads it. The servicing part of spec scenario "The VM lane has no
mediation target".
"""

from __future__ import annotations

import logging

import httpx
import pytest
from market_deal_lifecycle_client import LifecycleClient
from market_deal_lifecycle_contracts.models import Accepted, Unknown
from market_identity import TrustedIdentitySet

from tests.integration.test_payment_settlement import BUYER, NEGOTIATION, SELLER, make

# A dispute authority nothing can answer for, as the lanes pin one: its origin is
# under .invalid, a top-level domain reserved never to resolve, and its record
# key has no usable private half. Public development values; never use them on a
# public network.
UNREACHABLE = {
    "interface": "arkhai.mediation.v1",
    "origin": "https://dispute.invalid",
    "account": "00000000-0000-4000-8000-0000000000d1",
    "record_key": "ed25519:lMg0OhYvDsBJf2G3MtLHgbPX3spRLUCV20o7HY7AFOI",
    "params": {},
}
CREDENTIAL_ENV = "VM_LANE_DISPUTE_API_KEY"
# The seller's credential toward that authority: a public development value
# nothing at .invalid ever reads.
CREDENTIAL = "dev-vm-lane-dispute-credential"


@pytest.mark.asyncio
@pytest.mark.parametrize("form", ["api-key", "variable"])
async def test_servicing_reads_running_while_the_pinned_authority_is_unreachable(
    make, monkeypatch, caplog, form,
):
    # One entry states the token itself and no variable is set; the other names
    # the variable holding it.
    if form == "api-key":
        monkeypatch.delenv(CREDENTIAL_ENV, raising=False)
        stated = {"api_key": CREDENTIAL}
    else:
        monkeypatch.setenv(CREDENTIAL_ENV, CREDENTIAL)
        stated = {"api_key_env": CREDENTIAL_ENV}
    attempts: list[tuple[str, str]] = []
    tokens: set[str] = set()

    def unresolvable(request: httpx.Request) -> httpx.Response:
        attempts.append((request.url.host, request.url.path))
        tokens.add(request.headers["Authorization"])
        # What httpx raises when the origin's name does not resolve.
        raise httpx.ConnectError("[Errno -2] Name or service not known", request=request)

    h = await make(
        authority=UNREACHABLE,
        disputes={"DisputeCredential": [{
            key: UNREACHABLE[key] for key in ("interface", "origin", "account", "record_key")
        } | stated]},
        mediation_transport=httpx.MockTransport(unresolvable),
    )
    h.serve()
    await h.settle()
    await h.delivered()

    # The respondent poll and the deal's watch both reach the authority and
    # fail there. The poll's transport failure is logged for the next cycle to
    # retry, the cycle completes, and nothing marks the deal for repair.
    with caplog.at_level(logging.ERROR, logger="market_storefront.deal_lifecycle"):
        assert await h.lifecycle.cycle() == 1
    assert {(host, path) for host, path in attempts} == {
        ("dispute.invalid", "/respondent"), ("dispute.invalid", "/record"),
    }
    assert tokens == {f"Bearer {CREDENTIAL}"}
    assert [
        record.getMessage() for record in caplog.records if record.levelno >= logging.ERROR
    ] == ["VM respondent discovery awaits recovery"]
    [summary] = (await h.lifecycle.seller.list()).deals
    assert summary.state == "running"

    async with LifecycleClient(
        "http://test", BUYER, TrustedIdentitySet(identities=(SELLER.identity,)),
        transport=h.transport,
    ) as buyer:
        view = await buyer.read(NEGOTIATION)

    assert view.commitment_ref == h.data.transaction_id
    assert view.authority.state == "running", view
    assert not isinstance(view.authority.outcome, Accepted), view
    assert isinstance(view.authority.outcome, Unknown), view
    assert "mediation transport" in view.authority.outcome.reason
