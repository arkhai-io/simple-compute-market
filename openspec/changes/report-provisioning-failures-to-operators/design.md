# Design: report provisioning failures to operators

## Context

The proposal groups two of Goal 1's gaps (D1): a real playbook failure carries no
class, and nothing tells an operator when work is held for them. Reading the code
against the proposal, after `resolve-delivery-correctness-gaps` landed and
`marketplace-v0.4.0` shipped it, changed the picture in eight places.

1. **Two of the proposal's three conditions are one transition, and its bound
   exists.** `release_failed` now means only that an operator must act. A teardown
   whose playbook started and failed after its retries, and one whose reruns are
   spent (`RerunsSpent`, `teardown_rerun.py`), send the lease to `release_failed`
   with `teardown_failed`; a lease still `releasing` past
   `lease_watchdog_grace_period_seconds` (3600 seconds) goes there with
   `teardown_timeout` (`_process_releasing_reservation`, `lease_lifecycle.py`). A
   second bound would be the second clock the dependency's D3 rejected. The lease
   also enters `release_failed` with `release_unproven`, `release_submit_error`,
   `fulfillment_failed`, and the teardown refusals (`compensation_refused` among
   them).
2. **A cleanup refusal is pre-terminal.** A real bounded-cleanup refusal fails the
   reclaim job with `"Playbook failed"`, which the bare-metal codec's `is_retryable`
   answers `True`, so the job is retried after 60, 120 and 240 seconds.
   `VALIDATION_RUNBOOK.md`'s observation 5 depends on it: the operator repairs the
   fixture before retries are exhausted and the same job completes.
3. **No failure classifier matches a real run.** `TRANSPORT_FAILURES`, the VM
   codec's `VM_NON_RETRYABLE_FAILURES`, and the operator setting
   `additional_non_retryable_errors` (shipped in 0.4.0) are matched only against the
   `AnsibleError` message, which a real run sets to `"Playbook failed"`,
   `"Playbook timed out"` or `"Playbook error: …"`. Only the mock runner, raising
   `AnsibleError(rule.fail_with)`, matches them. Every real failure — an unreachable
   host, a refused login, a missing VM domain — is retried to `max_retries`.
4. **The engine discards the envelope.** `JobEngine.process_job` keeps only
   `outcome.error.message`, folded into `ansible_jobs.error`, and drops `code`,
   `retryable` and `details`, including the one structured code the real executor
   produces, `host_key_refused`.
5. **The roadmap names no operator event store.** That wording was the unowned
   row's before this change was opened.
6. **`kit/delivery` is introduction-shaped, its sinks are not.** `DeliveryEvent`
   requires an `obligation_ref` and a buyer or seller `role`, `[Delivery]` routes by
   seller origin, and dispatch is at most once with no outbox, by design. Its sinks
   read only `rendered`, `payload()` and `obligation_ref`. The provisioning service
   already runs two durable outboxes, `capacity_release_callback_outbox` and
   `lease_end_report_outbox`, each specific to one event and one peer.
7. **`fulfillment` is untouched.** What is reported when teardown is held is the
   lease's; convergence requeues `teardown_failed` without a ceiling.
8. **The bare-metal cleanup helper already reports structurally.**
   `tenant_working_data.py` prints `{"version": 1, "error": "Refusal", "message": …}`
   to stderr and exits 1, which reaches the job only inside the redacted log.

The provisioning service runs one database, which the site ledger, the job engine
and fulfillment share, so a producer can record an event in the transaction of the
change it reports. The deployed release is `marketplace-v0.4.0`
(`git log --tags --no-walk --decorate`); it carries `ansible_jobs.error`,
`JobStatusResponse.error`, `additional_non_retryable_errors`,
`site_lease_ended_events`, `lease_end_report_outbox` and
`capacity_release_callback_outbox`, and `arkhai-kit-delivery` 0.2.2 with its sink
contract.

## Goals / Non-Goals

**Goals**

- One eventing system, usable by any service: an open set of declared kinds, recorded
  in the producer's transaction, delivered at least once to each consumer.
- A real playbook failure classified from Ansible's own result records, the class
  deciding retry and kept on the job record.
- Operators told of held work, and of anything else they route, through the sinks
  they configure.
- The lease-end report and the capacity-released callback delivered as consumers of
  the eventing system, their 0.4.0 state carried over.

