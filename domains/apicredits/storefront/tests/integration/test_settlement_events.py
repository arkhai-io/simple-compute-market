"""The settlement composition hands its servicing worker the storefront's
event callback, so a failing step reaches the deal's stage record.

The composition is built as the storefront builds it, over a real SQLite
database; an obligation naming a mechanism no client serves makes the
worker's status step fail.
"""

from __future__ import annotations

import json
import logging

from market_identity import Ed25519Signer

from apicredits_storefront.domain_runtime import get_market_domain_contract
from apicredits_storefront.settlement_composition import (
    build_api_credit_settlement_composition,
)
from apicredits_storefront.utils.sqlite_client import SQLiteClient

# Deterministic development keys; never use them on a public network.
_SELLER = Ed25519Signer(b"\x22" * 32)
_BUYER = Ed25519Signer(b"\x23" * 32)


async def test_a_failing_servicing_step_is_recorded_as_a_claims_event(
    tmp_path, caplog
) -> None:
    composition = build_api_credit_settlement_composition(
        domain=get_market_domain_contract(),
        sqlite_client=SQLiteClient(str(tmp_path / "events.db")),
        alkahest_clients={},
        marketplace_signer=_SELLER,
        failure_policy=None,
    )
    [record] = await composition.runtime.register_plan(
        agreement_ref="agreement-events",
        obligations=[
            {
                "payer": "buyer",
                "claimant": "seller",
                "payer_principal": _BUYER.identity.model_dump(mode="json"),
                "claimant_principal": _SELLER.identity.model_dump(mode="json"),
                "mechanism": "unserved.v1",
                "expiration_unix": 4_102_444_800,
            }
        ],
    )

    with caplog.at_level(logging.INFO, logger="stage"):
        await composition.worker.service_obligation(record.obligation_ref)

    events = [json.loads(r.getMessage()) for r in caplog.records if r.name == "stage"]
    assert [
        (e["stage"], e["event"], e["obligation_ref"], e["operation"]) for e in events
    ] == [("claims", "settlement_retry", record.obligation_ref, "status")]
