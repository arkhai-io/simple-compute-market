"""Drive the whole-host scenario offline against controlled dependencies.

This executes the real `test_bare_metal_complete_deal` function. Only the
process-touching seams are substituted: the buyer CLI, `_buyer_ssh`,
`subprocess.run` (publication and the management probe) and `_setting`. The
real `classify_ssh_probe`, `freeze_lease_key`, `assert_lease_key_unchanged`,
`resolve_host_key_trust`, `_purchasable_offers` and `_run_publication` run
unmodified, so a caller that drops a required argument or reorders the
publication rounds fails here.

Every output below is a deterministic offline fixture. **Nothing here is
evidence of a real end-to-end run**: no process is spawned, no SSH is
attempted, and no network or cluster is contacted.
"""

from __future__ import annotations

import json
import subprocess as _subprocess
import uuid
from pathlib import Path

import pytest
from pydantic_core import to_jsonable_python
from registry_client.models import ListingListResponse, ListingSummary

from core_buyer.run_log import RunLog
from market_identity import Identity, IdentityScheme

from arkhai_bare_metal import BareMetalAccessResult, BareMetalReceipt
from arkhai_bare_metal_storefront.models import (
    BareMetalAccessDeliveryResponse,
    BareMetalFulfillmentResponse,
    BareMetalFulfillmentResultResponse,
)

from src.ssh_access import SshProbeResult, freeze_lease_key
from tests.e2e.roles.scenarios.bare_metal import test_bare_metal_deal as scenario

# `subprocess` is one shared module object, so patching its `run` attribute
# also replaces the one ssh_access uses. Hold the real callable and delegate to
# it for anything that is not a scenario-owned command.
_REAL_RUN = _subprocess.run

MACHINE_ID = "demo-node"
PHYSICAL_HOST_ID = "demo-host"

NEGOTIATION_ID = "neg-1"
SITE_ID = "demo-site"
ESCROW_UID = "0x" + "ab" * 32
LEASE_USERNAME = "arkhai-0123456789abcdef"


def _fulfillment(state: str) -> dict:
    """The storefront's own fulfillment projection, from its response model."""
    return BareMetalFulfillmentResponse(
        negotiation_id=NEGOTIATION_ID,
        escrow_uid=ESCROW_UID,
        site_id=SITE_ID,
        state=state,
    ).model_dump(mode="json")


def _result_response() -> dict:
    """The real `bare-metal result` envelope, not a flattened stand-in.

    Built from the response models the storefront returns, so the scenario is
    read against the shape it will actually receive: identity fields live under
    `receipt`, beside the executor's own `result`.
    """
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
            ssh_user=LEASE_USERNAME,
            escrow_uid=ESCROW_UID,
        ),
    ).model_dump(mode="json")


def _access_response() -> dict:
    return BareMetalAccessDeliveryResponse(
        negotiation_id=NEGOTIATION_ID,
        host="10.0.0.9",
        port=22,
        username=LEASE_USERNAME,
    ).model_dump(mode="json")


# What an ordinary lease account's session reports back.
UNPRIVILEGED_PROOF = (
    "arkhai-uid=1001\n"
    "arkhai-groups=arkhai-0123456789abcdef\n"
    "arkhai-sudo=refused\n"
)


BUYER_PRINCIPAL = Identity(
    scheme=IdentityScheme.ED25519,
    identifier="A6EHv_POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg",
)
SELLER_PRINCIPAL = Identity(
    scheme=IdentityScheme.ED25519,
    identifier="9DeYjBqI4KyBmpJnKUZvA1XvKWQ3lqLQ0m2CGxpEYQE",
)
REGISTRY_URL = "https://registry.example"
REGISTRY_AUTHORITY = "registry-demo"
LISTING_ID = "listing-1"
STOREFRONT_URL = "https://seller.example"


