"""Drive shipped receipts with both published claim signature schemes."""

import asyncio
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
from fastapi import FastAPI
from market_arkhai_mediation.adapter import MediationAdapter
from market_arkhai_mediation.client import MediationClient, MediationCredential
from market_arkhai_mediation.fixtures import market_signer
from market_arkhai_mediation.fixtures.authority import MediationContractFake
from market_deal_lifecycle.adapters import (
    DeliveryEndIntent, DisputeAdapterTable, DisputeBinding, PaymentAdapterTable, PaymentSelector,
)
from market_deal_lifecycle.terms import DisputeAuthority
from market_deal_lifecycle_contracts.models import SubmitResponse, Accepted
from market_deal_lifecycle_client import LifecycleClient
from market_identity import Ed25519Signer, TrustedIdentitySet
from pydantic import SecretStr

from market_deal_servicing import (
    DealWatch, DeliveryIngress, DeliveryRecord, EndService, EndSession, LifecycleRouteBinding,
    LifecycleRouteServices, PhysicalResult, SellerDeal, SellerServicing, SellerSession, create_lifecycle_router,
)
from market_deal_servicing.evidence import transaction


class Physical:
    async def apply_end(self, *_args, **_kwargs):
        return PhysicalResult(progress="tearing_down", done=True)


async def main():
    for scheme in ("ed25519", "eip191"):
        peer = MediationContractFake()
        authority = DisputeAuthority.model_validate(peer.authority)
        seller = market_signer(scheme)
        buyer = Ed25519Signer(bytes([1]) * 32)  # Public development seed; never use on a public network.
        agreement = {**peer.data["filing"]["request"]["agreement"],
                     "seller": seller.identity.model_dump(mode="json")}
        commitment = peer.data["filing"]["request"]["transaction"]
        binding = DisputeBinding("example", commitment, authority)
        async with MediationClient(
            authority, MediationCredential(authority.identity, token=SecretStr("fixture-payee")),
            transport=peer.transport(),
        ) as mediation:
            adapter = MediationAdapter(binding, agreement, mediation)
            with TemporaryDirectory(prefix="receipt-claims-") as root:
                path = Path(root) / "storefront.sqlite"
                end = EndService(path, Physical(), clock=lambda: int(time.time()))
                svc = SellerServicing(
                    path, payments=PaymentAdapterTable([]), disputes=DisputeAdapterTable([]),
                    credential_available=lambda _: False, clock=lambda: int(time.time()),
                    watch_factory=lambda deal, payment, dispute: DealWatch(
                        path, negotiation_id=deal.negotiation_id, commitment_ref=commitment,
                        payment=payment, dispute=dispute, dispute_binding=deal.dispute_binding,
                        seller_account=peer.payee, actor=lambda _: seller.identity, clock=lambda: int(time.time()),
                    ),
                )
                now = int(time.time())
                with transaction(path) as conn:
                    EndSession(conn).register(DeliveryRecord(
                        negotiation_id="example", seller=seller.identity, commitment_ref=commitment,
                        start_at=now - 100, committed_at=now - 100, term_end=now + 1000, progress="active",
                    ))
                    SellerSession(conn).register(SellerDeal(
                        negotiation_id="example", commitment_ref=commitment, domain="fixture",
                        buyer=buyer.identity, payment=PaymentSelector("fixture"), dispute=authority,
                    ))
                ingress = DeliveryIngress(
                    path, clock=lambda: int(time.time()), verify_site=lambda *_: None,
                    receipt_claim=lambda _negotiation, at: adapter.sign_delivery_end(
                        DeliveryEndIntent(ended_at=at, delivered=True, cause="payer"), seller,
                    ),
                )
                async def peer_handler(_):
                    return SubmitResponse(outcome=Accepted())
                services = LifecycleRouteServices(
                    seller=svc, binding=lambda _: LifecycleRouteBinding(
                        buyer=buyer.identity, seller=seller.identity, settlement=True,
                    ), signer=seller, administrators=TrustedIdentitySet(identities=(seller.identity,)),
                    peer=peer_handler, ingress=ingress, end=end,
                )
                app = FastAPI()
                app.include_router(create_lifecycle_router(lambda _: services))
                async with LifecycleClient(
                    "http://fixture", buyer, TrustedIdentitySet(identities=(seller.identity,)),
                    transport=httpx.ASGITransport(app=app),
                ) as client:
                    first = await client.end_delivery("example", operation_key="end-now")
                    second = await client.end_delivery("example", operation_key="end-now")
                    assert first.signed_delivery_end_claim == second.signed_delivery_end_claim
                    intent = DeliveryEndIntent(ended_at=first.receipt_at, delivered=True, cause="payer")
                    assert adapter.verify_delivery_end(first.signed_delivery_end_claim, intent)
                    request = adapter.concurrent_request(intent, first.signed_delivery_end_claim)
                    assert request.payload["concurrence"] == first.signed_delivery_end_claim
                    assert not adapter.verify_delivery_end(first.signed_delivery_end_claim, intent.model_copy(
                        update={"ended_at": first.receipt_at - 1},
                    ))
                    print(scheme, "mounted receipt verifies; claim/proof stable; exact concurrence maps; backdate refuses")


if __name__ == "__main__":
    asyncio.run(main())
