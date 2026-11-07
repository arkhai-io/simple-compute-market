"""Try bounded seller views and an immediate operator end with the vendored authority."""

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from market_arkhai_mediation.adapter import MediationAdapter
from market_arkhai_mediation.client import MediationClient, MediationCredential
from market_arkhai_mediation.fixtures.authority import MediationContractFake
from market_deal_lifecycle.adapters import DisputeAdapterTable, PaymentAdapterTable, PaymentSelector
from market_deal_lifecycle.terms import DisputeAuthority
from market_deal_lifecycle_contracts.models import LifecycleCommand, ListDealsRequest
from market_identity import Ed25519Signer, Identity
from pydantic import SecretStr

from market_deal_servicing import (
    DealWatch, DeliveryRecord, EndService, EndSession, PhysicalResult,
    SellerDeal, SellerServicing, SellerSession,
)
from market_deal_servicing.evidence import transaction


class DemoDelivery:
    def __init__(self):
        self.effects = set()

    async def apply_end(self, negotiation_id, *, terminate, at, operation_key):
        self.effects.add(operation_key)
        return PhysicalResult(progress="tearing_down", done=True)


async def main():
    peer = MediationContractFake()
    authority = DisputeAuthority.model_validate(peer.authority)
    agreement = peer.data["filing"]["request"]["agreement"]
    commitment = peer.data["filing"]["request"]["transaction"]
    seller = Identity.model_validate(agreement["seller"])
    now = [peer.data["records"][0]["signed"]["entry"]["at"] + 1000]
    has_credential = [True]
    with TemporaryDirectory(prefix="seller-api-") as root:
        path = Path(root) / "storefront.sqlite"
        physical = DemoDelivery()
        end = EndService(path, physical, clock=lambda: now[0])
        # Public deterministic fixture credential; never use on a public network.
        async with MediationClient(
            authority, MediationCredential(authority.identity, token=SecretStr("fixture-payee")),
            transport=peer.transport(),
        ) as client:
            def make_watch(deal, payment, dispute):
                return DealWatch(
                    path, negotiation_id=deal.negotiation_id, commitment_ref=deal.commitment_ref,
                    payment=payment, dispute=dispute, dispute_binding=deal.dispute_binding,
                    seller_account=peer.payee, actor=lambda _: seller, clock=lambda: now[0],
                )

            def service():
                return SellerServicing(
                    path, payments=PaymentAdapterTable([]),
                    disputes=DisputeAdapterTable([(
                        authority.interface, lambda binding: MediationAdapter(
                            binding, agreement, client, clock=lambda: now[0],
                        ),
                    )]),
                    credential_available=lambda pinned: has_credential[0] and pinned.identity == authority.identity,
                    watch_factory=make_watch, clock=lambda: now[0],
                )

            api = service()
            empty = await api.list()
            assert empty.deals == [] and empty.continuation is None
            print(json.dumps({"empty": empty.model_dump(mode="json")}))
            with transaction(path) as conn:
                for name in ("once-a", "once-b"):
                    EndSession(conn).register(DeliveryRecord(
                        negotiation_id=name, seller=seller, commitment_ref=commitment,
                        start_at=now[0] - 100, committed_at=now[0] - 100, term_end=now[0] + 1000,
                        available_at=now[0] - 50, progress="active",
                    ))
                    SellerSession(conn).register(SellerDeal(
                        negotiation_id=name, commitment_ref=commitment, domain="fixture-compute",
                        buyer=Ed25519Signer(bytes([1]) * 32).identity,
                        payment=PaymentSelector("arkhai.payments.v1"), dispute=authority, once_only=True,
                    ))
            first = await api.list(ListDealsRequest(limit=1))
            second = await api.list(ListDealsRequest(limit=1, continuation=first.continuation))
            has_credential[0] = False
            repair = await api.list()
            has_credential[0] = True
            command = LifecycleCommand(negotiation_id="once-a", kind="delivery_end", operation_key="interrupt")
            peer.lose_next_response = True
            uncertain = await api.submit(command, actor=seller, reason="fixture operator maintenance")
            await end.drive_physical("once-a")
            now[0] += 1
            replay = await service().submit(command, actor=seller, reason="fixture operator maintenance")
            await end.drive_physical("once-a")
            read = await api.read("once-a")
            with transaction(path) as conn:
                requests = EndSession(conn).requests("once-a")
            assert [[deal.negotiation_id for deal in page.deals] for page in (first, second)] == [["once-a"], ["once-b"]]
            assert first.deals[0].state == "running"
            assert all(deal.state == "repair_required" for deal in repair.deals)
            assert uncertain.status == "unknown" and replay.status == "accepted"
            assert len(peer.cases) == len(physical.effects) == 1
            assert requests[0].actor == seller and requests[0].administrator_reason == "fixture operator maintenance"
            assert read.delivery.progress == "tearing_down"
            print(json.dumps({
                "pages": [[deal.negotiation_id for deal in page.deals] for page in (first, second)],
                "initial_states": [deal.state for deal in first.deals],
                "missing_credential": [deal.state for deal in repair.deals],
                "lost_response": uncertain.status, "restart_replay": replay.status,
                "one_case": len(peer.cases), "one_physical_effect": len(physical.effects),
                "attributed_end": requests[0].model_dump(mode="json"),
                "delivery": read.delivery.model_dump(mode="json"),
                "case_state": [case.state for case in read.authority.cases],
            }))


if __name__ == "__main__":
    asyncio.run(main())
