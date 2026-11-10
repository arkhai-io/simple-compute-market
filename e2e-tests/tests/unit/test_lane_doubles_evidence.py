"""A payment scenario records its lane-double evidence from the doubles' status.

The doubles are stood in for by an httpx mock transport behind the controls
package's typed client, so the status route, the control token and the
answer's model are the client's own. Every value below is a development
fixture, never used on any network.
"""

from __future__ import annotations

import logging

import httpx
import pytest

from lane_double_controls import ControlClient, Status, routes

from tests.e2e.roles.helpers import lane_doubles
from tests.e2e.roles.helpers.mediation import MediationTarget

_TOKEN = "lane-double-control-public-development-token"
_PAYMENTS = {"schema/payments.schema.json": "aa" * 32, "test-vectors/payments.json": "bb" * 32}
_MEDIATION = {"contract_data/mediation.schema.json": "cc" * 32}
_EVIDENCE = lane_doubles.LaneDoublesEvidence(
    label=lane_doubles.LANE_DOUBLES, payments_contracts=_PAYMENTS, mediation_contracts=_MEDIATION,
)


def _target(*, lane_owned: bool) -> MediationTarget:
    return MediationTarget(
        service_url="https://mediation-double:8443",
        account="00000000-0000-4000-8000-0000000000d1",
        record_key="ed25519:2b8hSHSKhcidparY7gsPwtEF_TnUGkx5ZTY1TwrikAw",
        api_key_env="MEDIATION_BUYER_API_KEY", lane_owned=lane_owned, control_token=_TOKEN,
    )


def _double(contracts: dict[str, str]) -> ControlClient:
    def answer(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == f"Bearer {_TOKEN}"
        assert (request.method, request.url.path) == (routes.STATUS.method, routes.STATUS.path)
        status = Status(perceived_now=1_800_000_000, offset_seconds=0, contracts=contracts)
        return httpx.Response(200, json=status.model_dump(mode="json"))

    return ControlClient("https://double.test", token=_TOKEN, transport=httpx.MockTransport(answer))


def test_the_evidence_is_labelled_lane_doubles_with_each_doubles_contract_hashes() -> None:
    with _double(_PAYMENTS) as payments, _double(_MEDIATION) as mediation:
        assert lane_doubles.read_lane_doubles_evidence(payments, mediation) == _EVIDENCE


def test_both_lane_owned_targets_log_the_evidence(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger=lane_doubles.__name__):
        evidence = lane_doubles.lane_doubles_evidence_of(
            _target(lane_owned=True), payments_lane_owned=True, read=lambda _: _EVIDENCE,
        )

    assert evidence == _EVIDENCE
    (record,) = caplog.records
    assert record.getMessage().startswith("[evidence] lane doubles: payments double contracts ")
    assert "mediation.schema.json" in record.getMessage()


@pytest.mark.parametrize(("mediation", "payments_lane_owned"), [
    (None, True),
    (_target(lane_owned=False), True),
    (_target(lane_owned=True), False),
])
def test_a_run_whose_targets_are_not_both_the_lanes_own_records_nothing(
    mediation: MediationTarget | None, payments_lane_owned: bool, caplog: pytest.LogCaptureFixture,
) -> None:
    def never_read(_: MediationTarget) -> lane_doubles.LaneDoublesEvidence:
        raise AssertionError("no double's status may be read")

    with caplog.at_level(logging.INFO, logger=lane_doubles.__name__):
        assert lane_doubles.lane_doubles_evidence_of(
            mediation, payments_lane_owned=payments_lane_owned, read=never_read,
        ) is None
    assert not caplog.records
