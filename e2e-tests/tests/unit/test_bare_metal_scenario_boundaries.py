"""Pure parsing and validation boundaries owned by the whole-host scenario."""

from __future__ import annotations

import pytest

from arkhai_bare_metal import BareMetalAccessResult, BareMetalReceipt
from arkhai_bare_metal_storefront.models import (
    BareMetalFulfillmentResponse,
    BareMetalFulfillmentResultResponse,
)

from tests.e2e.roles.scenarios.bare_metal import test_bare_metal_deal as scenario


NEGOTIATION_ID = "neg-1"
SITE_ID = "demo-site"
ESCROW_UID = "0x" + "ab" * 32
MACHINE_ID = "demo-node"
PHYSICAL_HOST_ID = "demo-host"


def _fulfillment(state: str) -> dict:
    return BareMetalFulfillmentResponse(
        negotiation_id=NEGOTIATION_ID,
        escrow_uid=ESCROW_UID,
        site_id=SITE_ID,
        state=state,
    ).model_dump(mode="json")


def _result_response() -> dict:
    return BareMetalFulfillmentResultResponse(
        negotiation_id=NEGOTIATION_ID,
        receipt=BareMetalReceipt(
            escrow_uid=ESCROW_UID,
            machine_id=MACHINE_ID,
            physical_host_id=PHYSICAL_HOST_ID,
            status="active",
        ),
        result=BareMetalAccessResult(
            action="node_grant_access",
            machine_id=MACHINE_ID,
            physical_host_id=PHYSICAL_HOST_ID,
            ssh_user="arkhai-0123456789abcdef",
            escrow_uid=ESCROW_UID,
        ),
    ).model_dump(mode="json")


@pytest.mark.parametrize(
    "proof",
    [
        "arkhai-uid=0\narkhai-groups=root\narkhai-sudo=refused\n",
        "arkhai-uid=1001\narkhai-groups=arkhai sudo\narkhai-sudo=refused\n",
        "arkhai-uid=1001\narkhai-groups=arkhai\narkhai-sudo=granted\n",
        "arkhai-bare-metal-access-ok",
        "arkhai-uid=1001\narkhai-groups=arkhai\n",
    ],
)
def test_privileged_or_incomplete_access_proof_is_rejected(proof: str) -> None:
    with pytest.raises(AssertionError):
        scenario._assert_unprivileged_buyer_session(scenario._parse_access_proof(proof))


def test_complete_unprivileged_access_proof_is_accepted() -> None:
    proof = scenario._parse_access_proof(
        "arkhai-uid=1001\narkhai-groups=arkhai-0123456789abcdef\narkhai-sudo=refused\n"
    )

    scenario._assert_unprivileged_buyer_session(proof)
    assert proof.uid == 1001


def test_the_leased_host_is_read_from_the_receipt() -> None:
    view = _result_response()

    assert scenario._leased_host(view) == scenario.LeasedHost(
        machine_id=MACHINE_ID,
        physical_host_id=PHYSICAL_HOST_ID,
    )
    with pytest.raises(AssertionError):
        scenario._leased_host({"machine_id": MACHINE_ID, "physical_host_id": PHYSICAL_HOST_ID})


def test_a_receipt_the_executor_contradicts_is_refused() -> None:
    view = _result_response()
    view["result"]["physical_host_id"] = "another-host"

    with pytest.raises(AssertionError):
        scenario._leased_host(view)


def test_the_physical_state_is_read_from_the_status_envelope() -> None:
    assert scenario._fulfillment_state({"fulfillment": _fulfillment("active")}) == "active"
    with pytest.raises(AssertionError):
        scenario._fulfillment_state({"status": "released"})
