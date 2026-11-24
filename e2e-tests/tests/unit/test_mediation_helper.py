"""The run's mediation target: a lane's own fails by name, an external one blocks.

A run naming no mediation target has its case stages blocked and its buyers
written without a dispute credential. Once a target is named, a missing setting
fails rather than hiding a broken configuration behind a skip, and an unready
target blocks the stages unless it is the lane's own (LANE_OWNED), which fails
them, naming it. A live verification scenario refuses a lane-owned target
with a blocked skip naming it, and fails a run stating no buyer token; an
Agreement pinning another authority than the run's target is named with both.
The buyer's credential names its token's variable, and the harness hands the
token over under it. A target reached through MEDIATION.PROXY_URL is probed and
read through that proxy alone, and the buyer processes receive it as their
HTTPS_PROXY with loopback excluded. Every value below is a development
fixture, never used on any network.
"""

from __future__ import annotations

import dataclasses
import json
import re
import ssl
import tomllib
from pathlib import Path
from typing import Any

import httpx
import pytest
from market_arkhai_mediation.fixtures.authority import MediationContractFake
from market_arkhai_mediation.records import RecordVerificationError
from market_deal_lifecycle.configuration import AuthorityIdentity, dispute_config

from tests.e2e.roles.helpers import mediation

Failed = pytest.fail.Exception
Skipped = pytest.skip.Exception
# The lanes' public development CA, a real bundle the transport can load.
_LANE_CA = Path(__file__).resolve().parents[3] / "tools/lane-double-controls/tls/lane-ca.pem"

# The lanes' mediation double's identity and tokens, public development values.
_EXTERNAL = {
    "SERVICE_URL": "https://mediation-double:8443/",
    "ACCOUNT": "00000000-0000-4000-8000-0000000000d1",
    "RECORD_KEY": "ed25519:2b8hSHSKhcidparY7gsPwtEF_TnUGkx5ZTY1TwrikAw",
    "API_KEY_ENV": "MEDIATION_BUYER_API_KEY",
    "BUYER_API_KEY": "mediation-lane-double-buyer-public-development-token",
}
_LANE_OWNED = {
    **_EXTERNAL, "LANE_OWNED": True, "CA_BUNDLE_PATH": "/run/lane-doubles/lane-ca.pem",
    "CONTROL_TOKEN": "mediation-lane-double-control-public-development-token",
}


class _Settings:
    def __init__(self, values: dict[str, Any]) -> None:
        self._values = {f"MEDIATION.{key}": value for key, value in values.items()}

    def get(self, key: str, default: object = None) -> object:
        assert key.startswith("MEDIATION."), key
        return self._values.get(key, default)


@pytest.fixture
def configure(monkeypatch):
    def _configure(**values: Any) -> None:
        monkeypatch.setattr(mediation, "settings", _Settings(values))

    return _configure


def _never_asked(_url: str) -> bool:
    raise AssertionError("readiness must not be checked")


def _ready(_url: str) -> bool:
    return True


def _unready(_url: str) -> bool:
    return False


def _outcome(**kwargs: Any) -> BaseException:
    """The skip or failure `configured_mediation` raises, caught so that a wrong
    skip fails this test instead of being reported as a skipped test."""
    try:
        mediation.configured_mediation(**kwargs)
    except (Skipped, Failed) as raised:
        return raised
    raise AssertionError("configured_mediation neither skipped nor failed")


@pytest.mark.parametrize("url", ["", "   ", None])
def test_no_target_blocks_the_case_stages_naming_the_setting(configure, url) -> None:
    configure(SERVICE_URL=url)
    outcome = _outcome(ready=_never_asked)
    assert isinstance(outcome, Skipped)
    assert "blocked: MEDIATION.SERVICE_URL not configured" in str(outcome)


def test_no_target_writes_no_buyer_credential(configure) -> None:
    configure()
    assert mediation.mediation_if_configured(ready=_never_asked) is None
    assert mediation.buyer_dispute_credential_toml(None) == ()
    assert mediation.buyer_mediation_environment(None) == {}