**Non-Goals**

- Rerunning a teardown that never reached its executor
  (`resolve-delivery-correctness-gaps` owns it).
- Buyer-facing notification.
- Moving the site's `capacity_events` feed or the storefronts' `stage_events` onto
  the eventing system: `replace-polling-with-authenticated-push` and
  `redesign-storefront-stage-events` design onto it.
- Folding introduction delivery into the eventing system (D7).
- A CloudEvents rendering, throttling or digests, and retention by kind or severity
  (Open Questions).

## Decisions

### D1 — One change for failure reporting

Decided by the owner before design: Goal 1's unowned gaps are grouped by theme, and
this change takes failure classification and operator notification together, since a
notification is only as useful as the failure it carries.

### D2 — Operator-relevant state changes are an open set of event kinds

An event is any operator-relevant state change, not only held work: a failed
release, a held repair, and a long-running job that finished are each a kind. A
producer adds a kind with one declaration and one call to record it, and no sink,
route syntax, consumer or configuration schema changes for it.

*Rejected.* The proposal's three conditions, which duplicate the `release_failed`
transition and add a second clock (Context 1). Two fixed triggers — a lease entering
`release_failed` and a repairable teardown attempt — which serve held work and
nothing an operator might want beside it. Every failed job attempt, which notifies
on retries the policy exists to absorb. Classification alone, which leaves the
second gap open against D1.

### D3 — A real failure is classified from Ansible's own result records

The family kit's Ansible distribution ships a notification callback plugin that
needs no enabling. The runner puts its directory on the plugin path per process
through `ANSIBLE_CALLBACK_PLUGINS`, beside whatever stdout callback runs. Ansible
has no setting that adds a directory: the variable replaces the path an
`ansible.cfg`'s `callback_plugins` or Ansible's defaults would give. So the runner
sets it to that path with the plugin's directory in front — the variable's own
value when the environment gives one, else the `callback_plugins` of the
configuration file Ansible reads, resolved as Ansible resolves it, else the
defaults — and an operator's own stdout and notification callbacks still load
(implementation review 23 F1). The runner sets no `ANSIBLE_CALLBACKS_ENABLED`,
which would replace the operator's `callbacks_enabled`. It writes one JSON record
per failed or unreachable task to an owner-only file the runner names per run and
removes when the run ends: host, play,
role, task name, task tags, module, `rc`, `msg`, `stdout`/`stderr`, and whether the
failure was ignored or rescued. Results under `no_log` arrive censored.

The runner hands the records to the executor on the run's outcome, never through the
file (design review 14 F3). `wait_for_playbook` reads and parses the file once the
process has ended and attaches the records, as typed failure records, to the
`AnsibleResult` it returns or the `AnsibleError` it raises; the runner removes the
file in its own `finally`, on success, failure, timeout and cancellation alike, so
the executor reads no file and the task output it holds lives on disk only for the
run. On a timeout or cancellation the records already written are attached, though
`timed_out` and `cancelled` take precedence. The mock runner, which writes no file,
attaches its rule's record to the `AnsibleError` it raises, so a mocked failure
reaches `classify` through the same field.

The executor classifies a failed run in order: the runner's own outcomes
(`timed_out`, `cancelled`); then the generic classes from the last unignored,
unrescued record (`unreachable`, `authentication_refused` for an unreachable record
whose message is an SSH authentication refusal, `task_failed`); then, for
`task_failed`, the domain codec's class. The codec's `is_retryable(message)` becomes
`classify(run, failure) -> FailureClass`, carrying the class and whether it is
retryable. A role declares a domain class by tagging the task that can raise it
(`failure_class:cleanup_refused`); the codec maps tags to classes and may refine
from the record. A failed run with no record is `playbook_error`, its exit code in
the details. The mock runner's rules carry an optional failure record beside
`fail_with`, so a lane's mocked failure is classified through the same `classify`.

The reported envelope, for a refused cleanup:

```json
{
  "code": "cleanup_refused",
  "message": "bm-02: task \"Clean attributable bounded scratch and IPC\" failed: cleanup refused a foreign-owned descendant",
  "retryable": true,
  "details": {"host": "bm-02", "role": "bare-metal-access",
              "task": "Clean attributable bounded scratch and IPC",
              "module": "ansible.builtin.command", "rc": 1,
              "domain_detail": {"error": "Refusal", "message": "cleanup refused a foreign-owned descendant"}}
}
```

