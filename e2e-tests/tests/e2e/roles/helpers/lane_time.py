"""Lane time: one time, set by the scenario, that every party in a lane perceives.

A run is injected or wall time throughout, as its profile's ``lane_time`` section
says (``mode``), and that section names the parties the run reaches, a list or a
mapping keyed by name: in a Compose lane every party it runs — each service with
its typed client and administrator credential, both lane doubles and the sample
app with their control tokens, the chain, and the buyer's lane-time file; in the
local Helm release's validation its storefront, provisioning service and
registry. A party the profile names but the run cannot reach fails the setup by
name; nothing is skipped.

In an injected run the harness installs an injected source in its own process,
so its signing clients sign at lane time, and ``LaneTime.set(T)`` moves, in
order, the harness's own source, each service through its typed client, the
doubles and the sample app through their control, the chain (its next block
stamped at T and mined), and the buyer's file; it then reads every party's
status and fails naming any that does not report T, a status with no time
section among them. Lane time only moves forward and is never reset: a set
earlier than the harness's instant fails naming the harness and both instants,
and a party refusing a set fails naming that party. A party's field written
``<field>_setting`` is read from the setting it names, so a profile without
secrets, such as a Helm release's, leaves each credential in the secrets
profile that already holds it. At the session's start
every party is set to the wall instant of that moment, or to the latest instant
a party already holds when a run before this one on the same stack left lane
time ahead. The chain is frozen between sets.

In a wall run nothing is set: a stage reaches an instant the Agreement fixes by
waiting for it, and any other instant is a blocked skip naming the wall-time
target. Either way the session reads the status of every party the profile
names and fails naming a mix of sources. A run whose profile has no
``lane_time`` section, a hosted target's, has no lane time and reads no status,
and a stage there waits for an Agreement instant as a wall run does
(``compute_deal_stages.reach_agreement_instant``).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, Protocol

import httpx
import injected_time
import pytest
from arkhai_apicredits.settlement.credits_client import CreditsServiceClient
from compute_provisioning_client.client import SyncComputeProvisioningClient
from injected_time import InjectedTime, TimeFile, check_instant
from lane_double_controls import ControlClient
from market_identity import Identity, TrustedIdentitySet, create_signer
from registry_client.client import SyncRegistryClient
from storefront_client import SyncStorefrontClient

from e2e_harness.settings import settings

Mode = Literal["injected", "wall"]
MODES: tuple[Mode, ...] = ("injected", "wall")

#: The order a set moves the parties in, by kind: the services first, so a
#: double's due state never runs ahead of the service that acts on it, then the
#: doubles and the sample app, then the chain, then the buyer's file.
SET_ORDER: tuple[str, ...] = (
    "storefront", "provisioning", "registry", "credits", "control", "chain", "buyer",
)
#: Kinds whose status names no time source: the chain reports its latest
#: block's stamp, and the buyer's file holds only an instant.
_SOURCELESS = frozenset({"chain", "buyer"})


#: The longest wait `wait_until` accepts, so a mistaken instant fails the stage
#: rather than hanging the lane.
MAX_CLOCK_WAIT = timedelta(minutes=2)


class LaneTimeError(AssertionError):
    """A lane-time set or check that failed, naming the party."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def wait_until(instant: datetime, *, now: Callable[[], datetime] = _utc_now,
               sleep: Callable[[float], Any] = time.sleep) -> datetime:
    """Wait for the wall clock to reach ``instant``, and return the time it did.

    A wall-time run's one wait that is not on a request a stage made, and only
    for an instant the deal's Agreement fixes: nothing moves a wall-time
    party's clock, so a deal that must be late, or must reach its start, waits
    for the instant itself, and the stage then advances whatever acts on it
    explicitly. It never waits for a loop to have run.
    """
    remaining = instant - now()
    assert remaining <= MAX_CLOCK_WAIT, (
        f"refusing to wait {remaining} for {instant.isoformat()}; the bound is "
        f"{MAX_CLOCK_WAIT}"
    )
    # A sleep may return slightly before the wall clock reaches the instant,
    # so it is repeated for whatever remains.
    while remaining > timedelta(0):
        sleep(remaining.total_seconds())
        remaining = instant - now()
    return now()