def test_a_lane_owned_target_with_no_url_fails(configure) -> None:
    configure(LANE_OWNED=True)
    outcome = _outcome(ready=_never_asked)
    assert isinstance(outcome, Failed)
    assert "MEDIATION.LANE_OWNED is set but MEDIATION.SERVICE_URL is not configured" in str(outcome)


@pytest.mark.parametrize("missing", ["ACCOUNT", "RECORD_KEY", "API_KEY_ENV"])
def test_a_named_target_missing_a_setting_fails_naming_it(configure, missing) -> None:
    configure(**{key: value for key, value in _EXTERNAL.items() if key != missing})
    outcome = _outcome(ready=_never_asked)
    assert isinstance(outcome, Failed)
    assert f"MEDIATION.{missing} not configured" in str(outcome)


def test_a_lane_owned_target_needs_its_control_token(configure) -> None:
    configure(**{key: value for key, value in _LANE_OWNED.items() if key != "CONTROL_TOKEN"})
    outcome = _outcome(ready=_never_asked)
    assert isinstance(outcome, Failed)
    assert "MEDIATION.CONTROL_TOKEN not configured" in str(outcome)


def test_an_unready_lane_owned_target_fails_naming_it(configure) -> None:
    configure(**_LANE_OWNED)
    outcome = _outcome(ready=_unready)
    assert isinstance(outcome, Failed)
    assert "the lane's own mediation service at https://mediation-double:8443 is not ready" in str(outcome)


def test_an_unready_external_target_blocks_naming_it(configure) -> None:
    configure(**_EXTERNAL)
    outcome = _outcome(ready=_unready)
    assert isinstance(outcome, Skipped)
    assert "blocked: mediation service at https://mediation-double:8443 is not ready" in str(outcome)


def test_a_non_boolean_lane_owned_flag_fails(configure) -> None:
    configure(**{**_LANE_OWNED, "LANE_OWNED": "yes"})
    outcome = _outcome(ready=_never_asked)
    assert isinstance(outcome, Failed)
    assert "MEDIATION.LANE_OWNED must be true or false" in str(outcome)


def test_a_ready_target_is_read_without_a_trailing_slash(configure) -> None:
    configure(**{**_LANE_OWNED, "LANE_OWNED": "true"})
    target = mediation.configured_mediation(ready=_ready)
    assert target == mediation.MediationTarget(
        service_url="https://mediation-double:8443", account=_LANE_OWNED["ACCOUNT"],
        record_key=_LANE_OWNED["RECORD_KEY"], api_key_env="MEDIATION_BUYER_API_KEY",
        lane_owned=True, ca_bundle_path="/run/lane-doubles/lane-ca.pem",
        buyer_api_key=_LANE_OWNED["BUYER_API_KEY"], control_token=_LANE_OWNED["CONTROL_TOKEN"],
    )


@pytest.mark.parametrize("lane_owned", [True, "true"])
def test_a_live_scenario_refuses_a_lane_owned_target_before_reading_anything(
        configure, lane_owned) -> None:
    configure(**{**_LANE_OWNED, "LANE_OWNED": lane_owned})
    with pytest.raises(Skipped, match=(
            r"blocked: the mediation target https://mediation-double:8443/ is a lane's own "
            r"double \(MEDIATION.LANE_OWNED\), which yields no live evidence")):
        mediation.live_mediation(ready=_never_asked)


def test_a_live_scenario_takes_an_external_target(configure) -> None:
    configure(**_EXTERNAL)
    target = mediation.live_mediation(ready=_ready)
    assert (target.service_url, target.lane_owned, target.buyer_api_key) == (
        "https://mediation-double:8443", False, _EXTERNAL["BUYER_API_KEY"])


def test_a_live_scenario_with_no_target_or_an_unready_one_is_blocked(configure) -> None:
    configure()
    with pytest.raises(Skipped, match="blocked: MEDIATION.SERVICE_URL not configured"):
        mediation.live_mediation(ready=_never_asked)
    configure(**_EXTERNAL)
    with pytest.raises(Skipped, match="blocked: mediation service at .* is not ready"):
        mediation.live_mediation(ready=_unready)