The executor redacts `details` as it redacts logs.

*Rejected.* Parsing the printed output, which depends on the stdout callback, the
result format and Ansible's wording — all of which an operator's own `ansible_cfg`
or an upgrade can change — and on a YAML parser the kit keeps out. Roles wrapping
themselves in `block`/`rescue` to print a failure fact, which restructures every
role and still needs another source for an unreachable host, which skips `rescue`.

### D4 — The failure classes and their retry decisions

| Class | Raised by | Retried |
|---|---|---|
| `host_key_refused` | executor, before start | no |
| `not_dispatchable` | engine, before start: no host, unregistered host, unsupported action | no |
| `configuration_refused` | the codec's `prepare`, by a typed error: undecryptable key, missing relay, invalid parameters | no |
| `internal_error` | anything else unanticipated | no |
| `unreachable` | record: the host stopped answering mid-run | yes |
| `authentication_refused` | record: SSH authentication refused | no |
| `timed_out` | runner | yes |
| `task_failed` | record, no domain class | yes |
| `playbook_error` | no record, non-zero exit | no |
| `vm_not_found` | VM codec | no |
| `vm_image_locked` | VM codec | no |
| `vm_address_unknown` | VM codec | no |
| `cleanup_refused` | bare-metal codec, tagged helper tasks in `bounded-reclaim.yml` | yes |

Classes are an open set of strings: the generic ones are constants of
`compute_provisioning_ansible`, the domain ones each codec's. The VM classes are the
VM codec's former pattern list, matched against the failing task's own message in the
record. `cleanup_refused` is the one operator-repairable class: a teardown attempt
failing with it while a retry is scheduled raises `provisioning.teardown_attempt_held`
(D13), so observation 5 keeps its shape and the operator is pushed rather than
polling.

`unreachable` is retried although `TRANSPORT_FAILURES`' docstring said it never
would be: that intent never took effect on a real run, and a host that stops
answering after the pre-start probe proved it reachable under its pinned key is most
often rebooting or briefly partitioned. A refused login is configuration, which a
retry meets again.

*Rejected.* Classes that only inform, which keeps Context 3's defect. Restoring the
written intent whole, which sends every teardown on a blinking host to an operator.

### D5 — The job record keeps its structured failure beside its error

A nullable JSON column `ansible_jobs.failure` holds the latest attempt's
`ProvisioningErrorEnvelope` (`code`, `message`, `retryable`, redacted `details`), and
the job view `JobStatusResponse` gains an optional `failure` carrying it. `error`
keeps its meaning, its text now carrying the classified message
(`Job failed (non-retryable error): bm-02: task "…" failed: …`), so the fulfillment's
and the lease's failure messages become readable with no schema change. The engine's
own refusals carry codes too (D4). One additive compute-provisioning migration; the
contracts package and its client take a minor bump, and a client reading an older
view reads no `failure`.

*Rejected.* Text only, which leaves nothing structured. A table of every attempt's
failure, whose history the events already carry.

### D6 — One eventing system; its envelope

Each service has one eventing system: producers record events, and every outbox,
notification or peer delivery is a consumer of it, never a mechanism of its own per
event type. Its core is generic (D16) and reused by registries, storefronts, the
provisioning service and domains outside the compute family.

Anything a consumer acts on without knowing the kind — routing, filtering,
deduplicating, ordering, correlating — is a first-class envelope field; `details`
holds only what a reader of that kind wants:

```json
{
  "envelope_version": 1,
  "id": "01JDX9R6Q7Z3K2W8P4M5N6B7C8",
  "kind": "provisioning.teardown_attempt_held",
  "kind_version": 1,
  "data_schema": "urn:arkhai:event:provisioning.teardown_attempt_held:1",
  "source": {"service": "compute-provisioning", "instance": "site-west"},
  "sequence": 48213,
  "occurred_at": "2026-11-25T17:42:10Z",
  "severity": "action_required",
  "subject": {"type": "job", "id": "job-9e0d"},
  "related": [{"type": "lease", "id": "cr-7f3a9c"}, {"type": "host", "id": "bm-02"}],
  "correlation_id": "cr-7f3a9c",
  "causation_id": null,
  "attributes": {"offering_mode": "bare_metal", "failure_class": "cleanup_refused", "retries_left": 2},
  "summary": "Reclaim on bm-02 refused a foreign-owned entry; retry 1 of 3 at 17:44 UTC (lease cr-7f3a9c).",
  "details": {"task": "Clean attributable bounded scratch and IPC", "retry_count": 1, "max_retries": 3},
  "extensions": {}
}
```

