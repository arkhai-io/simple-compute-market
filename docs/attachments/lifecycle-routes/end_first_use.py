"""Mounted buyer end flow with injected authority outages and durable restart."""

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
import time

import httpx
from fastapi import FastAPI
from market_arkhai_mediation.adapter import MediationAdapter
from market_arkhai_mediation.client import MediationClient, MediationCredential
from market_arkhai_mediation.fixtures import record_signer
from market_arkhai_mediation.fixtures.authority import MediationContractFake
from market_deal_lifecycle.adapters import (
    DeliveryEndIntent, DisputeAdapterTable, DisputeBinding, PaymentAdapterTable, PaymentBinding, PaymentSelector,
)
from market_deal_lifecycle.terms import DisputeAuthority
from market_deal_lifecycle_buyer import BuyerDeal, BuyerLifecycle, FileEvidenceStore
from market_deal_lifecycle_client import LifecycleClient
from market_deal_lifecycle_contracts.models import Accepted, SubmitResponse, Unknown
from market_deal_servicing import (
    DealWatch, DeliveryIngress, DeliveryRecord, EndService, EndSession, LifecycleRouteBinding,
    LifecycleRouteServices, PhysicalResult, SellerDeal, SellerServicing, SellerSession, create_lifecycle_router,
)
from market_deal_servicing.evidence import transaction
from market_identity import Ed25519Signer, TrustedIdentitySet


class Physical:
    async def apply_end(self, *_args, **_kwargs):
        return PhysicalResult(progress="tearing_down", done=True)


class Payment:
    supported_commands = frozenset({"stop"})

    def __init__(self):
        self.down = True
        self.calls = []

    def validate(self, command):
        return None

    async def submit(self, command, keys):
        self.calls.append((command.model_dump(mode="json"), keys.part_event("rate", "stop")))
        return Unknown(reason="fixture payment outage; billing still runs") if self.down else Accepted()


async def scenario(mode):
    with TemporaryDirectory(prefix="buyer-end-") as root:
        peer = MediationContractFake()
        authority = DisputeAuthority.model_validate(peer.authority)
        seller = record_signer()
        buyer = Ed25519Signer(bytes([1]) * 32)  # Public fixture seed; never use on a public network.
        agreement = {**peer.data["filing"]["request"]["agreement"], "seller": seller.identity.model_dump(mode="json")}
        commitment = peer.data["filing"]["request"]["transaction"]
        binding = DisputeBinding("example", commitment, authority)
        payment = Payment()
        mediation_down = [mode == "both-down"]
        no_ack = [mode == "no-ack"]

        def mediation_transport(request):
            if mediation_down[0]:
                raise httpx.ConnectError("fixture mediation outage", request=request)
            return peer.handle(request)

        # Public deterministic development token; never use on a public network.
        async with MediationClient(
            authority, MediationCredential(authority.identity, "DEMO_PAYER"),
            environ={"DEMO_PAYER": "fixture-payer"}, transport=httpx.MockTransport(mediation_transport),
        ) as mediation:
            adapter = MediationAdapter(binding, agreement, mediation)
            path = Path(root) / "seller.sqlite"
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
                    buyer=buyer.identity, payment=PaymentSelector("fixture"),
                    dispute=None if mode == "no-adapter" else authority,
                ))
            ingress = DeliveryIngress(
                path, clock=lambda: int(time.time()), verify_site=lambda *_: None,
                receipt_claim=lambda _, at: None if mode == "no-adapter" else adapter.sign_delivery_end(
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
            store = FileEvidenceStore(Path(root) / "buyer")
            async with LifecycleClient(
                "http://fixture", buyer, TrustedIdentitySet(identities=(seller.identity,)),
                transport=httpx.ASGITransport(app=app), capture=store.capture,
            ) as client:
                class Peer:
                    async def end_delivery(self, negotiation_id, *, operation_key):
                        if no_ack[0]:
                            raise ConnectionError("fixture no acknowledgement")
                        return await client.end_delivery(negotiation_id, operation_key=operation_key)
                    def end_receipt(self, negotiation_id, operation_key):
                        return client.end_receipt(negotiation_id, operation_key)
                    async def hint(self, message):
                        return await client.hint(message)

                deal = BuyerDeal(
                    "example", commitment, PaymentBinding("example", PaymentSelector("fixture")),
                    dispute=None if mode == "no-adapter" else binding,
                    buyer=buyer.identity, seller=seller.identity,
                )
                def lifecycle():
                    return BuyerLifecycle(
                        deal=lambda _: deal, payments=PaymentAdapterTable([] if mode == "no-adapter" else [
                            (deal.payment.selector, lambda _: payment),
                        ]), disputes=DisputeAdapterTable([] if mode == "no-adapter" else [
                            (authority.interface, lambda _: adapter),
                        ]), operations=store, peer=Peer(), evidence=store,
                        end_journal=store.end_journal, clock=lambda: now,
                    )
                first = await lifecycle().end_delivery("example")
                if mode == "no-adapter":
                    assert first.delivery.status == "accepted" and first.payment.status == first.case.status == "rejected"
                    assert not peer.cases and not payment.calls
                elif mode == "no-ack":
                    assert first.delivery.status == "unknown" and first.contested
                    assert first.case.status == "accepted" and first.acknowledgement is None
                else:
                    assert first.delivery.status == "accepted" and first.payment.status == "unknown"
                    assert not first.contested and first.acknowledgement.signed_delivery_end_claim is not None
                    assert first.case.status == ("unknown" if mode == "both-down" else "accepted")
                payment.down = False
                mediation_down[0] = no_ack[0] = False
                recovered = await lifecycle().end_delivery("example")
                assert recovered.delivery.status == "accepted" and recovered.observed_at == first.observed_at
                if mode != "no-adapter":
                    assert recovered.payment.status == recovered.case.status == "accepted"
                    assert len(payment.calls) == 2 and payment.calls[0] == payment.calls[1]
                    assert len(peer.cases) == 1
                    filed = next(entry["entry"]["filing"] for entry in peer.entries if entry["entry"]["kind"] == "filed")
                    assert ("concurrence" in filed) == (mode != "no-ack")
                    if mode == "no-ack":
                        assert filed["request"]["ended_at"] == first.observed_at and recovered.contested
                assert any(item.kind == "end_delivery_receipt" for item in (await store.read("example")).items)
                try:
                    await client.end_delivery("example", at=now - 1)
                except TypeError:
                    pass
                else:
                    raise AssertionError("canonical client accepted a supplied instant")
                print(mode, first.payment.status, first.delivery.status, first.case.status, "=>",
                      recovered.payment.status, recovered.delivery.status, recovered.case.status)


async def main():
    for mode in ("payment-down", "both-down", "no-ack", "no-adapter"):
        await scenario(mode)


if __name__ == "__main__":
    asyncio.run(main())
