# Seller lifecycle servicing

`market_deal_servicing` is a storefront-side library. It receives authority
adapters and physical-delivery ports from its domain composition; it neither
interprets financial snapshots nor owns payment accounting.

## Evidence

`SQLiteEvidenceStore(path)` implements the foundation's async evidence port.
`EvidenceSession(connection)` borrows an existing storefront SQLite transaction
so capture and acceptance can commit together. Initialize its schema with
`create_schema(connection)`; none of these session operations commits. Call
`capture` from the verified-envelope sink, before returning parsed input, and
`accept` on each acceptance path with the captured buyer message ID and the
accepting seller or administrator principal. Pass lifecycle terms from the
selected Agreement, not current role configuration. They are frozen with the
acceptance so pruning cannot shorten its window.

Evidence IDs reject changed content and retain insertion order. Commitments
have at most one live attempt and superseded attempts cannot become live again.
Replay eviction does not touch these tables. `observe` accepts complete watched
payout/case/recovery observations; unknown payout, open extension, open case or
incomplete physical recovery prevents pruning. With no lifecycle terms or no
adapter pruning keeps evidence indefinitely.

## End service

Initialize `EndSession`'s schema in a caller-owned transaction. Register immutable
Agreement timing, commitment and seller identity before delivery. `admit` returns
`retry` on a stale revision and `ended` once a controlling end has arrived; keep
the same session through the corresponding reservation/dispatch/activation or
credential write. An earlier lawful end prevents refused admission from creating
a seller-failure correction. A later clock/authority end does not erase an
already-missed delivery deadline.

`record_end` retains every source and deterministic equal-time attribution. It
atomically journals either the required filing or a pending-classification slot.
`resolve_correction` discharges that slot or records the required filing under
the same revision and fixed basis. `failure_filing` fixes never-delivered claims
at the Agreement start/failure basis and defers future-start filing until start.
It never computes a monetary remedy. The seller half dispatches these intents.

`EndService.drive_physical` calls an injected domain port with stable operation
keys. That port must adopt dispatched work, never extend leases, and deduplicate
before physical effects. Truncation and termination have distinct keys; late
earlier evidence changes attribution without repeating termination. Recovery
remains the domain's assertion, never inferred from an end intent.

`authorize_delivery` combines the payment adapter's evidence decision with
caller-session admission; an adapter allow cannot override a stale revision or
end. `begin_billing` owns the immutable billing key/evidence before I/O. Unknown
results remain pending for same-key adapter resolution and block disclosure;
a validated once-only adapter can return an accepted no-op. Delivery retains
only the returned intent reference.

## First use

From a clean repository checkout:

```sh
make dist-ci
make -C kit/deal-servicing first-use
```

The example uses only public deterministic development identities and the
vendored mediation kit's in-process fixture. It creates its own temporary SQLite
database, verifies and captures opening/counteroffer/admin acceptance messages,
then displays exact-byte retention, held-money protection, post-window pruning
and restart recovery. It needs no service, credentials, deployment selector or
resident server. It is a library demonstration, not deployed-domain acceptance.