The evolution rules: envelope fields are only added, as optional; readers ignore
unknown fields and preserve `extensions`; `envelope_version` changes only for an
incompatible envelope change; a kind's `details` follow its `kind_version`, bumped by
an incompatible change; `attributes` hold scalars only. A kind's declaration — its
name, version, default severity, declared attributes and their types, dedup key
(D8), details model and summary renderer — never travels. `details` hold only what
may leave the service, already redacted, since sinks receive the payload.

*Rejected.* A minimal envelope with everything else in `details`, which makes every
router, filter and cursor learn each kind. CloudEvents 1.0 as the stored form, whose
extensions must be flat scalars, pushing `related`, `attributes` and `source` back
into `data`. A CloudEvents rendering at the edge is deferred (Open Questions). An
outbox in the compute family kit only, which another service would have to move. No
store, logs only, which is durable only as far as a deployment's log pipeline.

### D7 — One sink layer serves introductions and events

`kit/delivery`'s sinks take a `Deliverable` — `rendered`, `payload()`, `reference` —
which `DeliveryEvent` satisfies (`reference` is its `obligation_ref`) and an event
satisfies through an adapter (`summary`, the envelope as JSON, `subject` as
`"lease:cr-7f3a9c"`). The built-in sinks read `reference`, and the signing webhook
takes its role and operation from its composition rather than the constants `seller`
and `introduction_delivery`. `kit/delivery` gains the event-sink consumer, which reads
the event stream for a deployment's routes (D8) and hands each event to its sinks,
recording each outcome per destination; it depends on `tools/eventing`, which knows
no sink. Introduction delivery keeps its own at-most-once claim and origin routing. A
third-party sink reading `obligation_ref` keeps working for introductions and fails,
reported by its exception class, for an event; `arkhai-kit-delivery` takes a minor
bump.

*Rejected.* A sink contract and built-in sinks of the event core's own, duplicating
every sink and Apprise's plugin. A webhook and file sink only, which leaves out mail
and push. Introduction delivery as a kind now, whose at-most-once claim, absence of a
counterparty lever, origin routing and buyer-side delivery without a database need a
design of their own.

### D8 — Routes, repeats, retention, and failed delivery

**Routes.** A route is an SQL condition over the event — the envelope's scalar
fields and the declared attributes as columns, `related` as a table — evaluated by
sqlglot's executor and validated over sqlglot's own syntax tree at startup: only
comparisons, `AND`/`OR`/`NOT`, `IN`, `LIKE`, `IS NULL`, and subqueries over
`related`; every column one the envelope has or a matched kind declares; every sink
enabled. Severities are `info` < `warning` < `action_required`, with `severity_rank`
for comparison.

```toml
[Events.routes.long-jobs]
where = "kind = 'provisioning.job_finished' AND duration_seconds >= 1800"
sinks = ["ops-push"]

[Events.routes.host-bm-02]
where = "id IN (SELECT event_id FROM related WHERE type = 'host' AND id = 'bm-02')"
sinks = ["ops-email"]
```

A spike against sqlglot 30.35.0 evaluated these forms, `LIKE`, `IN`, `IS NULL`,
`NOT`, `TRUE` and a correlated `EXISTS` over `related` correctly, named a misspelled
column, and refused a `DROP` by node type.

**Repeats.** A kind declares the envelope fields that identify one occurrence; the
recorder writes an occurrence at most once per key and returns the existing event on
a repeat.

**Order.** The recorder allocates `sequence` from a single counter row it updates in
the producer's transaction (`UPDATE … SET value = value + 1 RETURNING value`), whose
row lock is held until that transaction ends, so no event commits with a lower
sequence than one already visible, and a consumer may always advance its position
past every event it has read (design review 14 F2). On SQLite, which serializes
writers, this costs nothing; on PostgreSQL, transactions that record events queue on
the row from their record call to their commit, negligible at the volumes of this
repository's services. *Rejected:* a free-running sequence whose consumers stop at a
gap until it is proven unused, which needs PostgreSQL's transaction snapshots in a
component meant to be portable, or, by a time horizon, still loses an event whose
transaction outlives it.

