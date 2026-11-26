# request-replay

Replay refusal, exact-retry resolution and in-flight leasing over an opaque request
key, with durable stores. Distribution `arkhai-request-replay`, import
`request_replay`. It depends on the standard library alone; its SQLAlchemy store
needs the `sqlalchemy` extra. This README is its interface.

## What it does

A service that has already authenticated a request knows who sent it, the ID the
sender gave it, and what it asks. Three jobs follow, each with its own lifetime:

1. **Replay refusal.** Reserve the request before it runs, so a second copy is
   refused, and a reused ID asking anything else is refused as changed reuse. This
   needs a hash of the request, never its body.
2. **Exact-retry resolution.** A sender that lost its answer re-sends the same
   request under the same ID. A route either runs it again, where its own state
   recognises the retry as already applied, or answers the response it recorded the
   first time.
3. **In-flight leasing.** While an attempt runs it holds the request's lease, so a
   concurrent retry is told it is in progress; a lease left by a crashed process
   ends.

## The request

The caller admits each request as an `Entry`:

| Field | Meaning |
|---|---|
| `principal` | Who sent it, as an opaque string |
| `request_id` | The ID the sender gave it, kept on every retry |
| `request_hash` | A hash of everything the request asks; a changed hash is changed reuse |
| `resolution` | `Resolution.RERUN` or `Resolution.RECORDED`, as the route declares |
| `origin` | The instant the request was first signed, kept on every retry, in integer seconds |

## Admission

`RequestReplay(store, policy, clock=...)` admits an entry and answers one of:

| Admission | When | The caller |
|---|---|---|
| `Dispatch(attempt, exact_retry=False)` | A first use | Runs the handler, then `complete(attempt, outcome)` |
| `Dispatch(attempt, exact_retry=True)` | An exact retry of a `RERUN` request whose lease has ended | Runs the handler again, telling it the request is a retry, then `complete` |
| `Answered(outcome)` | An exact retry of a `RECORDED` request whose response is recorded | Answers the recorded status, headers and body |
| `InProgress()` | An attempt holds the lease | Refuses the retry as in progress |
| `ChangedReuse()` | The key is held under another hash | Refuses the request |
| `OutcomeUnknown()` | A `RECORDED` attempt's lease ended with no response recorded | Refuses the retry; the sender reads current state before writing again under a new ID |
| `Expired()` | A `RECORDED` retry whose origin is older than the retention, or older than the skew with no row | Refuses the retry as expired |

A `RECORDED` request is dispatched once: its lease is never reclaimed. A `RERUN`
request's ended lease is reclaimed by one retry. `complete` records a `RECORDED`
attempt's `Outcome` and clears its lease; for a `RERUN` attempt it only clears the
lease, recording nothing.

`renewing(replay, attempt)` is an async context manager renewing the attempt's lease
every third of its period while its body runs, and stopping when the body returns or
raises; an attempt shorter than a third of the lease writes nothing. A renewal the
store fails is tried again at the next interval. `Renewal.start(replay, attempt)`
does the same for a holder that starts renewal in one place and stops it, with
`await renewal.stop()`, in another. Hold a `RECORDED` attempt's handler inside one,
so a lease ends only when its process is gone and `OutcomeUnknown` means the attempt
has ended.

## Bounds

`Policy(skew_seconds, retention_seconds, lease_seconds)`, all positive integers.
`skew_seconds` is the tolerance the caller's signature check grants a request's
signing time either way.

Each row expires at the later of its lease's end and its bound:

- `RERUN`: origin + 2 × skew, the last instant a captured copy could still pass the
  signature check;
- `RECORDED`: origin + max(retention + skew, 2 × skew).

The expiry is raised whenever a lease is reclaimed or renewed. An expired row answers
nothing and refuses nothing: a reservation under its key replaces it. A `RECORDED`
first use needs an origin within the skew of the clock.

`RequestReplay.sweep(batch_size=500)` deletes every expired row through the index on
`expires_at`, each batch its own transaction; concurrent sweeps are harmless. Run it
at startup and then periodically.

Every instant is integer seconds on the `clock` the caller passes: the time source
its process reads the time of the world from. `renewing` waits on the monotonic
clock.

## Stores

- `SqliteReplayStore(connect, table=...)`: a standard-library `sqlite3` database,
  opening a connection per step through `connect` and taking the write lock for each.
- `request_replay.sqlalchemy_store.SqlAlchemyReplayStore(engine, table=...)`: any
  database SQLAlchemy reaches, with the `sqlalchemy` extra.

No store creates anything. `request_replay.ddl.statements(dialect, table=...)` gives
the `CREATE TABLE` and expiry-index statements for `sqlite` and `postgresql`, for the
caller's own migrations to run. The default table is `request_replay`. A row holds the
key, the hash, the resolution, the origin, the expiry, the lease's end and owner, and
for a recorded request the response's status, headers as a JSON array of pairs, and
body bytes. A principal is at most 512 characters, a request ID and a request hash
each at most 128, and a lease owner at most 64; PostgreSQL enforces these limits and
SQLite does not. Another store implements `ReplayStore`, each method one transaction.

## ASGI

`request_replay.asgi` lets a middleware admit a request on its whole body and record a
whole response: `read_body(receive)`, `replayed_receive(body, receive)` to hand the
application the body already read, `capture(app, scope, receive)` to run the
application and hold its response, and `send_response(send, status, headers, body)`.

## Proving a `RERUN` route

`request_replay.harness` proves a route may run an exact retry again.
`run_double_dispatch(case, snapshot=...)` sends the case's request, then a later write
to the same resource, then the request's exact retry, and fails unless the state after
the retry equals the state before it and the retry's answer equals the route's current
answer. `assert_complete(rerun_operations, cases)` fails naming every `RERUN`
operation with no case. `sqlite_snapshot(connection, exclude=...)` and
`request_replay.sqlalchemy_store.table_snapshot(engine, exclude=...)` read every table
but those excluded, the replay table among them.

## Development

- `make test` type-checks the package and runs its unit tests, the structure test
  holding its boundary among them, and its library-integration tests, which run every
  rule on both stores over real SQLite files.
- `make build` builds its wheel into its own `dist/`, or into `DIST_DIR`.
