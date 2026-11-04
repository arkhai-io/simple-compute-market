"""Try immutable lease-ended events, durable push replay and signed pull without services."""

import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from compute_provisioning.lease_lifecycle import LeaseLifecycleService
from compute_provisioning.executor_leases import ExecutorLeaseService
from compute_provisioning.leases import LeaseRouteService
from compute_provisioning.release import ReleaseAction, ReleaseDecision
from compute_provisioning_contracts import LeaseForceRelease, LeaseTermination, verify_lease_end
from market_identity import Ed25519Signer, TrustedIdentitySet
from market_site.authority import LedgerSiteAuthority
from market_site.db import Base as SiteBase, CapacityReservation
from market_site.ledger import CapacityLedgerService
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from compute_provisioning_service.db.models import LeaseEndReportOutbox
from compute_provisioning_service.services.lease_end_reports import LeaseEndReports


class Undispatched:
    async def submit_release(self, reservation):
        return ReleaseDecision(action=ReleaseAction.FREE)

    async def begin_teardown(self, fulfillment_id):
        raise AssertionError("nothing was dispatched")


async def main():
    # Public deterministic development identity; never use on a public network.
    site = Ed25519Signer(bytes([3]) * 32)
    with TemporaryDirectory(prefix="lease-end-reports-") as root:
        engine = create_engine("sqlite:///" + str(Path(root) / "site.sqlite"))
        SiteBase.metadata.create_all(engine)
        LeaseEndReportOutbox.__table__.create(engine)
        factory = sessionmaker(bind=engine)
        reports = LeaseEndReports(factory, signer=site, peer="fixture-storefront")
        ledger = CapacityLedgerService(
            factory, site_id="fixture-site", lease_end_effect=reports.record,
        )
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
        seen = []
        async def lost_ack(report):
            seen.append(report.model_dump_json())
            return "retry"
        await reports.drain(lost_ack)
        restarted = LeaseEndReports(factory, signer=site, peer="fixture-storefront")
        async def acknowledged(report):
            seen.append(report.model_dump_json())
            return "delivered"
        await restarted.drain(acknowledged)
        routes = LeaseRouteService(ExecutorLeaseService(authority), lifecycle, reports=restarted.read)
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
        async def unsupported(report):
            return "unsupported"
        await restarted.drain(unsupported)
        with factory() as db:
            parked = db.get(LeaseEndReportOutbox, ledger.lease_end_events("unsupported")[0]["event_id"]).parked
        print(json.dumps({
            "causes": {name: [item["cause"] for item in ledger.lease_end_events(name)]
                       for name in ("expiry", "termination", "direct", "failure", "force")},
            "retry_preserves_bytes": sorted(seen[:len(seen)//2]) == sorted(seen[len(seen)//2:]),
            "pull_preserves_report": pulled.model_dump_json() == before,
            "caller_reason": event.reason, "caller": event.caller.model_dump(mode="json"),
            "unsupported_parked": parked, "unsupported_pull_retained": bool(restarted.read("unsupported")),
            "release_failure_still_holds_capacity": ledger.get_reservation("failure")["state"] == "release_failed",
        }))


if __name__ == "__main__":
    asyncio.run(main())