**One runner per consumer** (implementation review 23 F2). A named consumer is held
by one runner at a time: a cycle takes the consumer's hold — a holder and an expiry
on the consumer's row — or does nothing while another runner holds it unexpired;
each of its transactions renews the hold and applies nothing once another runner has
taken it; the cycle releases it at its end. Without it, two runs of one consumer
read the same head delivery, both call the destination, and the slower one's outcome
overwrites the faster one's after the faster has delivered the next event — out of
order, and a delivered event shown pending. The hold is kept in the consumer's clock,
as the retry schedule is, since other runners compare it; it is longer than any
delivery attempt, so only a runner stuck past it inside a destination's call can be
superseded, and then the event is delivered again under its `id`, as at-least-once
delivery allows. A runner identity names one process, and one stable across its
restarts takes its own hold back at once; a consumer instance runs one cycle at a
time, so a timer's cycle and a manual one on the same instance are kept apart too.
One mechanism covers registering and reading as well as delivering, at a
throughput of one runner per consumer, ample at these volumes. *Rejected:* a claim
per destination, which lets several runners serve one consumer's destinations at
once but leaves concurrent registering and reading to fail on their keys; leaving
the rule to each deployment (one replica, a process-local lock), which a second
process or a cycle run by hand breaks silently.

**Retention.** By time, configured per table — the events, the delivery state, and
any table a record-time hook writes — and never ahead of a pending destination: an
event is pruned only once past its table's retention and, for each consumer's
destination, delivered, abandoned, or held by a destination that is parked or
retired. A parked destination does not hold an event back, so a destination parked
longer than the events' retention loses, on resume, the events pruned meanwhile; the
owner accepted that risk (design review 14 F1). For the signed lease-end report, what
a resumed peer misses stays readable through the authenticated lease read, from
`lease_end_reports` (D15). A destination is retired when its consumer no longer has
it configured — a storefront peer replaced by another: its undelivered events go to
the finally sink, and it holds nothing back, so a removed peer's pending deliveries
do not keep events forever. *Rejected:* a parked destination holding every event it
would receive until resumed or abandoned, which keeps the resume guarantee whole but
lets a long park grow the events table without bound.

**Failed delivery.** Each consumer has a retry policy. The peer consumers (D15)
retry with backoff without limit and park a destination on "unsupported" until it is
resumed. The event-sink consumer retries each destination with backoff up to a
maximum age, then marks that delivery abandoned and hands the event to the finally
sink, which defaults to the log. Each destination's state shows on a status read.

*Rejected.* No routing, which floods every sink. Routes by kind and severity only,
which cannot select a long job or a host — the fallback had no library served.
Predicates or an expression language of our own, or one adopted that is not SQL (CEL).
Throttling and digests, which nothing shows a need for yet. Retention declared per
kind. Retrying operator sinks forever, which leaves a dead sink silent.

### D9 — Configuration, the delivery worker, and the operator surface

The provisioning service reads an `[Events]` section, shaped as `[Delivery]` is:

```toml
[Events]
retention_days = { events = 30, deliveries = 30, lease_end_reports = 0 }  # 0 keeps
delivery_interval_seconds = 10
sink_max_age_seconds = 86400
finally = "log"

[Events.sinks]
enabled = ["ops-push"]

[Events.sinks.ops-push]
sink = "apprise"
urls = ["ntfy://ntfy.example.net/provisioning"]

[Events.routes.held-work]
where = "severity = 'action_required'"
sinks = ["ops-push"]
```

Routes and sinks are checked against the catalogue at startup; secret sink settings
travel in the Secret overlay. Delivery runs on its own worker,
`EventDeliveryWorker`, with pause and run-cycle controls, which takes over the
outbox drains the lease watchdog runs today. Administrator routes: `GET
/api/v1/events` (filtered by kind, severity, subject or reference), `GET
/api/v1/events/deliveries`, and `POST /api/v1/events/destinations/{name}/resume`,
replacing the uncalled `resume_peer`. The provisioning chart carries `events` in its
public `config`, its schema and drift test updated.

### D10 — `additional_non_retryable_errors` is matched against the failure record

