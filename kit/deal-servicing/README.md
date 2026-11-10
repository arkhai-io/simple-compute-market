# Seller lifecycle servicing

`market_deal_servicing` is a storefront-side library. It receives authority
adapters and physical-delivery ports from its domain composition; it neither
interprets financial snapshots nor owns payment accounting.

## Evidence

`SQLiteEvidenceStore(path)` implements the foundation's async evidence port.
`EvidenceSession(connection)` borrows an existing storefront SQLite transaction
so capture and acceptance can commit together; none of these session operations
commits. Call
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

Register immutable
Agreement timing, commitment and seller identity before delivery. `admit` returns
`retry` on a stale revision and `ended` once a controlling end has arrived; keep
the same session through the corresponding reservation/dispatch/activation or
credential write. An earlier lawful end prevents refused admission from creating
a seller-failure correction. A later clock/authority end does not erase an
already-missed delivery deadline.

`record_end` retains every source and deterministic equal-time attribution. It
atomically journals either the required filing or a pending-classification slot.
`resolve_correction` discharges that slot, records the required filing, or adopts
an explicitly named verified controlling source under the same revision and fixed
basis without rewriting the original request. Both paths preserve the controlling
classification and reuse its filing. A classified selected end suppresses new
filings from later superseded sources. A pending selected site report cannot
discharge an independently established seller failure: its filing is retained in
either arrival order and exposed on seller reads. Later resolution requiring an
unsupported financial revision is visible repair state, never a silent lost filing.
`failure_filing` fixes never-delivered claims at the Agreement start/failure basis
and defers future-start filing until start.
It never computes a monetary remedy. The seller half dispatches these intents.

`EndService.drive_physical` calls an injected domain port with stable operation
keys. That port must adopt dispatched work, never extend leases, and deduplicate
before physical effects. Truncation and termination have distinct keys; late
earlier evidence changes attribution without repeating termination. Recovery
remains the domain's assertion, never inferred from an end intent.

`authorize_delivery` reads the payment adapter before opening a database
transaction, then checks `expected_revision` and admission in a worker thread.
Its optional `apply(session, authorization)` callback performs the protected local
write in that same transaction and must not perform I/O. An adapter allow cannot
override a stale revision or end. `begin_billing` owns the immutable billing key/evidence before I/O. Unknown
results remain pending for same-key adapter resolution and block disclosure;
a validated once-only adapter can return an accepted no-op. Delivery retains
only the returned intent reference.

## Watch

`DealWatch.poll` performs one bounded observation cycle through injected payment
and dispute adapters. Dispute bindings include the Agreement-pinned record key;
the owning adapter verifies signed records before observation. Configure the
client's capture callback to keep exact transport responses as well as projected
signed entries. `WatchSession` retains independent payment/dispute cursors and
last verified views separately from the current read outcome; extensions remain
identified by their own references, not cases. Full-history responses, including
empty ones, cannot regress below the durable cursor. A failed refresh reports its
own outcome while keeping the last verified records available.

Every delivery-end effect is journaled before its record cursor advances. A
counterparty case at a respondent-capable authority is left to `RespondentPoller`,
which signs matching facts or contests them from durable evidence. Its cursor
waits until that exact answer is journaled or the case is confirmed closed.
Authorities without respondent discovery use a stable evidence append. Never-attempted appends to confirmed closed cases are skipped;
uncertain attempts replay the original key first so an earlier acknowledgement
survives a closed-case race. Payment-stop classification is an injected,
evidence/entitlement-based hook: without it the correction remains pending,
never inferred lawful from event kind. A complete retention projection can also
be injected with `seller_retention(path, negotiation_id, clock=...)`; a failed
authority read never supplies a new pruning observation. The payment adapter's
optional `AuthorityView.payouts` maps every part to a verified completion observation
or `None`; an absent projection keeps evidence. The observer combines this with
case closes and proven local recovery, preserving first completion observations.
`SellerServicing.prune` refreshes all required records before applying the window.

`peer_hint` preserves evidence and reads authorities, not peer-asserted state.
`watch` yields current views and newly journaled events for one cycle. Compose
its repeated bounded step through `register_deal_watch` in the storefront kit,
which supplies pause, serialization and operator-step semantics rather than a
second timer in this library. Drain physical intents separately through end
service. Domain registration of that step belongs to the domain composition.

