"""Each route service's refusal is the status and body the service's baseline records."""

from __future__ import annotations

import json
from importlib.metadata import version as installed_version
from pathlib import Path

import pytest
from arkhai_api.issuance import KeyDisposition, issuance_request
from arkhai_api.labels import IssuanceLabel
from arkhai_api_authority import AuthorityRouteService, IssuanceError, RouteRefusal, SystemRouteService
from market_identity import Identity

REFUSALS = json.loads(
    (
        Path(__file__).resolve().parents[5]
        / "domains" / "apicredits" / "service" / "tests" / "fixtures" / "baseline" / "refusals.json"
    ).read_text(encoding="utf-8")
)
OWNER = Identity(scheme="eip191", identifier="0xabcdef0000000000000000000000000000000001")


class _Keys:
    """A key service scripted per test: each method returns or raises what the test sets."""

    def __init__(self, **outcomes):
        self._outcomes = outcomes

    def __getattr__(self, name):
        outcome = self._outcomes[name]

        def call(*args, **kwargs):
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        return call


def _request():
    return issuance_request(
        IssuanceLabel("example"),
        negotiation_id="neg-1", owner=OWNER, service="svc", resource_id="q", quantity=100,
        key=KeyDisposition(mode="existing", key_id="ak_missing"),
    )


def _refusal(call) -> tuple[int, dict]:
    with pytest.raises(RouteRefusal) as refused:
        call()
    return refused.value.status_code, refused.value.body


@pytest.mark.parametrize(
    ("record", "reason", "message"),
    [
        ("issuance_key_not_found", "key_not_found", "key 'ak_missing' not found"),
        ("issuance_key_not_owned", "key_not_owned", "key is bound to a different marketplace principal"),
        ("issuance_quota_exhausted", "quota_exhausted", "no quota resource can cover 100 units"),
        ("issuance_fulfillment_conflict", "fulfillment_conflict", "fulfillment_id is already bound to a different issuance request"),
    ],
)
def test_an_issuance_refusal_is_recorded_status_and_body(record, reason, message):
    service = AuthorityRouteService(_Keys(issue=IssuanceError(reason, message)))
    status, body = _refusal(lambda: service.issue(_request()))
    assert {"status": status, "body": body} == REFUSALS[record]


def test_issuance_onto_a_revoked_key_is_a_409_naming_the_key():
    service = AuthorityRouteService(_Keys(issue=IssuanceError("key_revoked", "key 'ak_missing' is revoked")))
    assert _refusal(lambda: service.issue(_request())) == (
        409, {"error": "key_revoked", "detail": "key 'ak_missing' is revoked"},
    )


def test_an_invalid_issuance_input_is_a_422_with_its_detail():
    service = AuthorityRouteService(_Keys(issue=ValueError("owner is required")))
    assert _refusal(lambda: service.issue(_request())) == (422, {"detail": "owner is required"})


def test_an_unknown_issuance_or_key_is_the_recorded_404():
    service = AuthorityRouteService(_Keys(get_credit_issuance=None, get_key=None, revoke=None, adjust=None))
    assert _refusal(lambda: service.get_issuance("f")) == (
        REFUSALS["issuance_not_found"]["status"], REFUSALS["issuance_not_found"]["body"],
    )
    for call, record in (
        (lambda: service.get_key("ak_missing"), "key_not_found"),
        (lambda: service.revoke("ak_missing"), "revoke_key_not_found"),
        (lambda: service.adjust("ak_missing", delta=1, reason=None), "key_not_found"),
    ):
        assert _refusal(call) == (REFUSALS[record]["status"], REFUSALS[record]["body"])


@pytest.mark.parametrize(
    ("record", "outcome"),
    [
        ("consume_key_not_found", {"ok": False, "reason": "key_not_found", "balance": 0}),
        ("consume_key_revoked", {"ok": False, "reason": "key_revoked", "balance": 0}),
        ("consume_insufficient_credits", {"ok": False, "reason": "insufficient_credits", "balance": 0}),
    ],
)
def test_a_refused_consumption_is_recorded_status_and_body(record, outcome):
    service = AuthorityRouteService(_Keys(consume=outcome))
    status, body = _refusal(lambda: service.consume("k", amount=1, idempotency_key=None))
    assert {"status": status, "body": body} == REFUSALS[record]


def test_an_admitted_consumption_and_a_batch_pass_through():
    outcome = {"ok": True, "consumed": 1, "balance": 4}
    service = AuthorityRouteService(_Keys(consume=outcome, consume_batch=[outcome, {"ok": False}]))
    assert service.consume("k", amount=1, idempotency_key="r1") == outcome
    assert service.consume_batch([{"key_id": "k", "amount": 1}]) == {"results": [outcome, {"ok": False}]}


def test_an_adjustment_below_zero_is_the_recorded_409():
    service = AuthorityRouteService(
        _Keys(adjust=ValueError("adjustment -999 would take balance 3 below zero"))
    )
    status, body = _refusal(lambda: service.adjust("k", delta=-999, reason=None))
    assert {"status": status, "body": body} == REFUSALS["adjust_below_zero"]


def test_lists_carry_their_totals():
    service = AuthorityRouteService(_Keys(list_keys=[{"key_id": "k"}], list_grants=[], list_usage=[{}, {}]))
    assert service.list_keys(status=None, owner_id=None) == {"keys": [{"key_id": "k"}], "total": 1}
    assert service.list_grants("k") == {"grants": [], "total": 0}
    assert service.list_usage("k", after_id=0, limit=10)["total"] == 2


def test_the_version_route_reports_the_configured_distribution_and_its_installed_version():
    assert SystemRouteService("pytest").version() == {
        "service": "pytest",
        "version": installed_version("pytest"),
    }
    assert SystemRouteService("no-such-distribution").version()["version"] == "dev"
