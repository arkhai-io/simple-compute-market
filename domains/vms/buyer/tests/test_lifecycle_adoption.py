"""Buyer transport recovery adopts the authority's signed original case."""

import asyncio

import pytest
from market_arkhai_mediation.adapter import MediationAdapter
from market_arkhai_mediation.client import (
    MediationClient, MediationCredential, MediationTransportError,
)
from market_arkhai_mediation.fixtures.authority import MediationContractFake
from market_deal_lifecycle.adapters import (
    DeliveryEndIntent, DisputeAdapterTable, DisputeBinding, submit_dispute,
)
from market_deal_lifecycle.configuration import DisputeCredential
from market_deal_lifecycle.terms import DisputeAuthority
from market_deal_lifecycle_buyer.store import FileEvidenceStore
from market_deal_lifecycle_contracts.models import LifecycleCommand
from pydantic import SecretStr

from arkhai_vms_buyer.lifecycle import _MediationPort


def test_lost_filing_response_is_adopted_through_buyer_port(tmp_path):
    async def drive():
        peer = MediationContractFake()
        authority = DisputeAuthority.model_validate(peer.authority)
        filing = peer.data["filing"]["request"]
        binding = DisputeBinding("deal", filing["transaction"], authority)
        # Missing credentials stay lazy, so receipt-only surrender remains usable.
        port = _MediationPort(authority, None)
        assert port.client is None
        async with MediationClient(
            authority, MediationCredential(authority.identity, token=SecretStr("fixture-payee")),
            transport=peer.transport(),
        ) as client:
            port.client = client
            adapter = MediationAdapter(binding, filing["agreement"], port, clock=lambda: 1800001800)
            table = DisputeAdapterTable([(authority.interface, lambda _: adapter)])
            command = LifecycleCommand(
                negotiation_id="deal", kind="delivery_end", operation_key="buyer-end",
                payload=DeliveryEndIntent(ended_at=1800000000, delivered=False, cause="payee").model_dump(mode="json"),
            )
            peer.lose_next_response = True
            first = await submit_dispute(command, binding, table, FileEvidenceStore(tmp_path))
            assert first.status == "unknown" and len(peer.cases) == 1
            recovered = await submit_dispute(command, binding, table, FileEvidenceStore(tmp_path))
            assert recovered.status == "accepted"
            assert recovered.filing.case_ref == next(iter(peer.cases))
            assert recovered.records[0].kind == "filed"
            assert len(peer.cases) == 1
            assert len([r for r in peer.requests if r.method == "POST"]) == 1

    asyncio.run(drive())


def test_a_credential_that_does_not_resolve_is_a_transport_error_at_io(monkeypatch):
    monkeypatch.delenv("BUYER_MEDIATION_TOKEN", raising=False)
    authority = DisputeAuthority.model_validate(MediationContractFake().authority)
    credential = DisputeCredential.model_validate(
        dict(zip(("interface", "origin", "account", "record_key"), authority.identity))
        | {"api_key_env": "BUYER_MEDIATION_TOKEN"}
    )
    port = _MediationPort(authority, credential)
    with pytest.raises(MediationTransportError, match="unavailable"):
        asyncio.run(port.case("case-ref", agreement="a", transaction="t"))
    assert port.client is None