class _RunLogWriter:
    """Emit the events `buy` and `fund` really write, using the real RunLog.

    The scenario reads a run log the buyer produced, so the fixture produces one
    the same way instead of listing event names by hand. An event this buyer
    does not emit therefore cannot be asserted here either.
    """

    def __init__(self, state_dir: Path):
        self._log = RunLog.start(
            profile_id=uuid.uuid4(),
            principal=BUYER_PRINCIPAL,
            domain="bare_metal",
            listing_id=LISTING_ID,
            option_id="option-1",
            duration_seconds=900,
            seller_url=STOREFRONT_URL,
            storefront_url=STOREFRONT_URL,
            publisher_id="publisher-1",
            publisher_principals={
                "identities": [SELLER_PRINCIPAL.model_dump(mode="json")]
            },
            source_registry_url=REGISTRY_URL,
            source_registry_authority=REGISTRY_AUTHORITY,
        )

    def negotiated(self) -> None:
        self._log.event(
            "agreement_accepted",
            negotiation_id=NEGOTIATION_ID,
            agreement_ref=NEGOTIATION_ID,
            obligation_ref="obligation-1",
            storefront_url=STOREFRONT_URL,
        )
        self._log.end("agreed", negotiation_id=NEGOTIATION_ID, agreed_amount=250)

    def funded(self) -> None:
        self._log.event("escrow_created", escrow_uid=ESCROW_UID)
        self._log.event("settlement_verified", escrow_uid=ESCROW_UID)
        self._log.event("fulfillment_begun", escrow_uid=ESCROW_UID)

    def events(self) -> list[dict]:
        return [
            json.loads(line)
            for line in self._log.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


class _Run:
    def __init__(self, payload, events=None):
        self._payload = payload
        self.returncode = 0
        self.run_id = "run-1"
        self._events = events

    def stdout(self) -> str:
        return json.dumps(to_jsonable_python(self._payload))

    def read_events(self):
        # Re-read, not a snapshot: the scenario reads this run's events again
        # after the settlement command and must see what settlement appended.
        return self._events() if self._events is not None else []


class _World:
    """Offline market state the scenario's own calls move through."""

    def __init__(self, run_log: _RunLogWriter):
        self.run_log = run_log
        self.leased = False
        self.listing_open = True          # published before the purchase
        self.events: list[str] = []
        self.ssh_calls: list[dict] = []
        self.classified: list[str] = []
        self.access_proof = UNPRIVILEGED_PROOF
        self.state = "pending"
        self.next_state = {"provisioning": "active", "releasing": "released"}

    # --- buyer CLI seam -------------------------------------------------
    def run(self, args, **kwargs):
        args = list(args)
        self.events.append(" ".join(args[:3]))
        if args[:2] == ["bare-metal", "buy"]:
            # Negotiation only. Nothing is leased until settlement funds it.
            self.run_log.negotiated()
            return _Run({}, events=self.run_log.events)
        if args[:2] == ["bare-metal", "fund"]:
            self.leased = True
            # `fund` returns once fulfillment has begun; the host is not yet
            # usable, which is why the scenario has to wait for `active`.
            self.state = "provisioning"
            self.run_log.funded()
            return _Run(
                {
                    "escrow_uid": ESCROW_UID,
                    "settlement": {"obligation_ref": "o"},
                    "fulfillment": _fulfillment("reserved"),
                }
            )
        if args[:2] == ["bare-metal", "result"]:
            if self.state != "active":
                raise AssertionError(
                    "the delivery view was read before the lease was active"
                )
            return _Run(_result_response())
        if args[:2] == ["bare-metal", "access"]:
            if self.state != "active":
                raise AssertionError(
                    "access coordinates were read before the lease was active"
                )
            return _Run(_access_response())
        if args[:2] == ["bare-metal", "teardown"]:
            self.leased = False
            self.state = "releasing"
            return _Run(_fulfillment("releasing"))
        if args[:2] == ["bare-metal", "status"]:
            # One intermediate observation per transition, so a scenario that
            # read the first answer as terminal would fail here.
            projection = _Run({"fulfillment": _fulfillment(self.state)})
            self.state = self.next_state.get(self.state, self.state)
            return projection
        if args[:2] == ["bare-metal", "list"]:
            listings = []
            if self.listing_open:
                listings.append(ListingSummary(
                    id="listing-1", status="open",
                    storefront_url="https://seller.example/",
                    offer={"machine_id": MACHINE_ID,
                           "physical_host_id": PHYSICAL_HOST_ID},
                    settlement_options=[{"mechanism": "alkahest"}],
                ))
            return _Run(ListingListResponse(listings=listings, total=len(listings)))
        raise AssertionError(f"unexpected buyer command: {args}")

    @property
    def run_id(self) -> str:
        return "run-1"

    # --- publication and management seam --------------------------------
    def subprocess_run(self, argv, **kwargs):
        if list(argv) == ["publish"]:
            self.events.append("publish")
            # The storefront closes a listing whose capacity is unavailable.
            self.listing_open = not self.leased
        elif list(argv) == ["management-probe"]:
            self.events.append("management-probe")
        else:
            return _REAL_RUN(argv, **kwargs)
        return _subprocess.CompletedProcess(args=argv, returncode=0,
                                            stdout="", stderr="")


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    w = _World(_RunLogWriter(tmp_path / "state"))
    key = tmp_path / "lease"
    _subprocess.run(["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(key), "-q"],
                    check=True, capture_output=True)
    pub = (tmp_path / "lease.pub").read_text().strip()
    material = freeze_lease_key(key)

    settings = {
        "BUY_ARGS": f"--duration 3600 --ssh-public-key-file {tmp_path / 'lease.pub'}",
        "REGISTRY_URL": REGISTRY_URL,
        "REGISTRY_AUTHORITY": REGISTRY_AUTHORITY,
        "TERMINAL_TEARDOWN_STATE": "released",
        "ACTIVE_FULFILLMENT_STATE": "active",
        "POLL_INTERVAL_SECONDS": 0,
        "PROVISIONING_TIMEOUT_SECONDS": 5,
        "TEARDOWN_TIMEOUT_SECONDS": 5,
    }
    monkeypatch.setattr(scenario, "_setting",
                        lambda name, default="": settings.get(name, default))
    monkeypatch.setattr(scenario, "assert_market_run_succeeded",
                        lambda run, command: None)
    monkeypatch.setattr(scenario.subprocess, "run", w.subprocess_run)

    def fake_buyer_ssh(access, *, private_key_file, known_hosts_file,
                       strict_host_key_checking, command=scenario._ACCESS_PROOF_COMMAND):
        w.ssh_calls.append({
            "private_key_file": str(private_key_file),
            "strict_host_key_checking": strict_host_key_checking,
            "known_hosts_file": str(known_hosts_file),
        })
        Path(known_hosts_file).write_text("10.0.0.9 ssh-ed25519 AAAAC3Nz\n")
        if len(w.ssh_calls) == 1:
            return SshProbeResult(returncode=0, stdout=w.access_proof, stderr="")
        # Offered line carries the frozen fingerprint, so the real classifier
        # only returns KEY_REJECTED when the scenario passes that exact value.
        return SshProbeResult(
            returncode=255, stdout="",
            stderr=(f"debug1: Offering public key: k ED25519 {material.fingerprint}\r\n"
                    "buyer@host: Permission denied (publickey)."))

    monkeypatch.setattr(scenario, "_buyer_ssh", fake_buyer_ssh)
    w.key = key
    w.public_key = pub
    w.material = material
    return w


def _drive(world, tmp_path):
    scenario.test_bare_metal_complete_deal(
        ["bare-metal", "fund"],
        world, world.key, ["management-probe"], ["publish"], tmp_path)


def test_the_scenario_completes_against_offline_dependencies(world, tmp_path):
    _drive(world, tmp_path)

    assert world.ssh_calls, "the scenario never attempted buyer SSH"


def test_publication_reconciles_while_leased_then_again_after_release(world, tmp_path):
    _drive(world, tmp_path)

    publishes = [i for i, e in enumerate(world.events) if e == "publish"]
    listings = [i for i, e in enumerate(world.events) if e.startswith("bare-metal list")]
    teardown = next(i for i, e in enumerate(world.events)
                    if e.startswith("bare-metal teardown"))

    assert len(publishes) == 2, world.events
    # while leased: publish, then observe the listing gone, all before teardown
    assert publishes[0] < listings[0] < teardown
    # after release: publish again, then observe it back
    assert teardown < publishes[1] < listings[-1]


def test_the_frozen_fingerprint_and_pinning_rule_reach_the_ssh_calls(world, tmp_path):
    _drive(world, tmp_path)

    assert [c["private_key_file"] for c in world.ssh_calls] == [str(world.key)] * 2
    # First contact may pin; the probe after teardown verifies and never re-pins.
    assert world.ssh_calls[0]["strict_host_key_checking"] == "accept-new"
    assert world.ssh_calls[1]["strict_host_key_checking"] == "yes"
    assert world.ssh_calls[0]["known_hosts_file"] == world.ssh_calls[1]["known_hosts_file"]


def test_a_stale_open_listing_while_leased_fails_the_scenario(world, tmp_path,
                                                              monkeypatch):
    """If publication does not close it, occupancy is false and the run fails."""
    # A publication round that does not close the stale listing.
    def publish_without_reconciling(argv, **kwargs):
        if list(argv) in (["publish"], ["management-probe"]):
            world.events.append("publish" if argv[0] == "publish" else "management-probe")
            return _subprocess.CompletedProcess(args=argv, returncode=0,
                                                stdout="", stderr="")
        return _REAL_RUN(argv, **kwargs)

    monkeypatch.setattr(scenario.subprocess, "run", publish_without_reconciling)

    with pytest.raises(AssertionError, match="still publicly purchasable"):
        _drive(world, tmp_path)


def test_teardown_is_requested_when_the_run_fails_after_purchase(world, tmp_path,
                                                                 monkeypatch):
    monkeypatch.setattr(scenario, "_purchasable_offers",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        _drive(world, tmp_path)

    assert any(e.startswith("bare-metal teardown") for e in world.events), world.events


def test_the_settlement_command_runs_before_delivery_is_claimed(world, tmp_path):
    """A negotiated agreement is not a purchase.

    `buy` only negotiates. If the lane went straight from `buy` to `result` it
    would assert delivery of a lease nothing had funded, and the host would
    never have been reserved.
    """
    _drive(world, tmp_path)

    funded = [i for i, e in enumerate(world.events) if e.startswith("bare-metal fund")]
    delivered = [i for i, e in enumerate(world.events) if e.startswith("bare-metal result")]

    assert funded, world.events
    assert funded[0] < delivered[0], "settlement must precede the delivery view"


def test_a_lane_whose_settlement_command_does_nothing_fails(world, tmp_path):
    """The settlement step has to have an effect, not merely be invoked."""
    original = world.run

    def run(args, **kwargs):
        if list(args)[:2] == ["bare-metal", "fund"]:
            world.events.append("bare-metal fund (inert)")
            return _Run({})
        return original(args, **kwargs)

    world.run = run

    with pytest.raises(AssertionError):
        _drive(world, tmp_path)


# ---------------------------------------------------------------------------
# The buyer session's own privilege level
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("proof", "reason"),
    [
        ("arkhai-uid=0\narkhai-groups=root\narkhai-sudo=refused\n", "root"),
        (
            "arkhai-uid=1001\narkhai-groups=arkhai sudo\narkhai-sudo=refused\n",
            "a privileged supplementary group",
        ),
        (
            "arkhai-uid=1001\narkhai-groups=arkhai\narkhai-sudo=granted\n",
            "a sudo grant",
        ),
        ("arkhai-bare-metal-access-ok", "a bare success marker"),
        ("arkhai-uid=1001\narkhai-groups=arkhai\n", "no sudo answer at all"),
    ],
)
def test_a_privileged_or_unreadable_buyer_session_fails(world, tmp_path, proof, reason):
    """SSH succeeding is not the claim; an unprivileged buyer is.

    The last two cases are the ones a printf marker would have passed: a session
    that never reported its privilege level has not shown it lacks one.
    """
    world.access_proof = proof

    with pytest.raises(AssertionError):
        _drive(world, tmp_path)


def test_the_privilege_proof_is_judged_before_teardown(world, tmp_path):
    """A released account cannot be inspected, so the order is the evidence."""
    world.access_proof = "arkhai-uid=0\narkhai-groups=root\narkhai-sudo=granted\n"

    with pytest.raises(AssertionError):
        _drive(world, tmp_path)

    # The `finally` still releases the host. What must not have happened is the
    # scenario continuing past the proof into the release wait.
    teardown = [
        i for i, e in enumerate(world.events) if e.startswith("bare-metal teardown")
    ]
    polls = [
        i for i, e in enumerate(world.events) if e.startswith("bare-metal status")
    ]
    assert teardown, world.events
    assert not [i for i in polls if i > teardown[0]], world.events


def test_an_ordinary_lease_session_passes(world, tmp_path):
    """The negative cases above must not be passing for an unrelated reason."""
    _drive(world, tmp_path)

    assert scenario._parse_access_proof(UNPRIVILEGED_PROOF).uid == 1001


def test_a_lease_that_never_becomes_active_fails_rather_than_delivering(
    world, tmp_path, monkeypatch
):
    world.next_state = {}          # provisioning never advances

    with pytest.raises(AssertionError, match="did not reach 'active'"):
        _drive(world, tmp_path)


def test_a_failed_fulfillment_is_reported_as_itself(world, tmp_path):
    """A terminal failure must not be waited out into a timeout."""
    world.next_state = {"provisioning": "failed"}

    with pytest.raises(AssertionError, match="ended in state 'failed'"):
        _drive(world, tmp_path)


def test_a_teardown_that_does_not_release_fails(world, tmp_path):
    world.next_state = {"provisioning": "active", "releasing": "teardown_failed"}

    with pytest.raises(AssertionError, match="ended in state 'teardown_failed'"):
        _drive(world, tmp_path)


# ---------------------------------------------------------------------------
# The run-log events this buyer actually writes
# ---------------------------------------------------------------------------


def test_the_asserted_events_are_the_ones_this_buyer_emits(world, tmp_path):
    """`buy` writes run_started, agreement_accepted, run_ended — and no more.

    The events are produced here by the same `RunLog` the command uses, so an
    assertion on a name nothing emits fails in this suite.
    """
    _drive(world, tmp_path)

    names = [event["event"] for event in world.run_log.events()]

    assert names[:2] == ["run_started", "agreement_accepted"]
    assert "run_ended" in names
    assert not {"discover", "negotiation_completed"}.intersection(names), (
        "these were asserted by the scenario and are emitted by nothing"
    )
    assert names[-3:] == [
        "escrow_created",
        "settlement_verified",
        "fulfillment_begun",
    ]


def test_discovery_is_bound_to_the_configured_registry(world, tmp_path):
    started = world.run_log.events()[0]

    scenario._assert_discovered_from_the_trusted_registry(started)

    for field, value in (
        ("source_registry_url", "https://other-registry.example"),
        ("source_registry_authority", "another-authority"),
        ("listing_id", ""),
        ("publisher_principals", {"identities": []}),
    ):
        with pytest.raises(AssertionError):
            scenario._assert_discovered_from_the_trusted_registry(
                {**started, field: value}
            )
