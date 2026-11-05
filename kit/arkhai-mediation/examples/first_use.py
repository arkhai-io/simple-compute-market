"""Try mediation filing, lost-response recovery and claimant evidence without a server."""

import asyncio
import json

from market_deal_lifecycle.adapters import DisputeAdapterTable, DisputeBinding, submit_dispute
from market_deal_lifecycle.terms import DisputeAuthority
from market_deal_lifecycle_contracts.models import LifecycleCommand
from pydantic import SecretStr

from market_arkhai_mediation.adapter import MediationAdapter
from market_arkhai_mediation.client import MediationClient, MediationCredential
from market_arkhai_mediation.fixtures.authority import MediationContractFake


class DemoOperations:
    """An in-memory replay guard; role compositions supply durable storage."""

    def __init__(self):
        self.commands: dict[tuple[str, str], str] = {}

    async def check_and_record(self, negotiation_id: str, operation_key: str, digest: str) -> bool:
        return self.commands.setdefault((negotiation_id, operation_key), digest) == digest


async def main():
    peer = MediationContractFake()
    authority = DisputeAuthority.model_validate(peer.authority)
    filing = peer.data["filing"]["request"]
    binding = DisputeBinding("negotiation-fixture", filing["transaction"], authority)
    # Public deterministic fixture credential; never use it on a public network.
    # A role resolves the token from its [[DisputeCredential]] and passes it in.
    async with MediationClient(
        authority, MediationCredential(authority.identity, token=SecretStr("fixture-payee")),
        transport=peer.transport(),
    ) as client:
        adapter = MediationAdapter(binding, filing["agreement"], client, clock=lambda: 1800001800)
        table = DisputeAdapterTable([(authority.interface, lambda _: adapter)])
        operations = DemoOperations()
        request = adapter.effects_request(
            [{"kind": "reverse", "part": 0, "amount": "1"}],
            claim="Operator review of a partial failure.",
            items=filing["items"],
        )
        command = LifecycleCommand(
            negotiation_id=binding.negotiation_id, kind="dispute", operation_key="demo-filing",
            payload=request.model_dump(mode="json"),
        )
        peer.lose_next_response = True
        lost = await submit_dispute(command, binding, table, operations)
        observed = await adapter.read()
        recovered = await submit_dispute(command, binding, table, operations)
        if recovered.status != "accepted" or recovered.filing is None:
            raise RuntimeError("demo filing was not recovered")
        append = LifecycleCommand(
            negotiation_id=binding.negotiation_id, kind="append", operation_key="demo-append",
            payload={"case_ref": recovered.filing.case_ref, "items": filing["items"]},
        )
        appended = await submit_dispute(append, binding, table, operations)
        final = await adapter.read()
        assert lost.status == "unknown" and len(observed.cases) == 1
        assert appended.status == "accepted" and len(peer.cases) == 1
        assert final.outcome.status == "accepted" and [event.sequence for event in final.disputes] == [1, 2]
        print(json.dumps({
            "target": "kit-owned in-process contract fake; no hosted service",
            "persona": "payee claimant",
            "lost_response": lost.status, "read_cases": len(observed.cases),
            "recovered": recovered.model_dump(mode="json"), "append": appended.status,
            "record_sequences": [event.sequence for event in final.disputes],
            "cases_created": len(peer.cases),
        }, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
