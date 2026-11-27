# Lease-end report first use

From a clean checkout:

```sh
make dist-ci
make -C provisioning/compute/service first-use-lease-end
```

The example owns a temporary file-backed SQLite database and uses a public,
deterministic development site principal. It requires no credentials, deployment
selector, server, container or payment/dispute service. Its injected release
executor represents proven undispatched work; it does not claim to validate
physical teardown.

The output shows expiry, caller-attributed termination, direct release, release
failure and force release. Each lease end is recorded as a `site.lease_ended`
event in the site transition's own transaction, which signs its report and keeps
it in `lease_end_reports`. The lease-end report consumer delivers the stored
report to a scripted storefront: a lost acknowledgement is replayed, once its
retry is due, by a restarted consumer with unchanged signed payload. The lease
route's pull projection returns that same report, and verification binds the
configured site principal, logical site and reservation together. A 404 from an
older receiver parks the peer's destination while the signed report stays
readable through the pull. Release failure still holds capacity.

Production composition supplies the site's configured identity and logical site
ID, signs the report in the ending transaction, and runs the lease-end report
consumer, with one destination per configured storefront peer, on the event
delivery worker, beside the capacity-released consumer and its own
acknowledgements. A first peer receives the reports recorded since the consumer
last read; a peer configured beside or in place of another is a new destination
that receives no earlier report, and the previous peer's destination is
retired. An administrator
resumes a parked destination through `POST /api/v1/events/destinations/{name}/resume`.
The callback contract is `LEASE_ENDED_CALLBACK` in the compute contracts;
storefront compositions bind it to their verified delivery ingress. This
independent library/service example is not deployed storefront acceptance.
