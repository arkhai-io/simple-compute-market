"""Port fakes, a fake site and provisioning service, and the real servicing journal.

The fake site keeps placement-keyed reserve replay, the commit, activation and
release state machine, and an acknowledgement that can be lost after its effect,
as the site does; the fake provisioning service begins one fulfillment per
reservation. The progress fake keeps its row in the storefront database beside
end service's journal, so its writes commit or roll back with the transaction
the path hands it, as a domain's own row does.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pytest
from compute_provisioning_contracts import (
    FulfillmentAcceptanceResponse,
    FulfillmentRequestBody,
    FulfillmentStatusResponse,
    LeaseView,
)
from compute_provisioning_contracts.contracts import lease_state_for_reservation_state
from market_alkahest.payment_adapter import AlkahestOnceAdapter
from market_capacity_publication import CapacityEffects, publication_binding
from market_core import VersionedEnvelope
from market_deal_lifecycle.delivery import BillingStartResult, ReadyEvidenceRef
from market_deal_servicing import DeliveryRecord, EndService, EndSession, PhysicalResult, create_schema
from market_deal_servicing.evidence import transaction
from market_identity import Ed25519Signer
from market_site_client import SiteCapacityClientError, SiteCapacityUnauthenticatedResponseError

from compute_delivery import (
    AcceptedDeal,
    ComputeDeliveryPath,
    ContinuationState,
    RecordedProgress,
    ReserveClaim,
)
from compute_delivery.window import utc_text

#: The Agreement start every scenario is built around, in Unix seconds.
START = 1_800_000_000
#: Public deterministic development seed; never use on a public network.
SELLER = Ed25519Signer(bytes([2]) * 32)
SITE = "site-a"


class LostAcknowledgement(SiteCapacityClientError):
    """The site applied the effect and its answer never arrived."""


class FakeSite:
    """An aggregate capacity client over one site's reservation ledger."""

    def __init__(self, clock: list[int]) -> None:
        self.site_names = (SITE,)
        self.clock = clock
        self.rows: dict[str, dict[str, Any]] = {}
        self.keys: dict[str, tuple[str, dict[str, Any]]] = {}
        self.capacity = True
        self.lose: dict[str, int] = {}
        self.refuse_commit: set[str] = set()
        self.activation: str = "answer"
        self.releases: list[tuple[str, str | None]] = []
        self.calls: list[str] = []
        #: Each commit's requested window, as sent.
        self.commits: list[tuple[str, str | None, str | None]] = []
        #: An answer raised before an operation takes effect.
        self.refuse_first: dict[str, SiteCapacityClientError] = {}
        #: Called as an operation arrives, before it takes effect.
        self.on_arrival: dict[str, Any] = {}
        #: Fields an answer is rewritten with, as a malformed answer would read.
        self.rewrite: dict[str, dict[str, Any]] = {}

    def _arrive(self, operation: str) -> None:
        self.calls.append(operation)
        if operation in self.on_arrival:
            self.on_arrival[operation]()
        if operation in self.refuse_first:
            raise self.refuse_first.pop(operation)

    def _answer(self, operation: str, row: dict[str, Any]) -> dict[str, Any]:
        if self.lose.get(operation, 0) > 0:
            self.lose[operation] -= 1
            raise LostAcknowledgement(f"{operation} acknowledgement lost")
        return {**row, "site": SITE, **self.rewrite.get(operation, {})}

    async def reserve(self, *, claim, deal_ref, ttl_seconds=None, lease_start_utc=None,
                      lease_duration_seconds=None, site=None):
        self._arrive("reserve")
        key = (deal_ref or {}).get("placement_key")
        request = {"claim": dict(claim), "start": lease_start_utc, "duration": lease_duration_seconds}
        if key is not None and key in self.keys:
            reservation_id, recorded = self.keys[key]
            if recorded != request:
                raise SiteCapacityClientError("placement replay changes the request", status_code=409)
            return self._answer("reserve", self.rows[reservation_id])
        if not self.capacity:
            return None
        reservation_id = f"res-{len(self.rows) + 1}"
        self.rows[reservation_id] = {
            "capacity_reservation_id": reservation_id, "state": "reserved",
            "deal_ref": dict(deal_ref or {}), "lease_start_utc": None, "lease_end_utc": None,
            "activated_at_utc": None,
            "hold_expires_at": None if ttl_seconds is None else self.clock[0] + int(ttl_seconds),
        }
        if key is not None:
            self.keys[key] = (reservation_id, request)
        return self._answer("reserve", self.rows[reservation_id])

    def expire(self, reservation_id: str) -> None:
        self.rows[reservation_id].update(state="released", failure_reason="hold_expired")

    async def commit(self, *, resource_id, capacity_reservation_id, lease_start_utc=None,
                     lease_end_utc=None, idempotency_ref=None, deal_ref=None, site_id=None):
        self.commits.append((capacity_reservation_id, lease_start_utc, lease_end_utc))
        self._arrive("commit")
        row = self.rows.get(capacity_reservation_id)
        if row is None:
            raise SiteCapacityClientError("unknown reservation", status_code=404)
        if capacity_reservation_id in self.refuse_commit or row["state"] not in ("reserved", "leased"):
            raise SiteCapacityClientError(f"reservation is {row['state']}; cannot commit", status_code=409)
        if row["state"] == "reserved":
            row.update(state="leased", lease_start_utc=lease_start_utc, lease_end_utc=lease_end_utc,
                       hold_expires_at=None)
        return self._answer("commit", row)

    async def release(self, *, capacity_reservation_id, deal_ref=None, failure_reason=None,
                      failure_message=None, site_id=None):
        self._arrive("release")
        row = self.rows[capacity_reservation_id]
        self.releases.append((capacity_reservation_id, failure_reason))
        row["state"] = "released"
        return self._answer("release", row)

    async def truncate_lease(self, *, capacity_reservation_id, lease_end_utc, site_id=None):
        row = self.rows[capacity_reservation_id]
        if datetime.fromisoformat(lease_end_utc) < datetime.fromisoformat(row["lease_end_utc"]):
            row["lease_end_utc"] = lease_end_utc
        return {**row, "site": SITE}

    async def activate_lease(self, *, capacity_reservation_id, site_id=None):
        self._arrive("activate")
        if self.activation == "unsigned":
            raise SiteCapacityUnauthenticatedResponseError("unsigned answer", status_code=404)
        if self.activation == "unreachable":
            raise SiteCapacityClientError("site unreachable")
        row = self.rows.get(capacity_reservation_id)
        if row is None or self.activation == "unknown":
            raise SiteCapacityClientError("unknown reservation", status_code=404)
        if row["state"] != "leased":
            raise SiteCapacityClientError(f"reservation is {row['state']}; cannot activate", status_code=409)
        if row["activated_at_utc"] is None:
            row["activated_at_utc"] = utc_text(self.clock[0])
        return self._answer("activate", row)