def test_a_live_scenario_with_no_buyer_token_fails_naming_it(configure) -> None:
    configure(**{key: value for key, value in _EXTERNAL.items() if key != "BUYER_API_KEY"})
    try:
        mediation.live_mediation(ready=_ready)
    except (Skipped, Failed) as raised:
        outcome: BaseException = raised
    else:
        raise AssertionError("live_mediation neither skipped nor failed")
    assert isinstance(outcome, Failed)
    assert "MEDIATION.BUYER_API_KEY not configured" in str(outcome)


def test_the_buyer_credential_binds_the_authority_and_resolves_the_handed_token(configure) -> None:
    """The buyer's own loader reads the written credential as bound to the
    target's identity, trusting the CA bundle, and resolves its token from the
    environment the harness hands each buyer process."""
    configure(**_LANE_OWNED)
    target = mediation.configured_mediation(ready=_ready)
    document = tomllib.loads("\n".join(mediation.buyer_dispute_credential_toml(target)))
    config = dispute_config(document, role="buyer")
    authority = AuthorityIdentity(
        interface="arkhai.mediation.v1", origin="https://mediation-double:8443",
        account=_LANE_OWNED["ACCOUNT"], record_key=_LANE_OWNED["RECORD_KEY"],
    )
    credential = config.credential_for(authority)
    assert credential is not None
    assert credential.api_key is None and credential.api_key_env == "MEDIATION_BUYER_API_KEY"
    assert credential.ca_bundle_path == "/run/lane-doubles/lane-ca.pem"
    environment = mediation.buyer_mediation_environment(target)
    assert environment == {"MEDIATION_BUYER_API_KEY": _LANE_OWNED["BUYER_API_KEY"]}
    assert credential.resolve(environment).get_secret_value() == _LANE_OWNED["BUYER_API_KEY"]


# The buyer's filing, against the mediation kit's in-process contract peer: its
# published authority, Agreement and transaction, and its fixture payer token.
# The claim's end is a fixed past instant, since the adapter refuses a future one.
_ENDED_AT = 1_700_000_000


def _peer_target(peer: MediationContractFake) -> mediation.MediationTarget:
    authority = peer.authority
    return mediation.MediationTarget(
        service_url=authority["origin"], account=authority["account"],
        record_key=authority["record_key"], api_key_env="MEDIATION_BUYER_API_KEY",
        lane_owned=True, buyer_api_key="fixture-payer",
    )


def _file(peer: MediationContractFake, tmp_path, transport: httpx.MockTransport):
    request = peer.data["filing"]["request"]
    return mediation.file_as_buyer(
        _peer_target(peer), negotiation_id="negotiation-fixture",
        transaction=request["transaction"], agreement=request["agreement"],
        store=tmp_path, ended_at=_ENDED_AT, transport=transport,
    )


def test_the_buyer_files_the_delivery_end_claim_through_the_adapter(tmp_path) -> None:
    peer = MediationContractFake()

    outcome = _file(peer, tmp_path, peer.transport())

    (filing,) = [request for request in peer.requests if request.method == "POST"]
    sent = json.loads(filing.content)
    assert filing.url.path == "/cases"
    assert filing.headers["authorization"] == "Bearer fixture-payer"
    assert sent["request"] == {"kind": "delivery_end", "ended_at": _ENDED_AT,
                               "delivered": True, "cause": "payer"}
    assert sent["agreement"] == peer.data["filing"]["request"]["agreement"]
    assert sent["transaction"] == peer.data["filing"]["request"]["transaction"]
    # The adapter derives the authority's key, a SHA-256, from the deal and the claim.
    assert re.fullmatch(r"[0-9a-f]{64}", filing.headers["idempotency-key"])
    assert outcome.status == "accepted" and outcome.filing is not None, outcome
    assert outcome.filing.case_ref in peer.cases
    assert outcome.filing.parts