@dataclass(frozen=True)
class TimeReading:
    """What a party's status says of its time.

    ``source`` is ``"injected"`` or ``"wall"``, or None for a status with no
    time section, as an image that predates the setting serves; ``now`` is the
    instant an injected party holds.
    """

    source: str | None
    now: int | None


class TimeParty(Protocol):
    """One party of a lane, as lane time reaches it."""

    name: str
    kind: str

    def set_time(self, now: int) -> None:
        """Set the party's time to ``now``; raise on a refusal."""
        ...

    def time(self) -> TimeReading:
        """The party's time as its status reports it."""
        ...


def _ordered(parties: Iterable[TimeParty]) -> list[TimeParty]:
    return sorted(parties, key=lambda party: SET_ORDER.index(party.kind))


class LaneTime:
    """The run's time across its parties: set together in an injected run, read in either."""

    def __init__(self, mode: Mode, parties: Sequence[TimeParty], *,
                 harness: InjectedTime | None = None,
                 wait: Callable[[datetime], datetime] | None = None,
                 target: str = "") -> None:
        if mode not in MODES:
            raise LaneTimeError(f"lane_time.mode is 'injected' or 'wall', not {mode!r}")
        if (mode == "injected") != (harness is not None):
            raise LaneTimeError("an injected run's harness holds an injected source; a wall run's none")
        unknown = sorted({party.kind for party in parties} - set(SET_ORDER))
        if unknown:
            raise LaneTimeError(f"lane_time names parties of unknown kinds: {', '.join(unknown)}")
        self.mode = mode
        self.parties = _ordered(parties)
        self.harness = harness
        self._wait = wait
        self._target = target

    @property
    def injected(self) -> bool:
        return self.mode == "injected"

    def now(self) -> int:
        """The lane instant: the harness's injected one, or the process's wall time."""
        return self.harness.now() if self.harness is not None else injected_time.now()

    def set(self, instant: int) -> int:
        """Move every party to ``instant``, in order, and confirm each reports it."""
        if self.harness is None:
            raise LaneTimeError(
                f"a wall-time run sets no time; {instant} is reached by waiting, if at all")
        current = self.harness.now()
        if instant < current:
            raise LaneTimeError(
                f"lane time moves only forward: the harness is at {current}, "
                f"and {instant} is earlier")
        self.harness.set(instant)
        for party in self.parties:
            try:
                party.set_time(instant)
            except Exception as error:
                raise LaneTimeError(
                    f"{party.name} refused lane time {instant}: {error}") from error
        self.confirm(instant)
        return instant

    def confirm(self, instant: int) -> None:
        """Fail naming every party that does not report ``instant``."""
        astray = []
        for party in self.parties:
            reading = self._read(party)
            if party.kind not in _SOURCELESS and reading.source is None:
                astray.append(f"{party.name} (its status has no time section)")
            elif party.kind not in _SOURCELESS and reading.source != "injected":
                astray.append(f"{party.name} (on {reading.source} time)")
            elif reading.now != instant:
                astray.append(f"{party.name} (at {reading.now})")
        if astray:
            raise LaneTimeError(
                f"lane time is {instant}, but not every party reports it: " + "; ".join(astray))

    def check_one_source(self) -> None:
        """Fail naming every party whose source is not the run's."""
        astray = []
        for party in self.parties:
            if party.kind in _SOURCELESS:
                continue
            reading = self._read(party)
            if reading.source is None:
                astray.append(f"{party.name} (its status has no time section)")
            elif reading.source != self.mode:
                astray.append(f"{party.name} (on {reading.source} time)")
        if astray:
            raise LaneTimeError(
                f"the run is on {self.mode} time throughout, but not every party is: "
                + "; ".join(astray))

    def start(self, wall_now: int) -> None:
        """The session's start: an injected run sets every party to ``wall_now``,
        or to the latest instant a party already holds — a run before this one on
        the same stack left lane time ahead of the wall clock, or the chain ran
        ahead of it — so the start never sets a party back."""
        if self.injected:
            held = [reading.now for party in self.parties
                    for reading in (self._read(party),)
                    if reading.now is not None
                    and (party.kind in _SOURCELESS or reading.source == "injected")]
            self.set(max([wall_now, *held]))
        self.check_one_source()

    def reach(self, instant: int, *, fixed_by_agreement: bool) -> int:
        """Bring the lane to ``instant``, or past it; the lane instant after.

        An injected run sets lane time, leaving it where it is when it is already
        past ``instant``. A wall run waits for an instant the Agreement fixes,
        and is a blocked skip for any other, since a wall-time target offers no
        way to reach it.
        """
        if self.injected:
            return self.set(max(instant, self.now()))
        if not fixed_by_agreement:
            pytest.skip(
                f"blocked: reaching {instant} needs lane time, and the run is on wall time"
                + (f" against {self._target}" if self._target else ""))
        if self._wait is None:
            raise LaneTimeError("a wall-time run waits through a wait function, and has none")
        return int(self._wait(datetime.fromtimestamp(instant, timezone.utc)).timestamp())

    @staticmethod
    def _read(party: TimeParty) -> TimeReading:
        try:
            return party.time()
        except LaneTimeError:
            raise
        except Exception as error:
            raise LaneTimeError(f"{party.name} cannot be read: {error}") from error