class FakeFulfillment:
    """The provisioning service's fulfillment surface: one fulfillment per reservation."""

    def __init__(self, site: FakeSite) -> None:
        self.site = site
        self.by_reservation: dict[str, str] = {}
        self.begins: list[FulfillmentRequestBody] = []
        self.state = "active"
        self.result: dict[str, Any] = {"endpoint": "vm-1.example:22", "ready_at": "fixed"}
        self.lose_begin = 0
        self.reads: list[str] = []
        #: Fields an answer is rewritten with, by read: ``status`` or ``lease``.
        self.rewrite: dict[str, dict[str, Any]] = {}

    async def begin_fulfillment(self, body, *, site_id):
        self.begins.append(body)
        reservation_id = body.capacity_reservation_id
        fulfillment_id = self.by_reservation.setdefault(reservation_id, f"ful-{len(self.by_reservation) + 1}")
        if self.lose_begin:
            self.lose_begin -= 1
            raise ConnectionError("begin acknowledgement lost")
        return FulfillmentAcceptanceResponse(
            fulfillment_id=fulfillment_id, capacity_reservation_id=reservation_id, state="dispatch_pending",
        )

    async def get_fulfillment_status(self, fulfillment_id, *, capacity_reservation_id, site_id):
        self.reads.append("status")
        return FulfillmentStatusResponse(
            fulfillment_id=fulfillment_id, capacity_reservation_id=capacity_reservation_id,
            state=self.state, failure_reason="create_failed" if self.state == "failed" else None,
        ).model_copy(update=self.rewrite.get("status", {}))

    async def get_fulfillment_result(self, fulfillment_id, *, capacity_reservation_id, site_id):
        self.reads.append("result")
        return VersionedEnvelope(kind="fulfillment.result.v1", schema_version=1, payload=dict(self.result))

    async def get_lease(self, capacity_reservation_id, *, site_id):
        row = self.site.rows[capacity_reservation_id]
        return LeaseView(
            capacity_reservation_id=capacity_reservation_id, deal_ref=row["deal_ref"], offering_mode="vm",
            executor_target="host-1", lease_start_utc=row["lease_start_utc"],
            lease_end_utc=row["lease_end_utc"], status=lease_state_for_reservation_state(row["state"]),
        ).model_copy(update=self.rewrite.get("lease", {}))