def _read(peer: MediationContractFake, *, page_size: int) -> list[dict[str, Any]]:
    request = peer.data["filing"]["request"]
    return mediation.read_record(
        _peer_target(peer), negotiation_id="negotiation-fixture",
        transaction=request["transaction"], agreement=request["agreement"],
        page_size=page_size, transport=peer.transport(),
    )


def test_an_agreement_pinning_the_runs_authority_differs_in_nothing() -> None:
    peer = MediationContractFake()
    agreement = peer.data["filing"]["request"]["agreement"]

    assert mediation.pinned_authority_difference(_peer_target(peer), agreement) is None


def test_an_agreement_pinning_another_authority_is_named_with_both_identities() -> None:
    peer = MediationContractFake()
    agreement = peer.data["filing"]["request"]["agreement"]
    target = dataclasses.replace(_peer_target(peer),
                                 account="00000000-0000-4000-8000-0000000000d9")

    difference = mediation.pinned_authority_difference(target, agreement)

    assert difference is not None
    assert peer.authority["account"] in difference
    assert "00000000-0000-4000-8000-0000000000d9" in difference


def test_an_agreement_naming_no_dispute_authority_fails_rather_than_differs() -> None:
    """No dispute terms is the market's failure, never a topology's other
    authority, so it fails rather than reading as a difference to skip on."""
    peer = MediationContractFake()
    agreement = peer.data["filing"]["request"]["agreement"]
    unpinned = {**agreement, "settlement": {**agreement["settlement"], "lifecycle": None}}

    with pytest.raises(AssertionError, match="names no dispute authority"):
        mediation.pinned_authority_difference(_peer_target(peer), unpinned)


def test_the_record_is_read_whole_page_by_page_as_the_buyer(tmp_path) -> None:
    """A filed case an operator ruled and closed: three signed entries, read as
    the buyer in pages of two, verified and returned as their JSON in sequence."""
    peer = MediationContractFake()
    outcome = _file(peer, tmp_path, peer.transport())
    peer.decide(outcome.filing.case_ref, [])
    peer.requests.clear()

    entries = _read(peer, page_size=2)

    assert entries == [signed["entry"] for signed in peer.entries]
    assert [entry["kind"] for entry in entries] == ["filed", "ruled", "closed"]
    reads = [request for request in peer.requests if request.url.path == "/record"]
    assert [(request.url.params["after"], request.url.params["limit"]) for request in reads] == [
        ("0", "2"), ("2", "2"),
    ]
    assert {request.headers["authorization"] for request in reads} == {"Bearer fixture-payer"}


def test_an_entry_failing_its_signature_is_refused(tmp_path) -> None:
    peer = MediationContractFake()
    outcome = _file(peer, tmp_path, peer.transport())
    peer.decide(outcome.filing.case_ref, [])
    peer.entries[1]["entry"]["basis"] = "payee_filed"

    with pytest.raises(RecordVerificationError):
        _read(peer, page_size=1000)


def test_an_unreachable_authority_leaves_the_buyer_s_filing_unknown(tmp_path) -> None:
    peer = MediationContractFake()

    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    outcome = _file(peer, tmp_path, httpx.MockTransport(unreachable))

    assert outcome.status == "unknown", outcome
    assert peer.cases == {}


_PROXIED = {**_EXTERNAL, "SERVICE_URL": "https://dispute-authority.topology.svc.cluster.local",
            "PROXY_URL": " http://127.0.0.1:18443 ", "CA_BUNDLE_PATH": str(_LANE_CA)}


def test_a_target_named_with_a_proxy_is_probed_through_it(configure, monkeypatch) -> None:
    asked: list[tuple[str, dict[str, Any]]] = []

    def probe(url: str, **kwargs: Any) -> bool:
        asked.append((url, kwargs))
        return True

    monkeypatch.setattr(mediation, "target_ready", probe)
    configure(**_PROXIED)
    target = mediation.configured_mediation()
    assert target.proxy_url == "http://127.0.0.1:18443"
    assert target.service_url == _PROXIED["SERVICE_URL"]
    assert asked == [(_PROXIED["SERVICE_URL"],
                      {"ca_bundle": str(_LANE_CA), "proxy": "http://127.0.0.1:18443"})]


