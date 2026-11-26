"""Try immutable lease-ended events, durable push replay and signed pull without services."""

import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import injected_time
from compute_provisioning.lease_lifecycle import LeaseLifecycleService
from compute_provisioning.executor_leases import ExecutorLeaseService
from compute_provisioning.leases import LeaseRouteService
from compute_provisioning.release import ReleaseAction, ReleaseDecision
from compute_provisioning_contracts import LeaseForceRelease, LeaseTermination, verify_lease_end
from injected_time import InjectedTime
from market_identity import Ed25519Signer, TrustedIdentitySet
from market_site.authority import LedgerSiteAuthority
from market_site.db import CapacityReservation
from market_site.ledger import CapacityLedgerService
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from storefront_client import StorefrontClientError

from compute_provisioning_service.db.database import migrate_database
from compute_provisioning_service.services.lease_end_reports import (
    LeaseEndReports,
    lease_end_report_consumer,
)
from compute_provisioning_service.services.operator_events import event_catalogue, event_recorder


class Undispatched:
    async def submit_release(self, reservation):
        return ReleaseDecision(action=ReleaseAction.FREE)

    async def begin_teardown(self, fulfillment_id):
        raise AssertionError("nothing was dispatched")


class ScriptedStorefront:
    """The storefront's lease-end route, answering from a script: a lost
    acknowledgement, an acknowledgement, or a 404 from an older receiver."""

    def __init__(self):
        self.answers = []
        self.seen = []
        self.url = "http://fixture-storefront"

    def client(self):
        return self

    def authenticated_request(self, method, path, *, body, **_):
        self.seen.append(json.dumps(body, sort_keys=True))
        answer = self.answers.pop(0) if self.answers else "accepted"
        if answer == "lost":
            raise ConnectionError("acknowledgement lost")
        if answer == 404:
            raise StorefrontClientError("not found", status_code=404)
        return {"status": answer}


async def main():
    # Public deterministic development identity; never use on a public network.
    site = Ed25519Signer(bytes([3]) * 32)
    # Held time, moved past the retry's backoff rather than waited out.
    source = InjectedTime()
    injected_time.install(source)
    with TemporaryDirectory(prefix="lease-end-reports-") as root:
        engine = create_engine("sqlite:///" + str(Path(root) / "site.sqlite"))
        migrate_database(engine)
        factory = sessionmaker(bind=engine)
        ledger = CapacityLedgerService(
            factory, site_id="fixture-site",
            event_recorder=event_recorder(event_catalogue(site), instance="fixture-site"),
        )
        reports = LeaseEndReports(factory)
        now = datetime.now(timezone.utc)
        with factory() as db, db.begin():
            for name in ("expiry", "termination", "direct", "failure", "force"):
                db.add(CapacityReservation(
                    capacity_reservation_id=name, state="leased", offering_mode="fixture",
                    lease_start_utc=(now - timedelta(hours=1)).isoformat(),
                    lease_end_utc=(now - timedelta(seconds=10) if name == "expiry"
                                   else now + timedelta(hours=1)).isoformat(),
                ))
        authority = LedgerSiteAuthority(ledger)
        lifecycle = LeaseLifecycleService(
            SimpleNamespace(lease_watchdog_grace_period_seconds=300), authority,
            release_executor=Undispatched(), release_status=None,
        )
        await lifecycle.force_check_leases()
        await lifecycle.terminate_lease("termination", LeaseTermination(reason="operator request"),
                                        caller=site.identity.model_dump(mode="json"))
        ledger.release(capacity_reservation_id="direct")
        ledger.begin_releasing("failure", release_job_id="fixture-release")
        ledger.record_release_failed("failure", reason="host unreachable", release_job_id="fixture-release")
        await lifecycle.force_release("force", LeaseForceRelease(reason="host inspected"),
                                      caller=site.identity.model_dump(mode="json"))
        await lifecycle.force_release("force", LeaseForceRelease(reason="host inspected"))
        before = reports.read("termination")[0].model_dump_json()
        storefront = ScriptedStorefront()
        storefront.answers = ["lost"]
        lease_end_report_consumer(factory, storefront, runner="first-use").run_cycle()
        # A restarted process replays what was not acknowledged, as it was
        # signed, once its retry is due.
        source.set(source.now() + 11)
        restarted = lease_end_report_consumer(factory, storefront, runner="first-use")
        restarted.run_cycle()
        routes = LeaseRouteService(ExecutorLeaseService(authority), lifecycle, reports=reports.read)
        pulled = routes.get("termination").end_reports[0]
        event = verify_lease_end(
            pulled, capacity_reservation_id="termination", site_id="fixture-site",
            expected_sites=TrustedIdentitySet(identities=(site.identity,)),
        )
        with factory() as db, db.begin():
            db.add(CapacityReservation(
                capacity_reservation_id="unsupported", state="leased", offering_mode="fixture",
                lease_start_utc=now.isoformat(), lease_end_utc=(now + timedelta(hours=1)).isoformat(),
            ))
        ledger.release(capacity_reservation_id="unsupported")
        storefront.answers = [404]
        parked = restarted.run_cycle().parked
        first_attempt, replayed = storefront.seen[0], storefront.seen[1]
        print(json.dumps({
            "causes": {name: [item["cause"] for item in ledger.lease_end_events(name)]
                       for name in ("expiry", "termination", "direct", "failure", "force")},
            "retry_preserves_bytes": first_attempt == replayed,
            "pull_preserves_report": pulled.model_dump_json() == before,
            "caller_reason": event.reason, "caller": event.caller.model_dump(mode="json"),
            "unsupported_parked": bool(parked), "unsupported_pull_retained": bool(reports.read("unsupported")),
            "release_failure_still_holds_capacity": ledger.get_reservation("failure")["state"] == "release_failed",
        }))


if __name__ == "__main__":
    asyncio.run(main())