class FakeProgress:
    """A domain progress row in the storefront database, each record written once."""

    def _ensure(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS fake_delivery_progress (
                negotiation_id TEXT PRIMARY KEY, step TEXT NOT NULL, reservation TEXT,
                fulfillment TEXT, activated_at INTEGER, claim_owner TEXT)"""
        )

    def load(self, conn, negotiation_id):
        self._ensure(conn)
        row = conn.execute(
            "SELECT step, reservation, fulfillment, activated_at FROM fake_delivery_progress WHERE negotiation_id=?",
            (negotiation_id,),
        ).fetchone()
        return None if row is None else RecordedProgress(*row)

    def create(self, conn, negotiation_id):
        self._ensure(conn)
        conn.execute(
            "INSERT OR IGNORE INTO fake_delivery_progress VALUES (?, 'reserve', NULL, NULL, NULL, 'worker')",
            (negotiation_id,),
        )

    def _once(self, conn, negotiation_id, column, value, step):
        current = conn.execute(
            f"SELECT {column} FROM fake_delivery_progress WHERE negotiation_id=?", (negotiation_id,),
        ).fetchone()[0]
        if current is not None and current != value:
            raise ValueError(f"{column} cannot change once recorded")
        conn.execute(
            f"UPDATE fake_delivery_progress SET {column}=?, step=? WHERE negotiation_id=?",
            (value, step, negotiation_id),
        )

    def record_reservation(self, conn, negotiation_id, capacity_reservation_id):
        self._once(conn, negotiation_id, "reservation", capacity_reservation_id, "commit")

    def record_dispatch(self, conn, negotiation_id):
        conn.execute("UPDATE fake_delivery_progress SET step='dispatch' WHERE negotiation_id=?", (negotiation_id,))

    def record_fulfillment(self, conn, negotiation_id, fulfillment_id):
        self._once(conn, negotiation_id, "fulfillment", fulfillment_id, "fulfillment")

    def record_activation(self, conn, negotiation_id, activated_at):
        self._once(conn, negotiation_id, "activated_at", activated_at, "activated")

    def release_claim(self, conn, negotiation_id):
        conn.execute("UPDATE fake_delivery_progress SET claim_owner=NULL WHERE negotiation_id=?", (negotiation_id,))

    def write(self, path, negotiation_id, **values):
        """Set a row as a domain might have left it; test setup only."""
        with transaction(path) as conn:
            self.create(conn, negotiation_id)
            for column, value in values.items():
                conn.execute(
                    f"UPDATE fake_delivery_progress SET {column}=? WHERE negotiation_id=?", (value, negotiation_id),
                )

    def row(self, path, negotiation_id) -> dict[str, Any] | None:
        with sqlite3.connect(path) as conn:
            self._ensure(conn)
            conn.row_factory = sqlite3.Row
            found = conn.execute(
                "SELECT * FROM fake_delivery_progress WHERE negotiation_id=?", (negotiation_id,),
            ).fetchone()
        return dict(found) if found else None


class FakeDomain:
    def __init__(self, accepted: AcceptedDeal) -> None:
        self.accepted: Any = accepted
        self.claim: Any = ReserveClaim(claim={"resource_type": "vm", "dimensions": {"vcpu": 2}})
        self.hold: Any = None
        self.ready: Any = ReadyEvidenceRef(schema_id="test.ready.v1", resource_ref="vm-1", digest="a" * 64)
        self.continuation_state = ContinuationState.NONE
        self.continuations = 0
        self.request_reservation: str | None = None

    async def accepted_deal(self, negotiation_id):
        return self.accepted

    async def reserve_claim(self, negotiation_id):
        return self.claim

    async def accepted_hold(self, negotiation_id):
        return self.hold

    async def fulfillment_request(self, negotiation_id, *, capacity_reservation_id, window):
        return FulfillmentRequestBody(
            capacity_reservation_id=self.request_reservation or capacity_reservation_id, market="vm",
            fulfillment_request=VersionedEnvelope(
                kind="test.vm.v1", schema_version=1,
                payload={"lease_start_utc": window.start_utc, "lease_end_utc": window.end_utc},
            ),
        )

    async def ready_evidence(self, negotiation_id, result):
        return self.ready

    async def continuation(self, negotiation_id):
        self.continuations += 1
        return self.continuation_state


class FakeEndPort:
    """The domain's end port: a reservation nothing was dispatched for is released."""

    def __init__(self, path, site: FakeSite, progress: FakeProgress) -> None:
        self.path = path
        self.site = site
        self.progress = progress
        self.calls: list[tuple[bool, int, str]] = []

    async def apply_end(self, negotiation_id, *, terminate, at, operation_key):
        self.calls.append((terminate, at, operation_key))
        with sqlite3.connect(self.path) as conn:
            recorded = self.progress.load(conn, negotiation_id)
        reservation = recorded.capacity_reservation_id if recorded else None
        if not terminate:
            if reservation is not None and self.site.rows[reservation]["state"] == "leased":
                await self.site.truncate_lease(
                    capacity_reservation_id=reservation, lease_end_utc=utc_text(at), site_id=SITE,
                )
            return PhysicalResult(progress="end_recorded", done=True)
        if reservation is None:
            return PhysicalResult(progress="released", done=True)
        if recorded.step in ("reserve", "commit"):
            await self.site.release(capacity_reservation_id=reservation, failure_reason=operation_key, site_id=SITE)
            return PhysicalResult(progress="released", done=True)
        return PhysicalResult(progress="tearing_down", done=True)


class ScriptedAdapter:
    """A once-only adapter whose authorization answers can be scripted per phase."""

    def __init__(self, inner, *, on_authorize=None) -> None:
        self.inner = inner
        self.supported_commands = inner.supported_commands
        self.answers: dict[str, list[str]] = {}
        self.on_authorize = on_authorize
        self.authorized: list[str] = []
        self.billing_keys: list[str] = []
        #: Billing starts whose answer is lost after the authority took them.
        self.lose_billing = 0
        #: An outcome billing start answers instead of the adapter's own.
        self.billing_outcome: Any = None
        #: Every call made on the adapter, by method name.
        self.calls: list[str] = []

    def validate(self, command):
        self.calls.append("validate")
        return self.inner.validate(command)

    async def submit(self, command, keys):
        self.calls.append("submit")
        return await self.inner.submit(command, keys)

    async def read(self):
        self.calls.append("read")
        return await self.inner.read()

    async def authorize(self, phase, evidence):
        self.calls.append("authorize")
        self.authorized.append(phase.value)
        if self.on_authorize is not None:
            self.on_authorize(phase)
        scripted = self.answers.get(phase.value)
        if scripted:
            status = scripted.pop(0)
            decision = await self.inner.authorize(phase, evidence)
            return decision.model_copy(update={"status": status, "reason": f"scripted {status}"})
        return await self.inner.authorize(phase, evidence)

    async def start_billing(self, operation_key, evidence):
        self.calls.append("start_billing")
        self.billing_keys.append(operation_key)
        if self.billing_outcome is not None:
            return BillingStartResult(outcome=self.billing_outcome)
        started = await self.inner.start_billing(operation_key, evidence)
        if self.lose_billing:
            self.lose_billing -= 1
            raise ConnectionError("billing-start acknowledgement lost")
        return started


@dataclass
class Rig:
    path: Any
    clock: list[int]
    site: FakeSite
    fulfillment: FakeFulfillment
    progress: FakeProgress
    domain: FakeDomain
    end_port: FakeEndPort
    end: EndService
    adapter: ScriptedAdapter
    delivery: ComputeDeliveryPath
    negotiation_id: str = "deal"
    validations: list[bool] = field(default_factory=list)
    #: What the Alkahest stage's commitment validator answers.
    commitment_valid: list[bool] = field(default_factory=lambda: [True])
    #: The Agreement start the deal is registered with.
    start: int = START
    site_id: str = SITE

    async def drive(self):
        return await self.delivery.drive(self.negotiation_id)

    def session(self):
        return transaction(self.path)

    def record(self) -> DeliveryRecord:
        with transaction(self.path) as conn:
            return EndSession(conn).read(self.negotiation_id)

    def register(self, *, start: int = START, term_end: int | None = None, committed_at: int | None = None,
                 delivery_deadline_seconds: int | None = None) -> None:
        with transaction(self.path) as conn:
            EndSession(conn).register(DeliveryRecord(
                negotiation_id=self.negotiation_id, seller=SELLER.identity, commitment_ref="commitment",
                start_at=start, term_end=start + 7200 if term_end is None else term_end,
                committed_at=start - 600 if committed_at is None else committed_at,
                delivery_deadline_seconds=delivery_deadline_seconds,
            ))


@pytest.fixture
def rig(tmp_path) -> Rig:
    """A deal accepted for ``[START, START + 2h)``, its clock half an hour in."""
    path = tmp_path / "storefront.sqlite"
    # Deal servicing's tables, which the storefront's chain creates and no
    # session does.
    with transaction(path) as conn:
        create_schema(conn)
    clock = [START + 1800]
    site = FakeSite(clock)
    fulfillment = FakeFulfillment(site)
    progress = FakeProgress()
    end_port = FakeEndPort(path, site, progress)
    end = EndService(path, end_port, clock=lambda: clock[0])
    validations: list[bool] = []

    async def validate(evidence):
        validations.append(commitment_valid[0])
        return commitment_valid[0]

    commitment_valid = [True]

    adapter = ScriptedAdapter(AlkahestOnceAdapter(
        negotiation_id="deal", commitment_ref="commitment", validate_commitment=validate,
    ))
    binding = publication_binding(capacity_backing="backed", site_id=SITE, offering_mode="vm", source_id="pool-a")
    domain = FakeDomain(AcceptedDeal(commitment_ref="commitment", binding=binding, payment=adapter))
    delivery = ComputeDeliveryPath(
        end=end, progress=progress, domain=domain, capacity=CapacityEffects(site), fulfillment=fulfillment,
    )
    rig = Rig(path, clock, site, fulfillment, progress, domain, end_port, end, adapter, delivery,
              validations=validations, commitment_valid=commitment_valid)
    rig.register()
    return rig
