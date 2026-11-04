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
failure and force release. Intended-end events and their signed outbox records
commit with the site transition. A lost acknowledgement is replayed across an
outbox restart with unchanged signed payload. The lease route's pull projection
returns that same report, and verification binds the configured site principal,
logical site and reservation together. Unsupported push is parked independently
of retained pull evidence. Release failure still holds capacity.

Production composition supplies the site's configured identity and logical site
ID, freezes the signed report in the ending transaction, and drains its own
event-keyed outbox through the lease-watchdog step. Capacity-released callbacks
retain their separate reservation-keyed outbox and acknowledgement. A configured
peer change never redirects stored reports to a different owner. After a
coordinated receiver upgrade, `LeaseEndReports.resume_peer()` explicitly re-enables
parked push. The callback contract is `LEASE_ENDED_CALLBACK` in the compute
contracts; storefront compositions bind it to their verified delivery ingress.
This independent library/service example is not deployed storefront acceptance.
