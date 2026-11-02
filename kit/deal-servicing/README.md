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
