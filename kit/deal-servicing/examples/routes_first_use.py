"""Drive the mounted lifecycle router with the shipped signed client."""

import asyncio
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
from fastapi import FastAPI
from market_deal_lifecycle.adapters import DisputeAdapterTable, PaymentAdapterTable, PaymentSelector
from market_deal_lifecycle_client import LifecycleClient, LifecycleClientError
from market_deal_lifecycle_contracts.models import Accepted, CommitMessage, HintMessage, SubmitResponse
from market_identity import (
    EMPTY_BODY, Ed25519Signer, RequestEnvelope, TrustedIdentitySet, canonical_body_hash,
    canonical_json, sign_request,
)

from market_deal_servicing import (
    DealWatch, DeliveryRecord, EndSession, LifecycleRouteBinding, LifecycleRouteServices,
    SellerDeal, SellerServicing, SellerSession, create_lifecycle_router,
)
from market_deal_servicing.evidence import transaction


async def main():
    # Public deterministic development identities; never use on a public network.
    buyer, seller, admin, stranger = (Ed25519Signer(bytes([n]) * 32) for n in (1, 2, 3, 4))
    calls = []
    with TemporaryDirectory(prefix="lifecycle-routes-") as root:
        path = Path(root) / "storefront.sqlite"
        servicing = SellerServicing(
            path, payments=PaymentAdapterTable([]), disputes=DisputeAdapterTable([]),
            credential_available=lambda _: False, clock=lambda: int(time.time()),
            watch_factory=lambda deal, payment, dispute: DealWatch(
                path, negotiation_id=deal.negotiation_id, commitment_ref=deal.commitment_ref,
                payment=payment, dispute=dispute, dispute_binding=deal.dispute_binding,
                seller_account="fixture", actor=lambda _: seller.identity, clock=lambda: int(time.time()),
            ),
        )
        now = int(time.time())
        with transaction(path) as conn:
            EndSession(conn).register(DeliveryRecord(
                negotiation_id="example", seller=seller.identity, commitment_ref="fixture-commitment",
                start_at=now, committed_at=now, term_end=now + 1000,
            ))
            SellerSession(conn).register(SellerDeal(
                negotiation_id="example", buyer=buyer.identity, commitment_ref="fixture-commitment",
                domain="fixture", payment=PaymentSelector("fixture-no-adapter"), once_only=True,
            ))

        def binding(negotiation):
            if negotiation != "example":
                raise KeyError(negotiation)
            return LifecycleRouteBinding(buyer=buyer.identity, seller=seller.identity, settlement=True)

        async def peer(message):
            calls.append(message.kind)
            return SubmitResponse(outcome=Accepted())

        services = LifecycleRouteServices(
            seller=servicing, binding=binding, signer=seller,
            administrators=TrustedIdentitySet(identities=(admin.identity,)), peer=peer,
        )
        app = FastAPI()
        app.include_router(create_lifecycle_router(lambda _: services))
        transport = httpx.ASGITransport(app=app)
        trust = TrustedIdentitySet(identities=(seller.identity,))
        captures = []
        async with LifecycleClient("http://fixture", buyer, trust, transport=transport,
                                   capture=captures.append) as client:
            assert (await client.commit(CommitMessage(
                negotiation_id="example", commitment_ref="fixture-commitment", operation_key="commit",
            ))).outcome.status == "accepted"
            assert (await client.hint(HintMessage(
                negotiation_id="example", operation_key="hint",
            ))).outcome.status == "accepted"
            assert (await client.read("example")).authority.outcome.status == "rejected"
        async with LifecycleClient("http://fixture", stranger, trust, transport=transport) as client:
            try:
                await client.hint(HintMessage(negotiation_id="example", operation_key="wrong-owner"))
            except LifecycleClientError as exc:
                assert exc.status_code == 403
            else:
                raise AssertionError("wrong buyer was admitted")

        async def raw(signer, role, operation, resource, body, method, url):
            envelope = sign_request(signer=signer, envelope=RequestEnvelope(
                role=role, principal=signer.identity, method=method, operation=operation,
                resource=resource, request_id=operation + signer.identity.identifier,
                timestamp=now, body_hash=canonical_body_hash(body),
            ))
            headers = {
                "X-Market-Signature-Version": envelope.protocol,
                "X-Market-Identity-Scheme": envelope.principal.scheme.value,
                "X-Market-Identity-Identifier": envelope.principal.identifier,
                "X-Market-Role": role, "X-Market-Request-ID": envelope.request_id,
                "X-Market-Timestamp": str(now), "X-Market-Signature": envelope.proof.value,
            }
            async with httpx.AsyncClient(transport=transport, base_url="http://fixture") as http:
                return await http.request(method, url, headers=headers,
                                          content=None if body is EMPTY_BODY else canonical_json(body))

        admin_url = "/api/v1/admin/lifecycle"
        assert (await raw(admin, "admin", "lifecycle_list", "", EMPTY_BODY, "GET", admin_url)).status_code == 200
        assert (await raw(buyer, "admin", "lifecycle_list", "", EMPTY_BODY, "GET", admin_url)).status_code == 403
        relay = await raw(buyer, "buyer", "lifecycle_peer", "example", {
            "kind": "stop", "negotiation_id": "example", "operation_key": "relay",
        }, "POST", "/api/v1/negotiations/example/lifecycle")
        assert relay.status_code == 422 and calls == ["commit", "hint"]
        assert len(captures) == 6
        print("mounted typed-client commit/hint/read; wrong buyer/admin and authority relay refused; six exact signed envelopes")


if __name__ == "__main__":
    asyncio.run(main())
