"""Lane time across a lane's parties: the order of a set, its confirmation, the run modes.

The parties are fakes that record each call and answer as the profile's parties
do; the profile builder is held to the profile's names and kinds; a signing
client the harness builds is shown to sign at the harness's injected instant,
and a session starts on a stack left ahead through the storefront's typed
client, over a transport that verifies each request and signs each answer as
the storefront does. Every value is a public development fixture, never used
on any network.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any

import httpx
import injected_time
import pytest
from injected_time import InjectedTime, TimeFile, WallTime
from lane_double_controls import TimeView
from market_identity import (
    EMPTY_BODY,
    AuthenticatedRequest,
    Ed25519Signer,
    Identity,
    ResponseEnvelope,
    SignatureProof,
    TrustedIdentitySet,
    canonical_body_hash,
    sign_response,
    verify_request,
)
from storefront_client import SyncStorefrontClient
from storefront_client.auth import (
    IDENTITY_IDENTIFIER_HEADER,
    IDENTITY_SCHEME_HEADER,
    REQUEST_ID_HEADER,
    ROLE_HEADER,
    SIGNATURE_HEADER,
    SIGNATURE_VERSION_HEADER,
    TIMESTAMP_HEADER,
)
from storefront_client.client import ADMIN_TIME_OPERATION, ADMIN_TIME_RESOURCE

from tests.e2e.roles.buyer_cli import _time_section
from tests.e2e.roles.helpers.compute_deal_stages import reach_agreement_instant
from tests.e2e.roles.helpers.lane_time import (
    BuyerFileParty,
    ChainParty,
    ClientParty,
    LaneTime,
    LaneTimeError,
    TimeReading,
    buyer_time_file,
    lane_time_of,
    parties_from,
)

T = 1_794_821_400


class FakeParty:
    """A party holding its own time, as its status reports it."""

    def __init__(self, name: str, kind: str, calls: list[str], *, source: str | None = "injected",
                 now: int = T - 60, stuck: bool = False, refuse: bool = False) -> None:
        self.name, self.kind = name, kind
        self.calls = calls
        self.source, self.now = source, now
        # A party that answers a set but keeps its instant, as one that missed it.
        self.stuck = stuck
        self.refuse = refuse

    def set_time(self, now: int) -> None:
        self.calls.append(self.name)
        if self.refuse or now < self.now:
            raise RuntimeError(f"409 time_moves_forward: {self.name} is at {self.now}")
        if not self.stuck:
            self.now = now

    def time(self) -> TimeReading:
        return TimeReading(self.source, self.now if self.source == "injected" else None)


#: The signing skew a service and its typed client allow a timestamp.
SKEW = 300


class SignedFakeParty(FakeParty):
    """A party whose status is a signed request answered signed: a read with the
    harness more than the signing skew from the party's instant is refused, as
    the service refuses a stale request and the client a stale answer. A set is
    exempt, as the time-setting operation is."""

    def __init__(self, name: str, kind: str, calls: list[str], *, harness: InjectedTime,
                 now: int) -> None:
        super().__init__(name, kind, calls, now=now)
        self.harness = harness

    def time(self) -> TimeReading:
        if abs(self.harness.now() - self.now) > SKEW:
            raise RuntimeError(f"401 stale_timestamp: signed at {self.harness.now()}")
        return super().time()


class ChainFakeParty(FakeParty):
    """The chain, whose latest block names no source."""

    def time(self) -> TimeReading:
        return TimeReading(None, self.now)


@pytest.fixture
def restored() -> Iterator[None]:
    before = injected_time.installed()
    yield
    injected_time.install(before)


def _lane(*parties: FakeParty, start: int = T - 60) -> LaneTime:
    return LaneTime("injected", parties, harness=InjectedTime(start=start))


def test_a_set_moves_the_harness_then_services_controls_chain_and_buyer_in_order() -> None:
    calls: list[str] = []
    parties = [FakeParty("buyer-file", "buyer", calls), FakeParty("chain", "chain", calls),
               FakeParty("payments-double", "control", calls),
               FakeParty("registry-a", "registry", calls),
               FakeParty("bob-storefront", "storefront", calls),
               FakeParty("credits-service", "credits", calls),
               FakeParty("bob-provisioning", "provisioning", calls)]
    lane = _lane(*parties)
    harness_at_each_call: list[int] = []
    for party in parties:
        party.calls = _Observed(calls, lambda: harness_at_each_call.append(lane.now()))

    assert lane.set(T) == T

    assert calls == ["bob-storefront", "bob-provisioning", "registry-a", "credits-service",
                     "payments-double", "chain", "buyer-file"]
    # The harness moved first: every party was set with the harness already at T.
    assert harness_at_each_call == [T] * len(parties)


class _Observed(list):
    """A call record that runs ``observe`` as each call is appended."""

    def __init__(self, record: list[str], observe: Any) -> None:
        super().__init__()
        self.record, self.observe = record, observe

    def append(self, name: str) -> None:
        self.observe()
        self.record.append(name)


def test_a_party_left_behind_fails_naming_it_and_its_instant() -> None:
    calls: list[str] = []
    lane = _lane(FakeParty("bob-storefront", "storefront", calls),
                 FakeParty("registry-b", "registry", calls, stuck=True))

    with pytest.raises(LaneTimeError, match=rf"registry-b \(at {T - 60}\)"):
        lane.set(T)


def test_a_status_without_a_time_section_fails_naming_the_party() -> None:
    lane = _lane(FakeParty("old-storefront", "storefront", [], source=None))

    with pytest.raises(LaneTimeError, match=r"old-storefront \(its status has no time section\)"):
        lane.set(T)


def test_a_backward_set_fails_naming_the_harness_and_both_instants() -> None:
    calls: list[str] = []
    lane = _lane(FakeParty("bob-storefront", "storefront", calls), start=T)

    with pytest.raises(LaneTimeError, match=rf"the harness is at {T}, and {T - 1} is earlier"):
        lane.set(T - 1)

    assert calls == []


def test_a_party_refusing_the_set_fails_naming_it() -> None:
    lane = _lane(FakeParty("payments-double", "control", [], now=T + 5))

    with pytest.raises(LaneTimeError, match=rf"payments-double refused lane time {T}"):
        lane.set(T)


def test_the_session_start_sets_every_party_to_the_wall_instant() -> None:
    calls: list[str] = []
    party = FakeParty("bob-storefront", "storefront", calls)
    lane = _lane(party)

    lane.start(T)

    assert (calls, party.now) == (["bob-storefront"], T)


def test_a_session_on_a_stack_left_ahead_starts_at_the_latest_instant_a_party_holds() -> None:
    calls: list[str] = []
    behind = FakeParty("bob-storefront", "storefront", calls, now=T - 60)
    ahead = FakeParty("registry-a", "registry", calls, now=T + 86_400)
    lane = _lane(behind, ahead, start=T)

    lane.start(T)

    assert (behind.now, ahead.now) == (T + 86_400, T + 86_400)


def test_a_session_on_a_stack_left_past_the_signing_skew_reads_the_unsigned_parties_first() -> None:
    calls: list[str] = []
    ahead = T + 86_400
    harness = InjectedTime(start=T)
    storefront = SignedFakeParty("bob-storefront", "storefront", calls, harness=harness, now=ahead)
    provisioning = SignedFakeParty("bob-provisioning", "provisioning", calls, harness=harness,
                                   now=ahead)
    credits = SignedFakeParty("credits-service", "credits", calls, harness=harness, now=ahead)
    registry = FakeParty("registry-a", "registry", calls, now=ahead)
    chain = ChainFakeParty("anvil", "chain", calls, now=ahead)
    lane = LaneTime("injected", [storefront, provisioning, credits, registry, chain],
                    harness=harness)

    lane.start(T)

    assert harness.now() == ahead
    assert {party.now for party in (storefront, provisioning, credits, registry, chain)} == {ahead}


def test_a_signed_party_restarted_behind_the_skew_is_moved_to_the_stack_s_instant() -> None:
    calls: list[str] = []
    ahead = T + 86_400
    harness = InjectedTime(start=T)
    # Restarted alone, its source began again at the wall instant.
    storefront = SignedFakeParty("bob-storefront", "storefront", calls, harness=harness, now=T)
    chain = ChainFakeParty("anvil", "chain", calls, now=ahead)

    LaneTime("injected", [storefront, chain], harness=harness).start(T)

    assert (harness.now(), storefront.now, chain.now) == (ahead, ahead, ahead)


def test_a_signed_party_left_past_the_skew_beyond_every_unsigned_one_fails_naming_it() -> None:
    # A run that stopped partway through a set moved a service but not the chain.
    calls: list[str] = []
    harness = InjectedTime(start=T)
    storefront = SignedFakeParty("bob-storefront", "storefront", calls, harness=harness,
                                 now=T + 86_400)
    chain = ChainFakeParty("anvil", "chain", calls, now=T + 60)

    with pytest.raises(LaneTimeError, match=rf"bob-storefront refused lane time {T + 60}: "
                                            r"409 time_moves_forward"):
        LaneTime("injected", [storefront, chain], harness=harness).start(T)

    assert (calls, storefront.now) == (["bob-storefront"], T + 86_400)


_ADMIN_SEED = b"lane-time-suite-admin-seed-32byt"
_PUBLISHER = Ed25519Signer(b"lane-time-suite-store-seed-32byt")
#: The storefront routes lane time reaches, by path: the operation and resource
#: each request is signed over.
_STOREFRONT_ROUTES = {
    "/api/v1/system/status": ("admin_system_status", "system/status"),
    "/api/v1/admin/time": (ADMIN_TIME_OPERATION, ADMIN_TIME_RESOURCE),
}


class WireStorefront:
    """A storefront on injected time, as its typed client meets it on the wire.

    Each request's signature and timestamp are verified as the storefront's
    administrator verification does it, a timestamp more than the signing skew
    from the storefront's own instant refused but for the time setting's; each
    answer is signed at the storefront's instant, which the client holds to the
    skew against its own. It reserves no request id against replay, and its
    status holds only the time section.
    """

    def __init__(self, now: int) -> None:
        self.now = now
        self.stamps: list[tuple[str, int]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        operation, resource = _STOREFRONT_ROUTES[request.url.path]
        body = json.loads(request.content) if request.content else EMPTY_BODY
        principal = Identity(scheme=request.headers[IDENTITY_SCHEME_HEADER],
                             identifier=request.headers[IDENTITY_IDENTIFIER_HEADER])
        signed = AuthenticatedRequest(
            protocol=request.headers[SIGNATURE_VERSION_HEADER],
            role=request.headers[ROLE_HEADER], principal=principal, method=request.method,
            operation=operation, resource=resource,
            request_id=request.headers[REQUEST_ID_HEADER],
            timestamp=int(request.headers[TIMESTAMP_HEADER]),
            body_hash=canonical_body_hash(body),
            proof=SignatureProof(scheme=principal.scheme,
                                 value=request.headers[SIGNATURE_HEADER]))
        self.stamps.append((operation, signed.timestamp))
        result = verify_request(
            signed, body=body, now=self.now, max_skew=SKEW, expected_role="admin",
            expected_method=request.method, expected_operation=operation,
            expected_resource=resource,
            expected_principals=TrustedIdentitySet(
                identities=(Ed25519Signer(_ADMIN_SEED).identity,)),
            time_setting_operation=ADMIN_TIME_OPERATION)
        if not result.verified:
            return httpx.Response(401, json={"code": result.code.value})
        if operation == ADMIN_TIME_OPERATION:
            if body["now"] < self.now:
                return self._answer(signed, 409, {"code": "time_moves_forward"})
            self.now = body["now"]
            return self._answer(signed, 200, {"source": "injected", "now": self.now})
        return self._answer(signed, 200, {"status": "ok",
                                          "time": {"source": "injected", "now": self.now}})

    def _answer(self, signed: AuthenticatedRequest, status: int, body: dict) -> httpx.Response:
        response = sign_response(signer=_PUBLISHER, envelope=ResponseEnvelope(
            role="seller", principal=_PUBLISHER.identity, method=signed.method,
            operation=signed.operation, resource=signed.resource,
            request_id=signed.request_id, timestamp=self.now, status=status,
            body_hash=canonical_body_hash(body)))
        return httpx.Response(status, json=body, headers={
            SIGNATURE_VERSION_HEADER: response.protocol,
            IDENTITY_SCHEME_HEADER: response.principal.scheme.value,
            IDENTITY_IDENTIFIER_HEADER: response.principal.identifier,
            ROLE_HEADER: response.role,
            REQUEST_ID_HEADER: response.request_id,
            TIMESTAMP_HEADER: str(response.timestamp),
            SIGNATURE_HEADER: response.proof.value,
        })


def test_a_session_starts_through_the_storefront_s_typed_client_on_a_stack_left_past_the_skew(
        restored) -> None:
    ahead = T + 86_400
    storefront = WireStorefront(now=ahead)
    chain = ChainFakeParty("anvil", "chain", [], now=ahead)

    def parties(section: Any) -> list[Any]:
        # Built as the profile's storefront party is, over the typed client;
        # the harness's injected source is installed by then, so the client
        # signs at, and checks each answer against, the harness's instant.
        client = SyncStorefrontClient(
            "http://storefront.test", Ed25519Signer(_ADMIN_SEED), caller_role="admin",
            expected_publishers=TrustedIdentitySet(identities=(_PUBLISHER.identity,)),
            transport=httpx.MockTransport(storefront))
        return [ClientParty("bob-storefront", "storefront", client.set_time,
                            lambda: client.get_system_status().time), chain]

    lane = lane_time_of({"mode": "injected", "parties": []}, parties=parties, start=lambda: T)

    assert lane is not None and lane.now() == ahead
    assert (ADMIN_TIME_OPERATION, ahead) in storefront.stamps
    # The status reads were signed at the stack's instant, never at the wall
    # instant the session began from, and their answers were verified there.
    assert ("admin_system_status", ahead) in storefront.stamps
    assert {stamp for _, stamp in storefront.stamps} == {ahead}


def test_the_session_start_counts_the_chain_s_latest_block_and_no_wall_time_party() -> None:
    class Wall(FakeParty):
        def time(self) -> TimeReading:
            return TimeReading("wall", T + 10_000)

    calls: list[str] = []
    storefront = FakeParty("bob-storefront", "storefront", calls, now=T - 60)
    # The chain ran ahead of a held lane instant; its latest block counts.
    chain = ChainFakeParty("anvil", "chain", calls, now=T + 90)

    _lane(storefront, chain, start=T).start(T)

    assert (storefront.now, chain.now) == (T + 90, T + 90)

    other = FakeParty("bob-storefront", "storefront", [], now=T - 60)
    with pytest.raises(LaneTimeError, match=r"registry-a \(on wall time\)"):
        _lane(other, Wall("registry-a", "registry", []), start=T).start(T)
    # The wall-time party's instant was not taken for the start.
    assert other.now == T


def test_a_mix_of_sources_fails_naming_the_wall_time_party() -> None:
    lane = LaneTime("wall", [FakeParty("registry-a", "registry", [], source="wall"),
                             FakeParty("bob-storefront", "storefront", [])])

    with pytest.raises(LaneTimeError, match=r"bob-storefront \(on injected time\)"):
        lane.start(T)


def test_an_injected_run_with_a_wall_time_party_fails_naming_it() -> None:
    lane = _lane(FakeParty("registry-a", "registry", [], source="wall"),
                 FakeParty("bob-storefront", "storefront", []))

    with pytest.raises(LaneTimeError, match=r"injected time throughout, .*registry-a "
                                            r"\(on wall time\)"):
        lane.check_one_source()


def test_a_status_instant_is_read_by_the_component_s_rule() -> None:
    float_party = ClientParty("credits-service", "credits", lambda now: None,
                              lambda: {"source": "injected", "now": float(T)})
    model_party = ClientParty("payments-double", "control", lambda now: None,
                              lambda: TimeView(source="injected", now=T))

    assert model_party.time() == TimeReading("injected", T)
    assert ClientParty("old", "storefront", lambda now: None, lambda: None).time() == (
        TimeReading(None, None))
    with pytest.raises(LaneTimeError, match="credits-service cannot be read"):
        LaneTime("wall", [float_party]).check_one_source()


def test_an_agreement_instant_is_set_in_an_injected_run() -> None:
    party = FakeParty("bob-storefront", "storefront", [])
    lane = _lane(party, start=T)
    instant = datetime.fromtimestamp(T + 3, timezone.utc)

    assert reach_agreement_instant(lane, instant) == instant
    assert party.now == T + 3


def test_the_generated_buyer_configuration_names_the_lane_time_file_only_when_injected() -> None:
    assert _time_section("/tmp/arkhai-lane-time/now.json") == [
        "[time]", 'source = "injected"', 'file = "/tmp/arkhai-lane-time/now.json"', ""]
    assert _time_section(None) == []


def test_an_unreachable_party_fails_naming_it() -> None:
    class Unreachable(FakeParty):
        def time(self) -> TimeReading:
            raise httpx.ConnectError("connection refused")

    lane = LaneTime("wall", [Unreachable("registry-b", "registry", [])])

    with pytest.raises(LaneTimeError, match="registry-b cannot be read: connection refused"):
        lane.check_one_source()


def test_an_injected_run_reaches_an_instant_by_setting_it_and_never_moves_back() -> None:
    party = FakeParty("bob-storefront", "storefront", [])
    lane = _lane(party, start=T)

    assert lane.reach(T + 3_600, fixed_by_agreement=False) == T + 3_600
    assert lane.reach(T, fixed_by_agreement=True) == T + 3_600
    assert party.now == T + 3_600


def test_a_wall_run_waits_for_an_agreement_instant() -> None:
    waited: list[datetime] = []

    def wait(instant: datetime) -> datetime:
        waited.append(instant)
        return instant

    lane = LaneTime("wall", [], wait=wait)

    assert lane.reach(T, fixed_by_agreement=True) == T
    assert waited == [datetime.fromtimestamp(T, timezone.utc)]


def test_a_wall_run_needing_any_other_instant_is_a_blocked_skip_naming_its_target() -> None:
    lane = LaneTime("wall", [], wait=lambda instant: instant, target="hosted authorities")

    with pytest.raises(pytest.skip.Exception,
                       match="blocked: .* on wall time against hosted authorities"):
        lane.reach(T, fixed_by_agreement=False)


def test_a_wall_run_sets_no_time() -> None:
    with pytest.raises(LaneTimeError, match="a wall-time run sets no time"):
        LaneTime("wall", []).set(T)


def test_the_chain_is_stamped_and_mined_and_read_from_its_latest_block() -> None:
    sent: list[tuple[str, list[Any]]] = []

    def rpc(method: str, params: list[Any]) -> Any:
        sent.append((method, params))
        return {"timestamp": hex(T)} if method == "eth_getBlockByNumber" else None

    chain = ChainParty("anvil", rpc)
    chain.set_time(T)

    assert sent == [("anvil_setBlockTimestampInterval", [0]),
                    ("evm_setNextBlockTimestamp", [T]), ("evm_mine", [])]
    assert chain.time() == TimeReading(None, T)


def test_the_buyer_file_is_written_and_read_by_the_component(tmp_path) -> None:
    party = BuyerFileParty("buyer-file", TimeFile(tmp_path / "lane-time.json"))
    assert party.time() == TimeReading(None, None)

    party.set_time(T)

    assert party.time() == TimeReading(None, T)


def test_the_profile_names_every_party_by_a_known_kind_and_its_fields(tmp_path) -> None:
    file = tmp_path / "run" / "lane-time.json"
    parties = parties_from({"parties": [
        {"name": "anvil", "kind": "chain", "url": "http://anvil:8545"},
        {"name": "buyer-file", "kind": "buyer", "file": str(file)},
    ]})

    assert [(party.name, party.kind) for party in parties] == [
        ("anvil", "chain"), ("buyer-file", "buyer")]
    assert file.parent.is_dir()
    with pytest.raises(LaneTimeError, match="'clock' is of unknown kind 'sundial'"):
        parties_from({"parties": [{"name": "clock", "kind": "sundial"}]})
    with pytest.raises(LaneTimeError, match="'anvil' names no url"):
        parties_from({"parties": [{"name": "anvil", "kind": "chain"}]})


def test_a_party_field_named_by_setting_is_read_from_that_setting() -> None:
    held = {"secrets.chain_url": "http://anvil:8545"}
    read: list[str] = []

    def setting(path: str) -> Any:
        read.append(path)
        return held.get(path)

    parties = parties_from({"parties": [
        {"name": "anvil", "kind": "chain", "url_setting": "secrets.chain_url"},
    ]}, setting=setting)

    assert [(party.name, party.kind) for party in parties] == [("anvil", "chain")]
    assert read == ["secrets.chain_url"]
    with pytest.raises(LaneTimeError,
                       match="'anvil' takes its url from setting 'secrets.missing', which"):
        parties_from({"parties": [
            {"name": "anvil", "kind": "chain", "url_setting": "secrets.missing"},
        ]}, setting=setting)


def test_parties_keyed_by_name_are_read_as_a_list_of_them_is(tmp_path) -> None:
    file = tmp_path / "lane-time.json"
    section = {"mode": "injected", "parties": {
        "anvil": {"kind": "chain", "url": "http://anvil:8545"},
        "buyer-file": {"kind": "buyer", "file": str(file)},
    }}

    assert [(party.name, party.kind) for party in parties_from(section)] == [
        ("anvil", "chain"), ("buyer-file", "buyer")]
    assert buyer_time_file(section) == str(file)


def test_the_buyer_reads_the_lane_time_file_only_in_an_injected_run() -> None:
    parties = [{"name": "buyer-file", "kind": "buyer", "file": "/run/lane-time.json"}]

    assert buyer_time_file({"mode": "injected", "parties": parties}) == "/run/lane-time.json"
    assert buyer_time_file({"mode": "wall", "parties": parties}) is None
    assert buyer_time_file(None) is None


def test_a_run_naming_no_lane_parties_has_no_lane_time() -> None:
    assert lane_time_of(None) is None


def test_a_client_built_in_an_injected_run_signs_at_the_harness_s_instant(restored) -> None:
    lane = lane_time_of({"mode": "injected", "parties": []}, parties=lambda section: [],
                        start=lambda: T)
    assert lane is not None and isinstance(injected_time.installed(), InjectedTime)
    stamps: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        stamps.append(request.headers["X-Market-Timestamp"])
        return httpx.Response(503)

    signer = Ed25519Signer(_ADMIN_SEED)
    publisher = Identity(scheme="ed25519", identifier=signer.identity.identifier)
    client = SyncStorefrontClient("http://storefront.test", signer, caller_role="admin",
                                  expected_publishers=TrustedIdentitySet(identities=(publisher,)),
                                  transport=httpx.MockTransport(answer))
    with pytest.raises(Exception):
        client.get_system_status()

    assert stamps == [str(T)]


def test_a_wall_run_installs_no_injected_source(restored) -> None:
    injected_time.install(WallTime())

    lane = lane_time_of({"mode": "wall", "parties": []}, parties=lambda section: [])

    assert lane is not None and not lane.injected
    assert isinstance(injected_time.installed(), WallTime)