## Seller half

`SellerSession.register` records the immutable committed projection beside delivery
registration in the caller's transaction. Supply metadata from the selected
Agreement through its accessors. `SellerServicing` resolves adapters using those
pinned bindings, not the currently offered authorities. Its credential hook checks
the complete authority identity, independently of publication preferences.
For an immutable binding read while ingress owns a write transaction, use
`SellerSession(conn)` on a separate read connection: a session issues no DDL, so
it opens no competing writer.

`list` returns bounded keyset pages from durable watched views. `read` refreshes
both records and returns physical progress even without a payment adapter. A
missing dispute credential or unresolved local respondent case marks repair
required. `RespondentPoller.repairs()` exposes bounded skipped-case diagnostics;
temporarily unresolvable local Agreements do not block later account-wide cases
and retry independently of the listing cursor in a rotating arrival-order queue.
Cases with no local registered commitment are skipped rather than retained as
repair rows. A payer claim matches only when its buyer request is the selected
end; a superseded surrender receives contesting end evidence. Once-only
commitments remain running until their delivery end, independently of rate-start
events.

`submit` routes explicit financial commands through the payment adapter and cases
through the dispute adapter. An operator `delivery_end` has no payload or `at`;
it requires an administrator and reason, fixes the local receipt instant, and
atomically records the end and the payee filing before any I/O. Drain
`dispatch_filings` in the controller-owned watch step. It respects deferred starts
and reuses the original key after lost responses. It returns each intent's outcome,
not just the last one. An authority rejection is terminal and retained as repair
required in `read` and `list`, whose `filings` carry the original refusal. Only
pending/unknown attempts are retried, including a semantic owner that must resolve
its original write before another caller can adopt it. Operator submit returns
only that operation's filing outcome, not unrelated filings' outcomes. Filing
acknowledgement is not a ruling; physical end work never waits for it and sends
no payment stop or reverse.

## Delivery ingress

`DeliveryIngress.end_delivery` verifies the accepted buyer's market envelope and
rejects any supplied instant. Receipt and final request commit together before
returning an acknowledgement for the route to sign; a retry retains the receipt.
No payment or dispute read is needed, so surrender works during authority outages.
The route owns the seller response signature. Ingress embeds the adapter-owned
claim only when that surrender is selected; an earlier seller-caused end cannot
be pre-empted by a signed payer claim.

`site_report` accepts exact bytes only through an injected domain verifier that
checks the reservation's configured site identity and event binding. The same
method handles push and authenticated pull recovery. Its classification hook
uses verified entitlement evidence; without it, the correction stays pending.
An unentitled classification journals the fixed-basis filing in the end
transaction, including pre-start failure deferred until the Agreement start.
A report correlated to an existing failure adopts its controlling filing, just
as a lawful consequence preserves its lawful classification. Never-delivered
claims use Agreement start, including a pre-start failure recorded late.
Duplicate events preserve their original observation and bytes. Neither ingress
path claims physical recovery or sends financial commands. Source/effect evidence
is pruned only under the Agreement's evidence-retention rule, not a fixed timer.

## Database execution

Constructors do not open databases. Async public operations run bounded database
units in worker threads and never keep a SQLite transaction across authority or
physical I/O. The explicit synchronous sessions and `DeliveryIngress` methods
are composition seams: async callers must use `asyncio.to_thread` (as the router
does), or an existing database worker.

## Schema

No session or poller creates a table. `SERVICING_SCHEMA` holds every table and
index the library reads and writes as `CREATE ... IF NOT EXISTS` DDL, and a
storefront composing it applies that DDL in a migration of its own chain, with
`create_schema(connection)` as the migration's body, so that opening the
library's sessions changes no schema. The statements tolerate tables already present, since a
storefront database built while sessions created these tables on first use may
hold some of them.

## First use

From a clean repository checkout:

```sh
make dist-ci
make -C kit/deal-servicing test
make -C kit/deal-servicing first-use
make -C kit/deal-servicing typecheck
```

The example uses only public deterministic development identities and the
vendored mediation kit's in-process fixture. It creates its own temporary SQLite
database, verifies and captures opening/counteroffer/admin acceptance messages,
then displays exact-byte retention, held-money protection, post-window pruning
and restart recovery. It needs no service, credentials, deployment selector or
resident server. It is a library demonstration, not deployed-domain acceptance.