The key keeps the meaning 0.4.0 gave it — a failure whose message contains one of
its substrings is not retried — and now takes effect: it is matched against the
failing task's `msg` and `stderr` in the record and against the classified message.
`TRANSPORT_FAILURES` narrows to the SSH authentication messages that tell
`authentication_refused` apart; `VM_NON_RETRYABLE_FAILURES` becomes the VM codec's
class mapping.

*Rejected.* Retiring the key, churn for a key that still has legitimate uses.

### D11 — Capabilities

New: `eventing`, the standalone component's specification and companion. Modified:
`physical-provisioning`, `site-capacity`, `compute-provisioning-contract`,
`introduction-delivery`. `fulfillment` is not modified (Context 7).

### D12 — Implementation cadence

Two rounds. Round 1, two sessions in parallel on disjoint code: the eventing core
(`tools/eventing` and its tests), and failure classification (the callback plugin and
record, `classify`, both codecs and their tags, the mock's records, the engine's
`failure` column and codes, the contracts bump, D4's retry decisions, D10). Round 2,
two sessions in sequence: the producers and delivery (the provisioning and site kinds
in their transactions, `kit/delivery`'s `Deliverable` and event-sink consumer,
`EventDeliveryWorker`, the routes, configuration and chart), then the move (D15: the
signed-report table, the peer and capacity-release consumers, retiring the old
outboxes and drains, the 0.4.0 data migration, observation 5 pushed). Then closeout.

*Rejected.* One round of four sessions, whose review sees everything at once. Three
rounds, an extra review for two foundations that do not touch.

### D13 — The first kinds

| Kind | Recorded in the transaction of | Severity | Dedup key | Attributes |
|---|---|---|---|---|
| `provisioning.lease_release_failed` | the site's release-failure transition, as a prepared event | `action_required` | lease, release handle | `reason`, `failure_class`, `offering_mode` |
| `provisioning.teardown_attempt_held` | the job engine's retry transition, for a repairable class | `action_required` | job, retry count | `failure_class`, `retry_at`, `retries_left`, `offering_mode` |
| `provisioning.job_finished` | the job engine's terminal transition | `info` succeeded; `warning` failed or cancelled | job | `status`, `action`, `offering_mode`, `duration_seconds`, `failure_class`, `operator_job` |
| `site.lease_ended` | the site's ending transition | `info` | reservation, `transition_key` | `cause`, `source_state` |
| `site.capacity_released` | the site's release | `info` | reservation | `forced`, `after_release_failure` |

The lease lifecycle does not hold the transaction that records `release_failed`: the
site ledger commits it. So the site's failing-transition method takes an optional
prepared event, which the ledger records in that transaction; the lifecycle prepares
`provisioning.lease_release_failed` beforehand from the reason, the message, the
release handle, and the latest teardown job and its class, read from the job
authority. A refused stale transition writes nothing, and no event exists. The site
records the prepared event without knowing its kind. The site's recorder is injected
into its ledger, as its lease-end effect is today.

A recovery is no kind of its own: `site.capacity_released` with
`after_release_failure` tells an operator that a lease they held was released, forced
or after a retry-release. `site.lease_ended` keeps 0.4.0's payload as its `details`
at `kind_version` 1.

*Rejected.* Held work and the moved kinds alone, which leaves out the long-running
job. Every failed attempt, host readiness, relay events and a lease handed to an
operator now: each is one declaration later, and readiness records no transition
today.

### D14 — This change moves the lease-end events and both outboxes onto the eventing system

The site's lease-end events, `lease_end_report_outbox` and
`capacity_release_callback_outbox` become producers and consumers of the eventing
system in this change, rather than in `replace-polling-with-authenticated-push`,
which is not near. That change and `redesign-storefront-stage-events` design their
event logs onto this system; their rows say so.

*Rejected.* Leaving the move to `replace-polling-with-authenticated-push`, or to a
follow-up change, which keeps the per-event mechanisms beside the new one. A
prerequisite change for the eventing system, which halts this design and holds
classification, which needs no events, behind it.

### D15 — Evidence stays domain state; delivery becomes consumers

The site keeps its immutable lease-end record, the state `site-capacity` requires,
and records `site.lease_ended` with it in the same transaction. That kind's
record-time hook signs the statement and writes it to `lease_end_reports` — the
signed column of today's outbox without its delivery columns — which the
authenticated lease read serves, retained under its own setting (unlimited by
default). Delivery to the storefront is a consumer of `site.lease_ended` with one
destination per configured peer: a peer answering "unsupported" parks its
destination until it is resumed, and a newly configured peer is a new destination
starting at the current position, so an old event never reaches a later peer, and
the replaced peer's destination is retired (D8).
`capacity_release_callback_outbox` is retired for a consumer of
`site.capacity_released`, now recorded in the release's own transaction rather than
reserved in a session before it. The lease watchdog no longer drains anything.

One provisioning-service migration carries 0.4.0's state: each undelivered
`lease_end_report_outbox` row becomes a `site.lease_ended` event under its original
`event_id`, in `created_at` order, its pending or parked delivery state, attempt
count and last error carried; every row's signed report moves to
`lease_end_reports`; each undelivered `capacity_release_callback_outbox` row becomes a
pending `site.capacity_released` delivery; delivered rows need no event. The signed
report and the callback keep their wire forms. The migration is one-time, so no
compatibility path is kept.

*Rejected.* Evidence in the event stream, which needs retention by kind (D8) or none.

### D16 — The event core is built as a standalone component, using sqlglot

No library covers per-destination state, record-time hooks and SQLite.
`eventsourcing` has a notification log and atomic tracking records on SQLite and
PostgreSQL, but events of event-sourced aggregates, session sharing through a
process-global setting, no per-destination state, and an append-only design pruning
works against. The outbox libraries found (`outboxed`, `outbox-core`, `python-cqrs`,
`outbox-streaming`, `factbus`) are PostgreSQL-only or broker-bound.

So the core is built as `tools/eventing`, a standalone component under the rule of
`package-layers.md`: no internal package, no market concept, its boundary held by a
structure test of its own, ready to lift into a repository of its own. It depends on
the standard library, SQLAlchemy, pydantic and sqlglot, and holds the envelope, kind
declarations and the catalogue, the recorder with dedup keys and record-time hooks,
the tables, consumers with cursors, per-destination state, park/resume and the
finally sink, sqlglot routes, per-table time pruning, reads by reference, and a
framework-free read and status service. It cannot depend on `kit/schema-migrations`,
so it supplies its table metadata and one DDL step per schema version, which each
service's migration chain applies. The market's kinds, the signed lease-end consumer,
the capacity-release consumer and `kit/delivery`'s event-sink consumer stay on the
market side.

*Rejected.* Adopting `eventsourcing` and building around it, which keeps more than
half the work and a model that does not fit. A small outbox library, none supporting
SQLite. An external broker, which adds infrastructure and still needs an outbox.

## Implementation cadence

D12: round 1, two sessions in parallel — the eventing core; failure classification.
Round 2, two sessions in sequence — producers and delivery; the move. Then closeout.

## Risks / Trade-offs

- **The change spans four areas** (eventing, classification, delivery, peer
  delivery). The cadence reviews each foundation before the integration, and the move
  with its migration last.
- **sqlglot's executor is not built for speed.** Routes run per event per route at
  provisioning's volumes; a deployment needing more evaluates routes in the database
  by transpiling them, which sqlglot also does.
- **A third-party sink reading `obligation_ref`** fails for events until it reads
  `reference`, reported as a sink failure.
- **The callback plugin depends on Ansible's callback API**, stable across
  `ansible-core` releases; the runner enables it whatever an operator configures.
- **A destination parked past the events' retention** loses the events pruned while
  it was parked; resuming delivers only what is retained. Accepted by the owner (D8);
  the signed lease-end reports a resumed peer misses stay readable through the
  authenticated lease read.
- **Event recording serializes on the sequence counter** on PostgreSQL (D8). A
  service recording events at rates where that queue is measurable revisits the
  allocation.
- **`cleanup_refused`'s retry window** is about seven minutes at the defaults, short
  for a person; the push narrows it (Open Questions).

## Open Questions

- **A CloudEvents mapping and rendering at the webhook sink.** Revisit when a
  definite receiver expects CloudEvents.
- **Throttling and digests per route.** Revisit when an operator reports a burst a
  destination cannot absorb.
- **Retention by severity or kind.** Revisit when higher-severity events must outlive
  the per-table window.
- **The retry window of an operator-repairable class.** Revisit if operators report
  missing the window before a cleanup refusal exhausts its retries.
- **An event when a destination's delivery is abandoned, routed to the other sinks.**
  The finally sink covers it today; revisit when the log is not watched.