def test_the_buyer_processes_reach_a_proxied_target_through_it_and_loopback_directly(
        configure) -> None:
    configure(**_PROXIED)
    target = mediation.configured_mediation(ready=_ready)
    assert mediation.buyer_mediation_environment(target) == {
        "MEDIATION_BUYER_API_KEY": _EXTERNAL["BUYER_API_KEY"],
        "HTTPS_PROXY": "http://127.0.0.1:18443", "https_proxy": "http://127.0.0.1:18443",
        "NO_PROXY": "127.0.0.1,localhost,::1", "no_proxy": "127.0.0.1,localhost,::1",
    }
    configure(**_EXTERNAL)
    direct = mediation.configured_mediation(ready=_ready)
    assert mediation.buyer_mediation_environment(direct) == {
        "MEDIATION_BUYER_API_KEY": _EXTERNAL["BUYER_API_KEY"]}


def test_the_harness_client_goes_through_the_proxy_trusting_the_bundle_alone(configure) -> None:
    configure(**_PROXIED)
    target = mediation.configured_mediation(ready=_ready)
    transport = mediation.target_transport(target)
    assert isinstance(transport, httpx.AsyncHTTPTransport)
    pool = transport._pool  # httpx exposes no public view of a transport's proxy.
    assert type(pool).__name__ == "AsyncHTTPProxy"
    assert pool._proxy_url.host == b"127.0.0.1" and pool._proxy_url.port == 18443
    lane_ca = ssl.create_default_context(cafile=str(_LANE_CA)).get_ca_certs()
    assert pool._ssl_context.get_ca_certs() == lane_ca and lane_ca


def test_a_test_transport_or_no_proxy_leaves_the_client_its_own(configure) -> None:
    configure(**_PROXIED)
    proxied = mediation.configured_mediation(ready=_ready)
    given = httpx.MockTransport(lambda request: httpx.Response(200))
    assert mediation.target_transport(proxied, given) is given
    configure(**_EXTERNAL)
    assert mediation.target_transport(mediation.configured_mediation(ready=_ready)) is None


def test_an_unready_proxied_target_is_named_with_its_proxy(configure) -> None:
    configure(**_PROXIED)
    outcome = _outcome(ready=_unready)
    assert isinstance(outcome, Skipped)
    assert (f"blocked: mediation service at {_PROXIED['SERVICE_URL']} through "
            "http://127.0.0.1:18443 is not ready") in str(outcome)


def test_the_buyer_s_filing_and_record_reads_go_through_the_proxy(tmp_path, monkeypatch) -> None:
    """Both of the harness's mediation clients take the proxied transport; the
    fake authority then answers in its place."""
    peer = MediationContractFake()
    given: list[object] = []
    real = mediation.MediationClient

    def recording(*args: Any, transport: object = None, **kwargs: Any) -> Any:
        given.append(transport)
        return real(*args, transport=peer.transport(), **kwargs)

    monkeypatch.setattr(mediation, "MediationClient", recording)
    target = dataclasses.replace(_peer_target(peer), proxy_url="http://127.0.0.1:18443")
    request = peer.data["filing"]["request"]
    outcome = mediation.file_as_buyer(
        target, negotiation_id="negotiation-fixture", transaction=request["transaction"],
        agreement=request["agreement"], store=tmp_path, ended_at=_ENDED_AT,
    )
    peer.decide(outcome.filing.case_ref, [])
    mediation.read_record(target, negotiation_id="negotiation-fixture",
                          transaction=request["transaction"], agreement=request["agreement"])
    assert len(given) == 2
    assert all(isinstance(transport, httpx.AsyncHTTPTransport) for transport in given)
