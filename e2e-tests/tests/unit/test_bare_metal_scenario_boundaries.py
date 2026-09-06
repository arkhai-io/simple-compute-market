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
from pathlib import Path

import pytest
from pydantic_core import to_jsonable_python
from registry_client.models import ListingListResponse, ListingSummary

from src.ssh_access import SshProbeResult, freeze_lease_key
from tests.e2e.roles.scenarios.bare_metal import test_bare_metal_deal as scenario

# `subprocess` is one shared module object, so patching its `run` attribute
# also replaces the one ssh_access uses. Hold the real callable and delegate to
# it for anything that is not a scenario-owned command.
_REAL_RUN = _subprocess.run

MACHINE_ID = "demo-node"
PHYSICAL_HOST_ID = "demo-host"


class _Run:
    def __init__(self, payload):
        self._payload = payload
        self.returncode = 0
        self.run_id = "run-1"

    def stdout(self) -> str:
        return json.dumps(to_jsonable_python(self._payload))

    def read_events(self):
        return []


class _World:
    """Offline market state the scenario's own calls move through."""

    def __init__(self):
        self.leased = False
        self.listing_open = True          # published before the purchase
        self.events: list[str] = []
        self.ssh_calls: list[dict] = []
        self.classified: list[str] = []

    # --- buyer CLI seam -------------------------------------------------
    def run(self, args, **kwargs):
        args = list(args)
        self.events.append(" ".join(args[:3]))
        if args[:2] == ["bare-metal", "buy"]:
            self.leased = True
            return _Run({})
        if args[:2] == ["bare-metal", "result"]:
            return _Run({"machine_id": MACHINE_ID,
                         "physical_host_id": PHYSICAL_HOST_ID})
        if args[:2] == ["bare-metal", "access"]:
            return _Run({"host": "10.0.0.9", "port": 22,
                         "username": "arkhai-0123456789abcdef"})
        if args[:3] == ["bare-metal", "teardown", "request"]:
            self.leased = False
            return _Run({"status": "requested"})
        if args[:3] == ["bare-metal", "teardown", "status"]:
            return _Run({"status": "released"})
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
    w = _World()
    key = tmp_path / "lease"
    _subprocess.run(["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(key), "-q"],
                    check=True, capture_output=True)
    pub = (tmp_path / "lease.pub").read_text().strip()
    material = freeze_lease_key(key)

    settings = {
        "BUY_ARGS": f"--duration 3600 --ssh-public-key-file {tmp_path / 'lease.pub'}",
        "TERMINAL_TEARDOWN_STATUS": "released",
        "POLL_INTERVAL_SECONDS": 0,
    }
    monkeypatch.setattr(scenario, "_setting",
                        lambda name, default="": settings.get(name, default))
    monkeypatch.setattr(scenario, "assert_market_run_succeeded",
                        lambda run, command: None)
    monkeypatch.setattr(scenario, "ordered_event_groups", lambda *a, **k: None)
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
            return SshProbeResult(returncode=0,
                                  stdout=scenario._ACCESS_PROOF_OUTPUT, stderr="")
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
        world, world.key, ["management-probe"], ["publish"], tmp_path)


def test_the_scenario_completes_against_offline_dependencies(world, tmp_path):
    _drive(world, tmp_path)

    assert world.ssh_calls, "the scenario never attempted buyer SSH"


def test_publication_reconciles_while_leased_then_again_after_release(world, tmp_path):
    _drive(world, tmp_path)

    publishes = [i for i, e in enumerate(world.events) if e == "publish"]
    listings = [i for i, e in enumerate(world.events) if e.startswith("bare-metal list")]
    teardown = world.events.index("bare-metal teardown request")

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

    assert "bare-metal teardown request" in world.events