# ---------------------------------------------------------------------------
# The parties, over the typed clients and controls a lane reaches them by
# ---------------------------------------------------------------------------


def _reading(section: Any) -> TimeReading:
    """A status's time section, a model or a mapping, as a reading.

    The instant is read by the time component's one rule, so a float or a
    string never passes for the instant set.
    """
    if section is None:
        return TimeReading(None, None)
    if hasattr(section, "model_dump"):
        section = section.model_dump(mode="json")
    if not isinstance(section, Mapping):
        return TimeReading(None, None)
    now = section.get("now")
    return TimeReading(section.get("source"), None if now is None else check_instant(now))


@dataclass
class ClientParty:
    """A party reached through callables over its typed client."""

    name: str
    kind: str
    setter: Callable[[int], Any]
    reader: Callable[[], Any]

    def set_time(self, now: int) -> None:
        self.setter(now)

    def time(self) -> TimeReading:
        return _reading(self.reader())


@dataclass
class ChainParty:
    """The lane's dev chain: its block time frozen, its next block stamped at the
    instant, then mined.

    Left to itself the chain stamps each block with the wall clock, running ahead
    of a held lane instant by the real time since the last set, and refuses a
    later set that falls behind its latest block. With the interval between
    block stamps set to zero, every block after a set carries the set instant
    until the next set.
    """

    name: str
    rpc: Callable[[str, list[Any]], Any]
    kind: str = "chain"

    def set_time(self, now: int) -> None:
        self.rpc("anvil_setBlockTimestampInterval", [0])
        self.rpc("evm_setNextBlockTimestamp", [now])
        self.rpc("evm_mine", [])

    def time(self) -> TimeReading:
        block = self.rpc("eth_getBlockByNumber", ["latest", False])
        stamp = block["timestamp"]
        return TimeReading(None, int(stamp, 16) if isinstance(stamp, str) else int(stamp))


@dataclass
class BuyerFileParty:
    """The buyer's lane-time file, which every `market` command reads."""

    name: str
    file: TimeFile
    kind: str = "buyer"

    def set_time(self, now: int) -> None:
        self.file.write(now)

    def time(self) -> TimeReading:
        # The harness writes the file at the session's first set; before it, a
        # fresh run has none, which holds no instant rather than failing.
        if not self.file.path.exists():
            return TimeReading(None, None)
        return TimeReading(None, self.file.now())


def lane_time_settings(settings: Any) -> Mapping[str, Any] | None:
    """The profile's ``lane_time`` section as plain data, or None when it has none."""
    section = settings.get("lane_time")
    if not section:
        return None
    return section.to_dict() if hasattr(section, "to_dict") else dict(section)


