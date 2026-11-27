"""Each route service's refusal is the status and body the service's baseline records."""

from __future__ import annotations

import json
from importlib.metadata import version as installed_version
from pathlib import Path

import injected_time
import pytest
from arkhai_api.issuance import KeyDisposition, issuance_request
from arkhai_api.labels import IssuanceLabel
from arkhai_api_authority import AuthorityRouteService, IssuanceError, RouteRefusal, SystemRouteService
from injected_time import InjectedTime, WallTime
from market_identity import Identity

REFUSALS = json.loads(
    (
        Path(__file__).resolve().parents[3]
        / "contracts" / "tests" / "fixtures" / "baseline" / "refusals.json"
    ).read_text(encoding="utf-8")
)
T = 1794821400
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


@pytest.fixture
def source():
    """The process's time source, injected at ``T`` and restored afterwards."""
    before = injected_time.installed()
    yield injected_time.install(InjectedTime(start=T))
    injected_time.install(before)


def test_the_status_reports_the_installed_time_source(source):
    system = SystemRouteService("pytest")
    assert system.status() == {"time": {"source": "injected", "now": T}}
    injected_time.install(WallTime())
    assert system.status() == {"time": {"source": "wall"}}


def test_the_time_route_sets_the_injected_source_and_refuses_without_changing_it(source):
    system = SystemRouteService("pytest")
    assert system.set_time(b'{"now": %d}' % (T + 900)) == {"source": "injected", "now": T + 900}
    assert source.now() == T + 900
    earlier = _refusal(lambda: system.set_time(b'{"now": %d}' % T))
    invalid = _refusal(lambda: system.set_time(b'{"now": true}'))
    assert (earlier[0], earlier[1]["code"]) == (409, "time_moves_forward")
    assert (invalid[0], invalid[1]["code"]) == (422, "invalid_time")
    assert source.now() == T + 900


@pytest.mark.parametrize(("reason", "status"), [("key_out_of_scope", 409), ("terms_digest_mismatch", 422)])
def test_a_scope_or_terms_refusal_of_issuance_names_its_reason(reason, status):
    routes = AuthorityRouteService(_Keys(issue=IssuanceError(reason, "refused")))
    assert _refusal(lambda: routes.issue(_request())) == (status, {"error": reason, "detail": "refused"})


def test_a_consumption_outside_the_keys_scope_is_a_403():
    routes = AuthorityRouteService(_Keys(consume={"ok": False, "reason": "key_out_of_scope", "balance": 0}))
    assert _refusal(lambda: routes.consume("ak_1", amount=1, idempotency_key=None, service="svc")) == (
        403, {"error": "key_out_of_scope", "balance": 0},
    )
