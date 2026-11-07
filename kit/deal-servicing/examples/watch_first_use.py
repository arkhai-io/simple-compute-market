"""Try respondent-owned answers and ruling replay with a vendored authority."""

import asyncio
import base64
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from market_arkhai_mediation.adapter import MediationAdapter
from market_arkhai_mediation.client import MediationClient, MediationCredential
from market_arkhai_mediation.fixtures.authority import MediationContractFake
from market_arkhai_mediation.models import Filing
from market_deal_lifecycle.adapters import DisputeBinding
from market_deal_lifecycle.terms import DisputeAuthority
from market_deal_lifecycle_contracts.models import EvidenceItem
from market_identity import Identity
from pydantic import SecretStr

from market_deal_servicing import DeliveryRecord, EndService, EndSession, PhysicalResult
from market_deal_servicing.evidence import EvidenceSession, transaction
from market_deal_servicing.watch import DealWatch, WatchSession


class DemoDelivery:
    def __init__(self):
        self.effects = set()

    async def apply_end(self, negotiation_id, *, terminate, at, operation_key):
        self.effects.add(operation_key)
        return PhysicalResult(progress="released", done=True)


async def main():
    peer = MediationContractFake()
    authority = DisputeAuthority.model_validate(peer.authority)
    filing = peer.data["filing"]["request"]
    negotiation = "watch-fixture"
    binding = DisputeBinding(negotiation, filing["transaction"], authority)
    now = peer.data["records"][0]["signed"]["entry"]["at"] + 1000
    seller = Identity.model_validate(filing["agreement"]["seller"])
    with TemporaryDirectory(prefix="seller-watch-") as root:
        path = Path(root) / "storefront.sqlite"
        physical = DemoDelivery()
        end = EndService(path, physical, clock=lambda: now)
        with transaction(path) as conn:
            EndSession(conn).register(DeliveryRecord(
                negotiation_id=negotiation, seller=seller, commitment_ref=binding.commitment_ref,
                start_at=now - 2000, term_end=now + 1000, committed_at=now - 2000,
            ))
            EvidenceSession(conn).capture(
                negotiation, evidence_id="buyer-message", body=b'{"buyer":"exact fixture message"}',
                headers={"proof": "fixture transport context"}, context={"producer": "buyer"},
                recorded_at=now - 2000,
            )

        def capture(body):
            with transaction(path) as conn:
                EvidenceSession(conn).put(negotiation, EvidenceItem(
                    evidence_id="mediation-response:" + hashlib.sha256(body).hexdigest(),
                    kind="authority_response", classification="independent",
                    recorded_at=now, body=base64.b64encode(body),
                ))

        # Public deterministic fixture credentials; never use on a public network.
        async with MediationClient(
            authority, MediationCredential(authority.identity, token=SecretStr("fixture-payer")),
            transport=peer.transport(),
        ) as buyer, MediationClient(
            authority, MediationCredential(authority.identity, token=SecretStr("fixture-payee")),
            transport=peer.transport(), capture=capture,
        ) as seller_client:
            await buyer.file(Filing.model_validate(filing), idempotency_key="buyer-case")
            adapter = MediationAdapter(binding, filing["agreement"], seller_client, clock=lambda: now)

            def watch():
                return DealWatch(
                    path, negotiation_id=negotiation, commitment_ref=binding.commitment_ref,
                    payment=None, dispute=adapter, dispute_binding=binding, seller_account=peer.payee,
                    actor=lambda _: seller, clock=lambda: now,
                )

            # Discovery owns counterparty answers; watch cannot preempt them.
            await watch().poll()
            case = next(iter(peer.cases))
            peer.decide(case, [{
                "id": "end-effect", "effect": {"kind": "end_delivery", "at": now - 100},
                "state": "prepared",
            }])
            await watch().poll()
            await end.drive_physical(negotiation)
            peer.decide(case, [{
                "id": "end-effect", "effect": {"kind": "end_delivery", "at": now - 100},
                "state": "applied",
            }])
            await watch().poll()
            await end.drive_physical(negotiation)
            second = {**filing, "claim": "A second independent case."}
            await buyer.file(Filing.model_validate(second), idempotency_key="buyer-case-two")
            second_case = next(key for key in peer.cases if key != case)
            peer.decide(second_case, [])
            await watch().poll()
            current_watch = watch()
            with transaction(path) as conn:
                intents = EndSession(conn).intents(negotiation)
                assert not [item for item in intents if item.kind == "append"]
                assert not [record for record in peer.entries if record["entry"]["kind"] == "appended"]
                assert len(physical.effects) == 1
                assert EndSession(conn).view(negotiation).recorded_end.ended_at == now - 100
                assert WatchSession(conn).cursor(negotiation, "payment:" + binding.commitment_ref) == -1
                print(json.dumps({
                    "append": [item.state for item in intents if item.kind == "append"],
                    "appended_records": sum(record["entry"]["kind"] == "appended" for record in peer.entries),
                    "physical_effects": len(physical.effects),
                    "recorded_end": EndSession(conn).view(negotiation).recorded_end.ended_at,
                    "dispute_cursor": WatchSession(conn).cursor(negotiation, current_watch.dispute_record),
                    "payment_cursor": WatchSession(conn).cursor(negotiation, "payment:" + binding.commitment_ref),
                }))


if __name__ == "__main__":
    asyncio.run(main())