def _required(entry: Mapping[str, Any], key: str) -> Any:
    value = entry.get(key)
    if value in (None, ""):
        raise LaneTimeError(f"lane_time party {entry.get('name', '?')!r} names no {key}")
    return value


def _signer(entry: Mapping[str, Any], prefix: str) -> Any:
    return create_signer(_required(entry, f"{prefix}_scheme"),
                         str(_required(entry, f"{prefix}_credential")))


def _pinned(entry: Mapping[str, Any], prefix: str) -> TrustedIdentitySet:
    return TrustedIdentitySet(identities=(Identity(
        scheme=_required(entry, f"{prefix}_scheme"),
        identifier=str(_required(entry, f"{prefix}_identifier"))),))


def _storefront(entry: Mapping[str, Any]) -> TimeParty:
    client = SyncStorefrontClient(_required(entry, "url"), _signer(entry, "admin"),
                                  caller_role="admin",
                                  expected_publishers=_pinned(entry, "publisher"))
    return ClientParty(entry["name"], "storefront", client.set_time,
                       lambda: client.get_system_status().time)


def _provisioning(entry: Mapping[str, Any]) -> TimeParty:
    client = SyncComputeProvisioningClient(_required(entry, "url"), _signer(entry, "admin"),
                                           "admin", _pinned(entry, "authority"))
    return ClientParty(entry["name"], "provisioning", client.set_time,
                       lambda: client.get_system_status().time)


def _registry(entry: Mapping[str, Any]) -> TimeParty:
    key = str(_required(entry, "admin_key"))
    client = SyncRegistryClient(_required(entry, "url"), signer=_signer(entry, "caller"),
                                caller_role="buyer",
                                expected_registries=_pinned(entry, "authority"),
                                registry_authority=_required(entry, "authority_id"))
    return ClientParty(entry["name"], "registry",
                       lambda now: client.set_time(now, admin_key=key),
                       lambda: client.get_admin_status(admin_key=key).time)


def _credits(entry: Mapping[str, Any]) -> TimeParty:
    client = CreditsServiceClient(_required(entry, "url"), signer=_signer(entry, "admin"),
                                  expected_authorities=_pinned(entry, "authority"),
                                  caller_role="admin")
    return ClientParty(entry["name"], "credits",
                       lambda now: asyncio.run(client.set_time(now)),
                       lambda: asyncio.run(client.get_system_status()).get("time"))


def _control(entry: Mapping[str, Any]) -> TimeParty:
    client = ControlClient(_required(entry, "url"), token=str(_required(entry, "token")),
                           ca_bundle_path=entry.get("ca_bundle_path") or None)
    return ClientParty(entry["name"], "control", client.set_time, lambda: client.status().time)


def _chain(entry: Mapping[str, Any]) -> TimeParty:
    url = _required(entry, "url")

    def rpc(method: str, params: list[Any]) -> Any:
        answer = httpx.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method,
                                       "params": params}, timeout=10.0).json()
        if "error" in answer:
            raise LaneTimeError(f"{method} refused: {answer['error']}")
        return answer["result"]

    return ChainParty(entry["name"], rpc)


def _buyer(entry: Mapping[str, Any]) -> TimeParty:
    path = Path(str(_required(entry, "file")))
    # The harness writes the file the buyer's configuration names; its
    # directory is the run's own.
    path.parent.mkdir(parents=True, exist_ok=True)
    return BuyerFileParty(entry["name"], TimeFile(path))


_BUILDERS: dict[str, Callable[[Mapping[str, Any]], TimeParty]] = {
    "storefront": _storefront, "provisioning": _provisioning, "registry": _registry,
    "credits": _credits, "control": _control, "chain": _chain, "buyer": _buyer,
}


#: The suffix of a party field naming the setting that holds its value: a
#: profile with no secrets of its own, such as a Helm release's ConfigMap
#: profile, names the secrets profile's key rather than restating its value.
_SETTING_SUFFIX = "_setting"


def _setting(path: str) -> Any:
    return settings.get(path)


def _resolved(entry: Mapping[str, Any], setting: Callable[[str], Any]) -> dict[str, Any]:
    """``entry`` with each ``<field>_setting`` replaced by ``<field>`` read from that setting."""
    resolved = {key: value for key, value in entry.items() if not key.endswith(_SETTING_SUFFIX)}
    for key, path in entry.items():
        if not key.endswith(_SETTING_SUFFIX):
            continue
        field = key.removesuffix(_SETTING_SUFFIX)
        value = setting(str(path))
        if value in (None, ""):
            raise LaneTimeError(
                f"lane_time party {entry.get('name', '?')!r} takes its {field} from "
                f"setting {path!r}, which the run's profiles do not set")
        resolved[field] = value
    return resolved


def _entries(section: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The section's parties, a list of entries or a mapping keyed by name — the
    form Helm values take, so an overlay changes one party alone."""
    parties = section.get("parties") or []
    if isinstance(parties, Mapping):
        return [{**dict(entry or {}), "name": name} for name, entry in parties.items()]
    return [dict(entry) for entry in parties]


def parties_from(section: Mapping[str, Any], *,
                 setting: Callable[[str], Any] = _setting) -> list[TimeParty]:
    """Every party the ``lane_time`` section names, each over its typed client.

    A field ``<field>_setting`` names the dotted setting its value is read from,
    so a credential stays in the profile that holds the run's secrets.
    """
    parties = []
    for entry in _entries(section):
        entry = _resolved({str(key).lower(): value for key, value in entry.items()}, setting)
        _required(entry, "name")
        kind = _required(entry, "kind")
        if kind not in _BUILDERS:
            raise LaneTimeError(f"lane_time party {entry['name']!r} is of unknown kind {kind!r}")
        parties.append(_BUILDERS[kind](entry))
    return parties


def buyer_time_file(section: Mapping[str, Any] | None) -> str | None:
    """The buyer's lane-time file in an injected run, which its configuration names."""
    if not section or section.get("mode") != "injected":
        return None
    for entry in _entries(section):
        if entry.get("kind") == "buyer":
            return str(entry.get("file") or "") or None
    return None


def wall_instant() -> int:
    """The wall instant the session starts an injected run at, unless a party
    already holds a later one."""
    return int(time.time())


def lane_time_of(section: Mapping[str, Any] | None, *,
                 parties: Callable[[Mapping[str, Any]], list[TimeParty]] = parties_from,
                 start: Callable[[], int] = wall_instant) -> LaneTime | None:
    """The run's lane time from its profile section, started; None with no section.

    An injected run installs an injected source in the harness's process before
    any party is built, so every client the harness builds signs at lane time.
    The caller restores the process's previous source when the run ends.
    """
    if section is None:
        return None
    mode = section.get("mode")
    harness = None
    if mode == "injected":
        harness = InjectedTime(start=start())
        injected_time.install(harness)
    lane = LaneTime(mode, parties(section), harness=harness, wait=wait_until,  # type: ignore[arg-type]
                    target=str(section.get("target") or ""))
    lane.start(start())
    return lane


@pytest.fixture(scope="session", autouse=True)
def lane_time() -> Iterator[LaneTime | None]:
    """The run's lane time, started at the session's start; None for a run whose
    profile has no ``lane_time`` section. A party missing, unreachable, astray or
    on another source fails the setup by name."""
    before = injected_time.installed()
    try:
        try:
            lane = lane_time_of(lane_time_settings(settings))
        except LaneTimeError as error:
            pytest.fail(str(error))
        yield lane
    finally:
        injected_time.install(before)


__all__ = [
    "BuyerFileParty",
    "ChainParty",
    "ClientParty",
    "LaneTime",
    "LaneTimeError",
    "MAX_CLOCK_WAIT",
    "MODES",
    "SET_ORDER",
    "TimeParty",
    "TimeReading",
    "buyer_time_file",
    "lane_time",
    "lane_time_of",
    "lane_time_settings",
    "parties_from",
    "wait_until",
    "wall_instant",
]
