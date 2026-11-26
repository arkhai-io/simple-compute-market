# Physical Provisioning Architecture

The [normative contract](spec.md) defines executor dispatch, jobs, and release. This document explains how the compute service composes generic lifecycle machinery with domain adapters.

## Compute composition

The compute service owns transport, persistence, job execution infrastructure, lease lifecycle, and registration of concrete adapter bundles. Domain adapters own infrastructure-specific request validation, invocation, result interpretation, and credentials.

```text
compute service composition
    ├── generic jobs and lease lifecycle
    ├── site and resource-pool authorities
    ├── fulfillment scheduler/registry
    └── VM, bare-metal, or future adapter bundles
```

The offering-mode-neutral composition root lets generic services dispatch by recorded executor or provider identity without importing a concrete domain implementation.

The mock mechanism is a worked instance of the five-piece route pattern ([`docs/guidance/engineering/implementation.md`, "Route contracts and their HTTP binding"](../../../docs/guidance/engineering/implementation.md#route-contracts-and-their-http-binding)) in which the family owns every piece but the binding's location. `compute_provisioning_contracts.mock_rules` holds the route-contract template, `MockRouteMount`, a path prefix and an operation-name prefix whose `route_declarations()` yields the rule add, list, delete, and resume routes and the evaluate-job route, and the wire models those routes answer with (`MockRuleAdded`, `MockRuleView`, `MockRuleDeleted`, `MockRuleResumed`, `MockJobEvaluation`, and the request `MockRuleCreate`). The family kit's `MockRuleRouteService` (`compute_provisioning.jobs.executor_mock`) answers with them, and `compute_provisioning_client`'s `MockRuleClient` and `SyncMockRuleClient` sign each call from a mount's declarations and return the same models. A domain states only its mount: VM's is `VM_MOCK_ROUTE_MOUNT`, `("/test", "provisioning_test")`, in `vm_provisioning_operator.routes`; bare metal's two values, `"/test/bare-metal"` and `"provisioning_test_bare_metal"`, live in `arkhai_bare_metal.provisioning_routes`, so `arkhai-bare-metal` keeps no compute dependency and its adapter builds the mount. Each adapter binds the route service under its mount's prefix and contributes the mount's declarations to the service's table. The evaluate-job request stays each domain's, since its fields are the domain's job parameters. A further compute domain mounts the mechanism by stating its two values.

The service's database holds VM's tables, so its metadata (`db/database.py`) maps them and its one chain (`db/migrations.py`) composes the VM adapter's baseline, `vm_provisioning_adapter.migrations.BASELINE`, beside the baselines `kit/resource-pools`, `kit/site`, `kit/fulfillment`, the family kit's hosts, jobs and relays, and the service's own tables export, in foreign-key order, followed by the migrations after the v0.3.0 baseline. `deployment-state`'s "Service-owned migration history" still gives the migration command only its database; nothing injects VM's schema. A single chain is adequate while one compute domain owns provisioning-side tables. When a second domain needs its own, its adapter exports its baseline and migrations and the service's chain composes them in an order the contributions declare.

The resource-pool projection a site serves is neutral, and a domain that publishes more — a view of a whole machine it sells, or a pool's configured defaults — contributes an `InventoryViewProjection` from `compute_provisioning.inventory_views`, which owns the protocol and its composer. The service merges what each projection returns and never names a domain's view, attribute, or provider configuration. A resource view is built with its pool's context, an `InventoryPoolContext` of pool ID, provider, and the pool's resolved declarations, because what a view may carry depends on them: a bare-metal view carries its delivery terms only where the pool's backing delegate passes them through (see the [resource-pool management architecture](../resource-pool-management/architecture.md#advertisement-delivery-and-backing)). The provisioning service, as the composition root, reads the pool rows in its own resource pass, resolves each pool once through the shared resolver, and hands each declaration its pool's context, interpreting none of it; the pool pass reads raw tags and the provider from the same column, so the two passes cannot drift on a pool's provider. A stored pool whose declarations do not resolve, which startup refuses and no write path produces, gives its members no context, so they project with no views and no problems, and the service logs a warning. The declarations the service hands the composer are the site ledger's offered read, whose `enabled` already says whether the site offers each one, so a view that reports availability, such as bare metal's, reports a declaration with no usable host as unavailable without the service or the view reading a host (see the [site-capacity architecture](../site-capacity/architecture.md#declared-capacity-and-connection-identity)). Building the context is compute-family work, so it sits at the contributed-view seam and nothing above the compute family learns of it: `kit/site` copies the per-resource result into its projection without reading it, and `kit/resource-pools` and core do not see it.

A contributed projection never raises on a declaration's content. Declarations reach the site over its API from any client, and one a view builder could not handle would otherwise fail the site's whole resource-pool projection, every pool and every domain with it. `resource_views` returns a `ResourceViews` of the views it built and, per declared view it could not build, the reasons, which the projected resource carries as `publication_view_problems` keyed by view identifier. A backed bare-metal declaration naming no host or no access methods, a missing or invalid `allocation_mode` or `physical_host_id`, and a private-looking capacity or capability key are such cases. A storefront reads a resource with problems as an unreadable declaration and holds its listing (see the [storefront publication architecture](../storefront-publication/architecture.md#reconciliation)). Refusing a malformed attribute when the declaration is written was rejected: its backing-dependent rules need the pool's backing, which the site's pool-facts port does not carry, so a write-time check would be partial and the projection would still have to tolerate what it missed.

## Registration boundary

Adapters register executor actions and FulfillmentProviders explicitly. Duplicate identities fail during startup because silent replacement would make persisted records execute under a different implementation. Provider and executor registration remain independent: fulfillment create/status/teardown and lease-release actions have different contracts and may evolve separately.

## Durable jobs, transient workers

A persisted job gives accepted work a durable identity, status, request snapshot, result, and diagnostic history. The in-process queue is only the execution mechanism. It does not become the database, retry authority, or provider policy engine.

This distinction makes accepted work observable while avoiding false recovery promises. A process restart does not by itself prove that every queued or running action is safely resumed; recovery must be explicit where required.

The job record is also where delivered credentials live. A job's executor reports the credentials it generated as `CredentialEnvelope`s, and the job authority stores them with the transition that reports them. The fulfillment aggregate, its provider metadata, and the fulfillment result hold none: a result query for an active fulfillment reads its create job's credentials from the job record each time. Keeping them there is a necessity, not a cache — the create job generates VM tenant credentials on the host, and nothing can read them back from it afterwards.

A job's result is read from the fact its role prints, and one reader in the shared Ansible kit, `compute_provisioning_ansible.read_fact`, reads it for every compute domain. Under the packaged configuration's YAML callback format a role's `debug: var:` fact prints as YAML, which the kit does not parse, beside the JSON document its `debug: msg:` task prints as a literal block; under the JSON format the `var:` form is JSON. The reader takes either, reads each `msg:` block alone so it never runs into a later task's output, and keeps only a document naming the action the job expects. Judging that document belongs to the domain's codec, which owns what a result means: it yields delivery evidence only when the fact names the job's own action, target, tenant account (and, for bare metal, machine), and success. That guards against adopting the wrong document from one run's output, not against provenance across runs. A bare-metal reclaim's fact is checked the same way but decides nothing: a fact that does not match is recorded as a mismatch for an operator, and the reclaim job's status alone decides its teardown.

Two limits follow. An operator's VM password reset runs as its own job, whose new credentials are stored against that job; the fulfillment result still reads the create job's, so after a reset it delivers the superseded password. And the envelopes are stored as plain JSON, unlike a relay's admission token, which is encrypted with the deployment's key, and nothing deletes job rows; anyone who can read the provisioning database can read every credential a job has reported, including those of workloads since torn down.

## Failure classification

A failed playbook run is classified from Ansible's own account of each failed task, never from the run's printed output. The shared Ansible kit ships a notification callback, `compute_provisioning_ansible/callback_plugins/arkhai_failure_records.py`, which appends one JSON record per failed or unreachable task to the file `ARKHAI_FAILURE_RECORDS_PATH` names: its host, play, role, task name, tags, resolved module, `rc`, `msg`, `stdout` and `stderr` (each bounded to 8 KiB, the message keeping its start and the output its end), whether the host was unreachable, and whether the failure was ignored (`ignore_errors`, or `ignore_unreachable`) or rescued (the task sits in the `block` of an enclosing block that has a `rescue`). A result under `no_log` arrives censored, so its record says only that it was hidden. Parsing the printed output was rejected: it depends on the stdout callback, the result format and Ansible's wording, any of which an operator's own `ansible_cfg` or an Ansible upgrade can change, and on a YAML parser the kit keeps out. So was having roles wrap themselves in `block`/`rescue` to print a failure fact: it restructures every role and still needs another source for an unreachable host, which skips `rescue`.

The callback is a notification callback that needs no enabling, so it runs beside whatever stdout callback and enabled callbacks an operator's configuration names. Ansible has no setting that adds a callback directory: `ANSIBLE_CALLBACK_PLUGINS` replaces the search path an `ansible.cfg`'s `callback_plugins` or Ansible's defaults would give. The runner therefore sets it, per process, to the path Ansible would otherwise search with the callback's directory in front — the variable's own value when the environment gives one; else the `callback_plugins` of the configuration file Ansible reads, found in Ansible's order (`ANSIBLE_CONFIG`, the working directory's, `~/.ansible.cfg`, `/etc/ansible/ansible.cfg`) and resolved as Ansible resolves it, a relative entry from the file's directory; else Ansible's defaults under `ANSIBLE_HOME` or the configuration's `home` — so a stdout or notification callback an operator loads from a directory of their own is still found. It sets no `ANSIBLE_CALLBACKS_ENABLED`, which outranks an `ansible.cfg`'s `callbacks_enabled` and would drop the callbacks the operator's configuration enables; a callback that needs no enabling loads from the plugin path alone.

The runner creates the records file owner-only under a random name before the playbook starts; the callback only appends to it and never creates it. `wait_for_playbook` reads the file once the process has ended and attaches the records, as `FailureRecord`s, to the `AnsibleResult` it returns or the `AnsibleError` it raises, with the run's outcome (`failed`, `timed_out`, `cancelled`, or `error` where the runner could not run or watch the playbook) and exit status; its own `finally` removes the file on success, failure, timeout and cancellation alike, and a spawn that fails removes it at once. The executor reads no file: it classifies from the records it is handed, and the task output they hold lives on disk only for the run. The mock runner writes no file and attaches its rule's `failure_record`, so a lane's mocked failure is classified through the same path; a mocked failure with no record is a `playbook_error`, as a real playbook that recorded no failed task is.

The executor classifies a failed run in order:

1. the runner's own outcome: `timed_out`, then `cancelled`;
2. else the last record neither ignored nor rescued: an unreachable host is `authentication_refused` when its message is an SSH authentication refusal (`TRANSPORT_FAILURES`: "Permission denied", "Authentication failed", "Too many authentication failures") and `unreachable` otherwise; a failed task is what the domain's codec classifies it as;
3. else, with no deciding record, `playbook_error`, its exit status in the details, or `internal_error` where the runner could not run or watch the playbook.

A codec's `classify(run, failure)` returns a `FailureClass`: its code, whether it is retryable, and optionally a summary replacing the record's `msg` in the message and a `domain_detail` for the details. A role declares a domain class by tagging the task that can raise it, `failure_class:<class>`; Ansible never selects tasks by these tags, since the runner passes no `--tags`. The bare-metal codec maps `failure_class:cleanup_refused`, carried by the three tasks of `bounded-reclaim.yml` that run the working-data helper, to `cleanup_refused`, refined from the helper's structured refusal, the last line of its standard error as `{"version": 1, "error": …, "message": …}`. The VM codec matches the failing task's `msg`, then its `stderr`, against `VM_FAILURE_CLASSES`. A task failure no domain class applies to is `task_failed`. The failure's message names the host, the task and what failed (`bm-02: task "…" failed: …`); its details are the record's host, task, play, role, module and `rc` with the codec's `domain_detail`, never its output, which the job's logs keep. Message and details are redacted as logs are, a key naming a secret field replaced whole.

| Class | Raised by | Retried |
|---|---|---|
| `host_key_refused` | the executor, before the start, for a host with no pin or presenting another key ([The host registry owns the connection](#the-host-registry-owns-the-connection)) | no |
| `not_dispatchable` | the engine, before any executor runs: no host, an unregistered host, an unsupported action | no |
| `configuration_refused` | the engine, for a typed refusal (`ConfigurationRefusedError`) of the codec's preparation, the variables, the inventory target, an undecryptable key or an unusable relay | no |
| `internal_error` | the engine, for anything else an executor raises; the executor, for a run the runner could not run or watch that recorded no failure | no |
| `timed_out` | the runner, a playbook past `ansible_timeout_seconds` | yes |
| `cancelled` | the runner, a run stopped through its handle | no |
| `unreachable` | a record: the host stopped answering during the run | yes |
| `authentication_refused` | a record: the host refused the SSH login | no |
| `task_failed` | a record no domain class applies to | yes |
| `playbook_error` | no record, a non-zero exit | no |
| `vm_not_found`, `vm_image_locked`, `vm_address_unknown` | the VM codec | no |
| `cleanup_refused` | the bare-metal codec, from the tagged helper tasks | yes |

Classes are an open set of strings: the generic ones are constants of `compute_provisioning_ansible.failures` and `compute_provisioning.jobs`, a domain's are its codec's. Whatever the class, a failure matching one of the operator's `additional_non_retryable_errors` is not retried ([configuration](configuration.md#non-retryable-failure-messages)). A host that stops answering mid-run is retried: the probe before the start proved it reachable under its pinned key, so one that stops answering afterwards is most often rebooting or briefly partitioned, and refusing the retry would send every teardown on a host that blinked to an operator. A refused login is not: it is configuration — a key or user the host does not accept — which a retry meets again.

The job keeps its structured failure beside its error. `ansible_jobs.failure` holds the latest failed attempt's envelope — `code`, `message`, `retryable` and redacted `details` — written on the retry and terminal transitions, cleared with `error` on success and kept on cancellation, and the job view's `failure` carries it. `error` keeps its form, its text carrying the classified message (`Attempt 1 failed: bm-02: task "…" failed: …` while a retry is scheduled, `Job failed (max retries exceeded): …` once none is), so the fulfillment's and the lease's failure messages read the classified failure with no schema of their own. Only the latest attempt's failure is kept, each failed attempt overwriting the one before.

`cleanup_refused` is the one operator-repairable class: a reclaim refusing a foreign-owned entry waits on a person removing it, and is retried so the same job completes once they have. The bare-metal adapter names it in `OPERATOR_REPAIRABLE_FAILURES`, the service hands that set to the job engine, and a teardown attempt failing with it while a retry is scheduled records `provisioning.teardown_attempt_held`, so an operator is told of the hold within the retry window — about seven minutes at the default backoff — rather than finding it by polling the job.

## Operator events

The provisioning service records the site's event kinds and compute provisioning's in its own database, through one recorder its site ledger, job engine and lease lifecycle share, each in the transaction of the change it reports ([`operator-events.md`](../../../docs/guidance/repository/operator-events.md)); the kinds are the specification's requirement "Compute provisioning records operator-relevant events" and [`site-capacity`'s](../site-capacity/spec.md). The event store is `tools/eventing` ([`eventing`'s architecture](../eventing/architecture.md)), its tables built by the service's own chain from the component's schema step.

`EventDeliveryWorker` runs three consumers, then prunes, on its own timer, with a pause and a manual cycle that runs the same production cycle (`POST /api/v1/system/event-delivery/{pause,resume,run-cycle}`): `event-sinks`, delivering what the deployment's routes select to the sinks `[Events.sinks]` enables ([configuration](configuration.md#operator-events)), and the storefront peer's `lease-end-reports` and `capacity-released` ([Lease-end report delivery](#lease-end-report-delivery)). It holds each consumer under a runner name for its site, `compute-provisioning:<site>`, stable across restarts, since one process serves a site's database: a restarted service takes its own holds back at once. A route, sink or finally sink the eventing component refuses refuses the service's start, since the worker is composed before it serves. The administrator reads events through `GET /api/v1/events`, filtered by kind, severity, subject or related reference, each destination's delivery state through `GET /api/v1/events/deliveries`, and resumes a parked destination through `POST /api/v1/events/destinations/{name}/resume`, all through route contracts and the family client's typed methods.

## Selected-resource execution

Concrete providers operate on the Settlement Resource selected by fulfillment scheduling. The VM Ansible adapter resolves pool/provider configuration, validates it, and snapshots prepared inputs at dispatch. Administrative pool edits therefore affect later operations rather than rewriting the accepted execution.

Operational inventory is authoritative service state, not a checked-in Ansible inventory. A host definitions document or an INI submitted to the import route may register hosts, and an adapter may render transient execution inventory, but operator mutations and job-history references remain tied to persisted resources.

### Bare-metal storefront pull boundary

The bare-metal storefront is a client of the accepted POOLS-7 scheduling and fulfillment contracts, not a second job repository or convergence worker. It derives one `SettlementResource` request from the immutable accepted listing/site/Physical Resource and agreed bare-metal terms, submits it to the provisioning authority bound to that site, and persists only returned reservation, settlement-resource, and fulfillment correlations.

The storefront's seller table binds payment, Alkahest and contact stages;
its purchase table binds payment only. A payment or Alkahest seller persists one
`bare_metal.settlement-evidence.v1` payload in negotiation-keyed
`bare_metal_settlement_records`, bound to the exact Agreement digest and an
immutable established reference. Verified source/delivery cannot be replaced.
Physical lifecycle correlations, progress and private results remain separate.
A contact-exchange deal records no settlement evidence: it completes by its
introduction, whose reveal is the contact-exchange kit's own record, and it has
no settlement or fulfillment to load. No escrow row or payment chain-name
sentinel is alternative authority.

Common begin, recovery/status, access/result and teardown load verified evidence
through the accepted entry. Payment rechecks the mandate and trusted signed
receipt. Alkahest requires an active journal (pending reclaim/collection and
ready mechanism status) and rechecks chain evidence against the persisted
proposal, amount/duration, selected chain and exact obligation index, on every
drive of a deal. Local materialization is adoption history, not current chain
authority.

Delivery enters through core's `fulfill_domain` hook, as VM's does: payment
settle, the Alkahest ready step, the delivery re-drive's `redeliver` and a status
read each call the fulfillment service's `deliver`, which revalidates the settlement
through the accepted entry and builds a `StorefrontFulfillmentContext`, and the
registered hook builds the compute delivery path from the clients in `ports` and
the storefront's lifecycle in `domain_input`, refusing before any call when the
lifecycle is absent. There is therefore one registered entry, and it always admits
and commits the Agreement's window, and core's identity check runs on every
bare-metal delivery. No core type changed for this: `ports` and the opaque
`domain_input` already carry what the hook needs. The hook drives under the deal's
lock, drives the physical end after releasing it, and returns the lifecycle row as
`domain_result` with a public result naming the outcome, its fulfilled, deferred
or failed disposition, and whether the deal is available.

`bare_metal_fulfillment_lifecycle` is the path's progress port for bare metal
([compute delivery](../compute-delivery/architecture.md)), its step read from the
activation instant, the fulfillment, a recorded `dispatch` state, then a
reservation; its row is created only while the settlement record is verified, in
the admission's transaction, so a seller refund that won the start refuses it. The
domain port reserves the whole-machine claim with `escrow_uid` beside the
`:settlement` placement key, so recovery replays by key rather than scanning the
site's reservations, and schedules and records the assigned resource before
building the materialization over the Agreement window, since the request names
that resource. The `delivery-recovery` loop drives waiting and pending deals again
through the compute family's re-drive
([compute delivery, "Dispatch and recovery"](../compute-delivery/architecture.md#dispatch-and-recovery)):
it lists the deals whose lifecycle row shows a delivery started and not finished,
skips one whose lock is held, re-checks its settlement through the settlement
service's `verified_evidence`, and drives it through `deliver`. A status read
drives a deal whose fulfillment is active and not yet available before answering,
so the administrator's settle wait and a buyer's status read reach availability;
the access read does not drive, reaching no payment authority, and goes through the
path's access check. `access` and `status` are declared credential-capable.
Migration `bare-metal-storefront-0016-delivery-activation` adds the activation
column, marks a row an earlier storefront left with a saved materialization and no
fulfillment as dispatched, so it is adopted rather than released, and removes
`host`, `port` and `username` from every recorded replay body whose `method` is
`ssh`.

The scheduler's recorded resource kind, provider, and executor selection remain authoritative for begin, status, result, and teardown. The storefront never substitutes a process-global provisioner, buyer-supplied URL, or guessed adapter. It pulls normalized status and the versioned result envelope through the same recorded site client after restart; provisioning remains the authority for jobs, provider metadata, execution credentials, and teardown convergence.

### Signed payment receipt boundary

Arkhai payment acceptance stores the seller-derived mandate in shared negotiation `settlement_data` beside exact Agreement bytes. The seller verifies the service-signed receipt against that mandate before selected-site reservation, scheduling, or fulfillment. Pending payment cannot create access or renew capacity. Equivalent retries reuse the accepted site, durable reservation, and fulfillment identity; recovery rechecks receipt evidence before physical effects.

VM retains negotiation-scoped settlement evidence and independent delivery
progress/convergence claims without a chain escrow or payment obligation.
Bare metal retains independent evidence and its selected-site lifecycle/public
result. Neither common delivery path dispatches from a mechanism ID. Lease expiry and revocation use provisioning-owned teardown convergence; capacity stays quarantined until authoritative release, independently of payment hold release or refund.

### Explicit storefront database reset

Incompatible disposable bare-metal storefront databases require explicit reset
while effects and recovery are quiesced. Confirm database ownership, use a new
owned path or remove only that disposable database, bootstrap current migrations,
then republish and renegotiate. Old receipt-only evidence and escrow-named
lifecycle shapes fail startup; there is no silent copy/adoption or sentinel
fallback. Rebuild `.dist` and reinstall consumers before use. Controlled HTTP
settlement/contact entries use fresh pytest-owned SQLite and clean it afterward;
this is not live hardware access/revocation qualification.

## Lease-end report delivery

The site forms immutable `lease_ended` evidence when it intends to end a lease,
before teardown. Explicit termination, expiry, direct release without dispatch,
release failure and force release all have durable event identity. Payloads bind
reservation/site, effective instant, cause/source state, caller/failure reason
and applicable deadline phase. The ledger's ending transition records the
`site.lease_ended` event with that record, keyed on the reservation and the
transition, so a repeated transition records neither again and every delivery
reuses the original event.

**The evidence is domain state.** `site.lease_ended`'s record-time hook, which
the service's event catalogue attaches, signs the lease end's statement with the
site's service identity and writes it to `lease_end_reports` in the ending
transaction, so the end, its event and its signed report commit or roll back
together. The compute wire codec frames canonical payload bytes under
`arkhai.site.lease-ended.v1`, and the table keeps the original signed wrapper,
so every delivery and `LeaseView.end_reports`, the authenticated lease read,
return the same bytes after a signer changes. The table has a retention of its
own, `retention_days.lease_end_reports`, unlimited by default
([configuration](configuration.md#operator-events)), and a report is kept
while its event is, whatever that retention, so a delivery never finds its
report pruned. Keeping the evidence in the event stream instead was rejected:
events are retained by time, whatever their kind, while a report a storefront
missed must stay readable after its event has gone.

**Delivery is a consumer.** The `lease-end-reports` consumer delivers each
`site.lease_ended` event's stored report to the owning storefront under a
request identity derived from the event's, so a lost acknowledgement is retried
as the same request, with a backoff doubling from 10 seconds to an hour and no
limit. It holds one destination per configured storefront peer, named for the
peer's URL — `storefront@` and its host, port and path, each `/` of the path
written `~` and any credentials left out — so the name is one segment of the
resume route's path. A peer answering 404, 405, 501 or an explicit
`unsupported` parks its destination until an administrator resumes it through
`POST /api/v1/events/destinations/{name}/resume`; resumed, it receives in order
the reports it missed whose events are still retained, and an older one stays
readable through the lease read. Any other failure is retried, and a report the
table does not hold is abandoned to the finally sink, since no retry can send
it. A peer configured beside or in place of another is a destination of its own that
starts at the latest committed event, so a changed peer cannot redirect old
events: a report recorded before it never reaches it. A first peer, the
consumer's first destination, by contrast receives what was recorded since the
consumer last read, so the first report after an install, or after an upgrade
that moved no undelivered report, reaches it. A peer whose undelivered reports
the upgrade moved already has its destination, which keeps receiving them and
every later report; a peer configured in its place is a change of peer, as
above. A report from a restart's window
sent to a first peer that does not own its reservation can park that peer until
it is resumed. The destination of a peer the configuration does not name is retired, and
its undelivered reports, those the consumer had not yet read included, go to
the finally sink, the log, while staying readable through the lease read.

**The capacity-released callback is a consumer too.** The site records
`site.capacity_released` in the transaction of the release that frees a
reservation's capacity, its `lease_lifecycle` attribute marking the releases the
lease lifecycle makes through the site authority port. The `capacity-released`
consumer sends the signed capacity-released callback for those alone; a
release a caller of the site's own release route asks for draws none. Its one destination, `storefront`, is
whichever URL configures the storefront, so a pending callback follows the
storefront to another URL, and its request identity is derived from the
reservation and its release instant. It retries with backoff and no limit. A
storefront refusing one callback outright — 400, 404 or 409, for a reservation
it does not hold — has that callback abandoned to the finally sink at once, and
the next follows, so one refusal holds back nothing. The destination is
registered whether or not a storefront URL is configured: while none is, its
delivery fails and stays pending, and a callback recorded or migrated meanwhile
is delivered once one is.

**When deliveries leave.** Terminate, retry-release, force-release and a lease
watchdog cycle that made a transition each run the two storefront consumers'
cycles through the event delivery worker once their transitions have committed
and before they return, so a report or callback leaves on the request or
stepped cycle that recorded it; a failure there is logged and never fails the
command. Retries, and events recorded on any other path, are delivered on the
worker's timer. The lease watchdog delivers nothing of its own. Each consumer
runs one cycle at a time, a delivery asked for during its cycle waiting for it,
and none waits for another consumer's deliveries or for pruning.

**The upgrade from the storefront outboxes.** Migration
`20261126_002_storefront_outboxes_to_event_store`, after the event store's
schema step `eventing_0001`, carries the undelivered rows of the two outboxes
marketplace 0.4.0 kept, `lease_end_report_outbox` and
`capacity_release_callback_outbox`, into the event store, then drops both.
Every signed report is copied to `lease_end_reports`. Each undelivered report
becomes a `site.lease_ended` event under its original event identity, in
creation order, written as the recorder writes one, its delivery pending to the
peer it was signed for with its attempts and last error, and that peer's
destination parked when the peer had parked its reports; a report for a peer the
configuration does not name is retired to the finally sink at the first cycle, never
redirected. Each undelivered callback of a released or force-released
reservation becomes a pending `site.capacity_released` delivery to
`storefront`, marked `lease_lifecycle`; a callback of a reservation never
released is dropped, since none was owed. Delivered rows need no event. Both
storefront consumers are registered past every event it writes. A report naming no
recorded lease end, or a callback whose release records no instant or lease
end, refuses the migration, which then writes nothing. The signed report and
the callback keep their wire forms, and the migration runs once, so no
compatibility path is kept.

VM/bare-metal ingress verifies the configured selected-site binding, retains the
exact wrapper idempotently, and records source/actor/cause in end service. Buyer
lifecycle reads expose that same evidence, not a storefront re-signing of it.
The site knows no payment transaction, dispute policy or payee credential.
Seller end classification/filing belongs above provisioning.

Due delivery ends terminate immediately; future ends truncate rather than extend
the accepted horizon at second precision. Pre-dispatch release stays behind the
site's guard; create-in-flight is adopted before termination. The intended-end
report has its own acknowledgement, distinct from the capacity-released
callback's. A report, failed release or queued teardown proves no hardware stop and
returns no capacity; normal release remains proof-driven below.

## Proof-driven release

Release is proof-driven and split across two cooperating owners. Lease lifecycle decides when a reservation should release and owns the final capacity-return decision; it never dispatches a teardown itself. Fulfillment convergence (see `openspec/specs/fulfillment/spec.md#fulfillment-convergence-worker`) owns teardown dispatch, provider polling, and recovery through `torn_down`/`teardown_failed`. One provider-neutral release executor and one status port connect the two for every offering mode: release begins the fulfillment aggregate's teardown, and release status reads the aggregate's teardown state. The site authority releases capacity only after the fulfillment aggregate reaches `torn_down`, or an operator explicitly force-releases. Failure retains the reservation and records a retryable release state (`teardown_failed`), which convergence requeues without an operator prompting it. An explicit force release is an operator override with distinct audit meaning, not fabricated proof of executor success.

A teardown's job is adopted, not run again, unless its record proves its execution never started. The job engine records two instants on every job from the process's time source: `execution_started_at`, committed when the executor reports, immediately before it starts anything that can act on the host, that the execution is starting — the Ansible executor before it spawns the playbook — and `finished_at`, stamped on every terminal transition. The start's report raises when it cannot be committed or the job has left `running`, so no attempt acts on a host without a recorded start and a job cancelled since its claim spawns nothing; a retry keeps the first instant. A job's execution never started when it is `failed`, not `cancelled`, and records `finished_at` but neither a start nor a handle: it was refused before anything acted on its host — by the engine, or by its executor's codec, inventory, host key or relay — so running it again does exactly what it should have. A job with no `finished_at` was finished by an engine that recorded the handle only after spawning the playbook, so a missing handle there proves nothing, and it is never so classified; a recorded start without a handle counts as started. The job view carries both instants.

The Ansible executor checks a host's key against its pin ([The host registry owns the connection](#the-host-registry-owns-the-connection)) before it reports the start, so a host presenting another key, or one with no pin, fails its job as never started, unretried: a teardown so refused runs again once the operator settles the key, by the rerun rule below, and nothing touched the host meanwhile. A key that changes between that check and the playbook fails the playbook as started, and an operator handles it, as for any started teardown.

The job-backed provider's `dispatch_teardown` adopts the reservation's latest teardown job. When that job's execution never started and a rerun is ready, it submits rerun *n* under `"{reservation}:teardown:rerun-{n}"`, *n* counting the teardown jobs already bound, from the frozen prepared teardown operation's parameters; the first teardown is `"{reservation}:teardown"`. A crash between submitting and recording finds the rerun as the latest job and adopts it, and concurrent dispatches collapse on the job identity. Rerun *n* is ready once the previous job has been finished for the job retry policy's delay after *n* − 1 retries, up to `teardown_rerun_limit` reruns. One compute-owned predicate (`teardown_rerun`) decides from the reservation's teardown jobs, read through one unpaginated engine-internal read, whether the teardown is not rerunnable, waiting, ready, or spent; dispatch acts on it, and the release status reads it beside the aggregate, as it reads the compensable predicate. A `teardown_failed` aggregate whose rerun is waiting or ready, or whose latest job is still unsettled, reads as tearing down, so the lease stays `releasing`; one not rerunnable or spent reads as failed, the message for a never-started teardown saying so and how many reruns were spent, and the lease enters `release_failed`, which then means only that an operator must act. A teardown whose execution started, a cancelled one, and one finished before starts were recorded stay failed, their capacity held, until an operator verifies the host and force-releases. The lease's `release_job_id` is the fulfillment, so a new teardown job touches neither it nor convergence, which requeues every `teardown_failed` row as before.

The lease watchdog's grace is the backstop for every stuck release: a lease still `releasing` past `lease_watchdog_grace_period_seconds`, timed from when it entered `releasing`, enters `release_failed` with `teardown_timeout`, whether its teardown is in progress, a rerun is pending, its status read keeps failing, or its teardown keeps failing to begin. Its default, 3600 seconds, covers a teardown of expected length succeeding on a job retry or a rerun ([configuration](configuration.md#secrets-are-named-not-carried)). A longer teardown is timed out like any other, and since an operator's retry-release re-observes the same aggregate, one that has since reached `torn_down` is released by that call, and one with a rerun pending returns to `releasing` and waits for it.

A create that was dispatched and then failed has host effects nothing proved removed, so it is not left to an operator by default. When its provider reported the failure and its job metadata names its create job, release compensates it: it begins the domain's ordinary teardown from the `failed` aggregate, marked `create_compensation`, and capacity returns only when that teardown reaches `torn_down`. Each domain's teardown is safe after a partial create: bare metal's reclaim reports an account its grant never created as absent rather than failing, and a VM teardown removes only what its own guest created, finding each artifact by the guest's name when its cleanup script is missing and failing on one it cannot attribute. Compute provisioning alone decides eligibility, through one predicate the release decision, status, and teardown ports share; a failed row it cannot compensate — quarantined, with unreadable metadata, or with its create job missing — still waits for an operator. A compensating teardown that fails before its execution starts is run again by the same rule as any teardown, keeping `create_compensation`.

Readiness checks use local service dependencies. Slower outbound provider or storefront diagnostics belong to operator surfaces so an external failure does not unnecessarily make a healthy API/worker process unready.

## Authenticated service boundary

### Exact role and authority selection

The provisioning boundary authorizes complete scheme-tagged principals, not
addresses or credential-shaped strings. Each authenticated route selects its
required `seller` or `admin` role, and the durable provisioning principal
authority resolves the active principals for that role. Bootstrap configuration
seeds an empty role binding but never overwrites persisted generations, so
configuration drift cannot silently replace a rotated authority.

The provisioning service has its own configured public principal and injected
signer. Client composition supplies the provisioning endpoint and expected
service authority trust set independently of request content. The same
provisioning composition resolves the storefront counterparty for inbound
requests and outbound lifecycle callbacks. Consequently, a valid proof by a
different role or principal has no authority, and neither a request body nor a
private credential can choose the identity against which it is checked.

### Canonical requests, durable replay, and signed responses

`arkhai.market-request-signature.v2` binds the caller role and complete
principal, HTTP method, semantic operation and resource, request identity,
timestamp, and canonical body hash. Route metadata supplies the operation and
resource independently of proxy path spelling. This makes body mutation,
cross-role replay, principal substitution, and retry with changed content fail
before a handler or infrastructure effect runs.

The authority durably reserves `(principal, request_id)` with the canonical
request digest before dispatch. A completed exact retry recovers the recorded
status and body and returns them under a fresh signed response. A concurrent
exact retry is rejected while the dispatch lease is active; after expiry, one
caller can atomically claim the unfinished reservation and resume it. Reuse
with any different signed content remains a replay conflict. Durable outcome
classification is therefore the recovery authority rather than process memory.

Mutation responses use the distinct shared response domain to bind the status,
originating request identity, provisioning authority principal, timestamp, and
canonical response body. Clients verify every field against the expected
authority before accepting an acknowledgement. This distinguishes an
authenticated authority outcome from an unsigned status code or a correctly
signed response produced by the wrong service.

A route that fails after the caller was authenticated still answers signed: a
500 with a fixed, non-revealing detail, the error itself going to the service's
log. An unsigned 500 would reach the caller's typed client as missing response
authentication rather than as the authority's failure. The provisioning
service's middleware records that answer as the request's outcome, as it
records any, so an exact retry replays the same signed 500 instead of finding
the reservation in progress until its dispatch lease expires. `kit/site`'s
middleware, which the API-credits service composes, keeps reservations but no
outcomes, so it answers the signed 500 and records nothing; an exact retry is
handled as its route's retry contract says. Neither middleware catches a failure
after a route has started its response: the body stream ends and the error is
re-raised only once the status is sent, so the middleware would sign, and the
provisioning service record, a truncated body under the original status. No
route streams its response, so the limit is latent; a streaming route needs the
middleware to detect that failure or to refuse streamed responses.

A request that resolves to no route contract is answered before authentication,
by what failed to match, and unsigned: 404 for a path no contract names, 405
with `Allow` for a path named only under other methods, 400 for a route whose
body resource cannot be bound. Route resolution reports the case through a
typed error (`ProvisioningRouteNotFound`, `ProvisioningRouteMethodNotAllowed`,
`ProvisioningRouteResourceUnbound` in `compute_provisioning_contracts.routes`;
`SiteRouteNotFound`, `SiteRouteMethodNotAllowed`, `SiteRouteResourceUnbound`
in `market_site.auth` for `kit/site`'s middleware). Such an answer cannot be
signed meaningfully: a response proof binds the method, operation, resource,
request identity, status, and body, and a client verifies it against its own
operation and resource, while the server knows no operation for an unknown path
or a wrong method and no resource for an unbindable body, and a request carries
a signature over its operation rather than the operation itself. Signing "not
served" over the caller's claimed operation needs a request envelope that states
its operation, which the current version does not; until then the answers stay
unsigned. The family client and the site client refuse an unsigned answer as
they refuse any unverifiable one, but report it distinctly
(`ComputeProvisioningUnauthenticatedResponseError`,
`SiteCapacityUnauthenticatedResponseError`), by its status alone: an unsigned
answer is also what anything between client and authority may give, so nothing
it says is repeated. The family client resolves its own table before sending,
so it meets these answers only when its table and the service's differ.

The route table can answer by cause, and can refuse ambiguity, because a route
contract's pattern is restricted: literal segments, `[^/]+` named captures,
finite alternations of literal segments, and an optional terminal `/?`. Building
a contract refuses any other pattern, and so does a pattern compiled with a
flag, since the comparison reads only the pattern's text. Over that grammar,
overlap is decidable segment by segment, so `ProvisioningRouteTable` refuses,
when it is composed and before the service accepts traffic, two contracts of
different contributions that one method and path could both match: neither
owner can say which signature such a request means. Within one contribution the
first matching contract decides, in the order its owner gave. Detecting
ambiguity per request instead would let a mis-composed service start and fail on
exactly the overlapping requests. The grammar is hand-written only while it
stays this small: a route needing more, such as a tail capture or a typed
segment, is a reason to adopt an established path-template grammar and its
matcher, and rebuild the overlap comparison on it, not to widen this one.
`kit/site`'s middleware has no ambiguous case: it resolves first-match over the
one ordered table its composition root gives it, which the API-credits service
extends with its own routes, and it takes no contributions.

One such failure is refused at startup instead: the service does not start
while a stored pool names a provider no registered handler serves. Handlers are fixed by
the build and every write refuses an unknown provider, so such a row comes only
from outside the service's write paths, no pool document can repair it, and
every read of it would fail; startup names each pool and provider, beside its
refusal of stored pools whose declarations are invalid. Unreadable own state
stops startup because waiting does not repair it, where an unavailable
dependency starts the service degraded.

### Scheme, credential, and package boundaries

Ed25519 and EIP-191 use the same canonical request, response, replay, and
rotation models. Verifier-registry dispatch changes only the cryptographic
operation and remains local in both cases. Ed25519 provides a wallet-free
service profile; selecting EIP-191 for marketplace identity does not by itself
require an RPC endpoint, while any chain effect receives separately validated
wallet and chain settings.

Ordinary configuration contains public service, storefront, and administrator
principals and trust pins. The provisioning credential enters through the
service's secret boundary, constructs a signer whose public principal must
match configuration, and does not enter settings, persistence, request bodies,
responses, logs, or diagnostics. Service, storefront, and administrator
authority inputs are independent, and optional chain-wallet credentials do not
implicitly supply any of them.

The shared identity package owns principal normalization, signer and verifier
contracts, canonical request and response models, proof-scheme dispatch, replay
classification, and rotation proof validation. Compute provisioning packages
own only their route semantics, durable replay and principal-authority adapters,
and service/client composition. Keeping that dependency direction prevents a
second signature protocol and keeps raw private keys and signature encodings
out of generic provisioning orchestration.

### Rotation and disablement

Counterparty rotation changes the principal generation attached to a stable
role binding, not the role subject itself. Both the active and replacement
principals sign one authority- and subject-bound statement. The registry
records the replacement and audit history, accepts both principals only for the
bounded overlap, and rejects the old principal after expiry or retirement.
Disablement removes authorization without assigning it to a replacement and
does not erase the binding or rotation history.

## Explicit authority boundaries

Provider-to-executor linkage and universal multi-storefront event routing are
not inferred. Optional notification adapters are delivery mechanisms, not
ownership authorities.

## Host preparation cannot cost the machine

Two rules govern how a rented host is prepared for passthrough, and both exist
because the failure they prevent is unrecoverable in band.

**No configuration change that can remove the host's network path may require a
reboot to take effect, or a reboot to be undone.** Enabling the IOMMU is exempt:
it claims no device. Every decision about which devices go to guests is applied
from userspace, so a wrong decision fails an operation on a running machine
rather than producing one that cannot be reached to correct it. A host that has
lost its network interface cannot be recovered by any in-band mechanism — a
tunnel, a second SSH daemon, an agent, or a self-healing loop all require the
interface that was taken.

**A rollback target must be a state that cannot fail, not the most recent state
that has not yet failed.** A configuration that boots correctly by winning a
driver race is an unobserved failure, not a known-good baseline, and reverting
to it delivers the machine into a coin flip at the moment reliability matters
most. The rescue boot entry therefore binds no device at all: its correctness
follows from what it does rather than from history. For the same reason a
binding is not made to persist across reboots until it has been applied and
verified on that machine.

Refusing an ambiguous topology is preferred to working around it. An IOMMU group
is the hardware's unit of DMA isolation, so a GPU grouped with a network or
storage controller cannot be assigned without assigning that controller too. The
ACS override patch would split such a group by asserting an isolation property
the hardware does not have, and its failure mode is silent cross-guest DMA. In a
marketplace renting isolation to strangers, the correct outcome is an accurate
report that the device is unavailable.

## Guests are isolated from each other

Every VM guest on a host attaches to libvirt's `default` network (`virbr0`,
`192.168.122.0/24`), and no guest shares a layer-2 segment with another by
anyone's choice: a seller gains nothing by it, and different buyers' guests
sharing one could reach each other and claim each other's addresses. A private
network for one buyer's guests would be a buyer feature with its own
representation in negotiation; no pool or seller setting places guests on a
shared segment.

**Port isolation and the anti-spoofing filter.** Every guest's interface is
defined once, by the `vm-management` role's `templates/guest-interface-args.j2`,
which every `virt-install` site looks up, GPU guests' included: a virtio NIC on
`default` with `<port isolated='yes'/>` and libvirt's `clean-traffic` filter,
its parameters `CTRL_IP_LEARNING=dhcp` and `DHCPSERVER=192.168.122.1`. It is a
template rather than a variable because a pool's `extra_vars` override any
variable. An isolated bridge port forwards only to ports that are not isolated,
which on `virbr0` is the bridge itself, so a guest reaches DHCP, DNS and the NAT
uplink but never another guest at layer 2; `clean-traffic` holds it to its MAC
address and the address it leased, so it cannot claim another guest's address by
ARP, and drops every frame that is not IPv4 or ARP. A libvirt network per guest
would need subnet allocation, a dnsmasq per guest and a rewrite of every
teardown path reading `default`; a filter of the host kit's own would have to
keep ARP and DHCP correct by hand. Host preparation refuses, naming each missing
item, a host whose libvirt predates 6.1 (port isolation), whose virt-install
predates 3.0 (the `--xml` edits that set the filter's parameters), or which
lacks the nwfilter driver's `clean-traffic` filter or `ebtables`, which host
preparation installs.

**The guest policy.** The host kit's `tasks/guest-policy.yml` installs chains of
its own, each jumped to from the first position of its built-in chain for
packets arriving from `virbr0`:

- `ARKHAI-GUEST-IN` (from `INPUT`): a guest reaches DHCP, DNS to the bridge's
  address, and replies of connections already established; everything else to
  the host, its SSH included, is dropped;
- `ARKHAI-GUEST-FWD` (from `FORWARD`): a forwarded packet going back out on
  `virbr0` is dropped first, closing the hairpin through the gateway to another
  guest; replies of established connections pass, a buyer connecting from a
  private address included; an accept for each
  `guest_allowed_private_destinations` entry, empty by default, follows; then
  link-local (`169.254.0.0/16`, a cloud's metadata service among it) and the
  private ranges (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`,
  `100.64.0.0/10`) are dropped, and anything else returns to `FORWARD`, where
  libvirt's NAT accepts it;
- `ARKHAI-GUEST-V6` (from ip6tables' `INPUT` and `FORWARD`): every IPv6 packet
  from the bridge is dropped. A filtered guest sends none, so the drop takes
  nothing from it; it closes the IPv6 path of a running guest whose filter waits
  for its next start, on a host whose `default` network carries IPv6.

A guest that reaches the seller's networks, its management route, or its cloud
credentials has crossed the boundary a seller places beside buyers as surely as
one that reaches another guest, so the private ranges are closed unless the
seller lists a destination. A connection the guest opens toward a private
address has its first packet dropped and never becomes established.

The jumps lead their built-in chains because an appended rule would follow UFW's
accepts on `INPUT` and libvirt's `LIBVIRT_FWO` accept on `FORWARD` and never
run; under libvirt's nftables backend its accepts sit in a table of their own and
stop no drop here. libvirt re-adds its rules when it starts and UFW when it
reloads, so the policy is installed again after each. Host preparation renders
the IPv4 rules to `/etc/arkhai/guest-policy.rules` and installs
`/usr/local/sbin/arkhai-guest-policy`, which installs each family in one
`iptables-restore -w --noflush` transaction, `ip6tables-restore` for IPv6,
skipped on a kernel without IPv6: declaring each chain flushes and refills it,
any jump to it already present is deleted by its rule, and a new one is inserted
first, so no packet sees the chains empty or a jump missing, and every run leaves
exactly one jump from each built-in chain at position one. It runs from
`arkhai-guest-policy.service`, a oneshot ordered after UFW, the saved rules and
libvirtd, wanted by `multi-user.target` and by `libvirtd.service`, keeping no
active state so every libvirtd start, a socket activation included, runs it
again; and from a block of UFW's `/etc/ufw/after.init`, which UFW runs each time
it starts or reloads, leaving the rest of an operator's hook as it is.
Installing the policy through UFW's `before.rules` instead would couple it to
UFW's layout and leave hosts without UFW needing another path. Host
preparation's security hardening saves the installed IPv4 rules with the host's
others; nothing saves the IPv6 chain, which the unit installs at boot. The
policy does not rely on the host kit's `iptables-restore` unit.

What a guest reaches on its host is the policy's alone: no per-port guest rule
sits behind it, and host preparation deletes from a host an earlier release
prepared the exact port-22 drop and log forms, `ufw allow in on virbr0 from
192.168.122.0/24` and `vm-network-isolation.service` with its script, a
compatibility path with a scheduled retirement ([the release handbook,
"Compatibility to retire"](../../../docs/release-handbook.md#compatibility-to-retire)).
Its `allow out on virbr0` governs only the host's own connections to its guests
and stays. A VM create inserts its guest's two forwarding accepts for DNATed
buyer SSH at `FORWARD`'s first position, ahead of the policy's jump; they match
no packet a guest originates, the inbound accept requiring `! -i virbr0` and the
reply accept `--ctstate ESTABLISHED`. cloud-init reads a seed ISO, and the
host's SSH into a guest, frpc's proxy and DNATed buyer SSH are connections the
host opens or forwards, so none needs more.

**Converging running guests.** An isolated port can still be reached from one
that is not, so a running guest holding a port that is not isolated, or no
filter, could reach every isolated guest at layer 2 for as long as it runs, and
VM leases may be open-ended. Host preparation installs
`/usr/local/sbin/arkhai-guest-converge` (`vm-setup/files/guest_converge.sh`) and
runs it after the policy. For each running guest on `default` it sets the tap's
bridge port isolated (`bridge link set dev <tap> isolated on`), which does not
drop the link; applies `clean-traffic` through `virsh update-device --live`
where libvirt accepts it, leaving the interface's `<port>` element as libvirt
holds it, and otherwise leaves the filter for the guest's next start; and writes
the isolated port and the filter into the saved definition through
`virsh update-device --config`, so a restart, an autostart or a host reboot keeps
them. No buyer session is interrupted: restarting running guests would interrupt
every buyer, and isolating new guests only would leave their isolation to the
oldest guest on the host. The command prints one JSON line per running guest —
`name`, `port_isolated`, `filter` (`live`, `next_start` or `none`),
`saved_definition`, `changed` and `error` — and reports a filter `live` only when
the running definition names it and libvirt lists an active binding of it on
the guest's tap (`virsh nwfilter-binding-list`). It exits non-zero only when it
cannot run at all, and host preparation fails only then: it names each guest
left unconverged and each whose filter waits for its next start, since failing
would leave every other host step undone for one guest the operator can act on.
Callers read these lines rather than `virsh`; the real-host proof of guest
isolation runs the same command
([test-compatibility](../test-compatibility/architecture.md#the-real-host-proof-of-guest-isolation)).

The convergence leaves residual exposure. Until a guest's filter applies at its
next start, port isolation keeps it from other guests at layer 2 but not from
claiming another guest's address to the host's own end of the bridge. A
converged guest's running definition still says its port is not isolated, so a
tap libvirt attaches to the bridge again before the guest restarts, as after the
network is restarted, comes up not isolated until the saved definition applies
at the guest's next start. The convergence is a compatibility path with a
scheduled retirement ([the release handbook, "Compatibility to
retire"](../../../docs/release-handbook.md#compatibility-to-retire)); a guest
never converged keeps a port that is not isolated until it is torn down.

## The host registry owns the connection

Address, user, key material, and port are one descriptor and live together in
the host registry, because a rendered inventory must be reproducible from the
registry alone. Splitting any part into service configuration would make the
connection unreproducible and would express one value for every host, which is
wrong as soon as two hosts sit behind different tunnels.

Beside the provisioner's route, a connection may name the direct buyer route:
a tenant-facing `public_host` and `public_port`, each falling back to the
connection's own address and port. A bare-metal buyer uses this route when the
pool has no buyer relay; for a relay-backed pool, the leased relay endpoint is
delivered instead. A VM guest is reached at its own forwarded or relayed port,
never the host's `public_host` or `public_port`.

The `ssh` connection is served at version 3 alone. A submission must state its
version — the contract gives it no default — and one stating no version, or
another, is refused. A host stored at a version no codec serves is refused
before any inventory is written, and runs nothing until it is submitted again
by an update or an inventory import. An update restates every stored public
field. A protected key it neither resubmits nor replaces with a key file is
carried forward from the stored row as ciphertext, never read or decrypted.

No reader upgrades a stored connection. Besides a submission, only a recorded
migration with an exact mapping rewrites one. Compute provisioning's chain
rewrites every host's `ssh` connection stored at version 1 — which the v0.3.0
chain wrote and v0.3.0 refuses — to version 2 with the same public fields and
the same ciphertext, since version 2 is version 1 with an optional
`public_port` falling back to the connection's port; a later migration rewrites
every connection stored at version 2 to version 3 with the same public fields
and protected values and no `host_keys`, since version 3 is version 2 with an
optional pin, and marks each host it rewrites pending adoption (below). Each
writes its literal target version, not the codec's current one, and validates
each row before writing any, against the fields the versions share and refusing
a row that already states `host_keys`; a host it refuses fails the migration,
naming it, and nothing is rewritten. Only the `hosts` row stores a connection: a job reads its host's at
dispatch, through the host lookup the job engine is given, and no job record,
parameter or envelope carries a copy, so a job queued before the migration
dispatches against the rewritten host. A teardown that had already failed on a
version-1 host is not re-run by the migration ([Proof-driven
release](#proof-driven-release)); the operator handbook's upgrade procedure
recovers it.

A host's SSH key is part of the same descriptor. The connection's `host_keys`
are its pin: OpenSSH public keys, each its type and base64 without a comment,
which identify the machine rather than its route, so a submission that omits
them keeps the stored pin whatever else it changes, `ssh_host` and `ssh_port`
included, and the INI import, which carries none, keeps it too. A pin is
replaced only by stating other keys or by a capture with `replace`; stating the
old key with the new lets a host rotate without a refusal between. Keeping the
pin in the connection, rather than in a record beside it or a `known_hosts`
file an operator mounts, keeps an SSH concept with the codec that owns its
kind's fields and keeps the inventory reproducible from the registry.

A pin is stated at registration, or captured: an operator's connectivity check
of an unpinned host reports the key it presents, with its endpoint
`[ssh_host]:ssh_port` and SHA-256 fingerprint, and stores nothing, and the
capture route records that key only when the host presents the fingerprint the
operator names, which the operator compared from an independent source. The
probe that observes a key completes the SSH key exchange with authentication
disabled, so it runs nothing and sends no credential. Capture is an operator's
act rather than a job's because a host's first job is usually its preparation,
which sends the relay's client token: capturing there would hand that token to
whoever answered. A host-key certificate authority would need a CA the operator
runs and would leave a host another party prepared unsigned; the
representation leaves room for one.

The rule is the Ansible executor's, whose concept the host key is. For every
job and probe the runner writes an owner-only `known_hosts` holding the pin
under `[ssh_host]:ssh_port`, removed with any decrypted key file, and renders
verification as host variables, which outrank any Ansible configuration:
`ansible_host_key_checking=true`, `ansible_ssh_args` with the service's own
baseline, and `ansible_ssh_common_args` naming that file with
`GlobalKnownHostsFile=/dev/null` and `StrictHostKeyChecking=yes`. A setting in
a configuration file would not hold: an operator's `ansible_cfg` replaces the
packaged file whole, Ansible's ssh plugin emits `StrictHostKeyChecking=no`
ahead of the common arguments when checking is off, and `ssh` keeps the first
value it reads. Before a job's recorded start, the executor makes one
connection against the pin that runs nothing on the host, and refuses an
unpinned or mismatched host, naming the host, its endpoint, the presented and
pinned fingerprints and how to recover ([Proof-driven
release](#proof-driven-release)). A host behind a management tunnel is checked
at its tunnel port, so a port handed to another machine is refused on mismatch.
The mock executor reaches no host and reads no pins, as every lane registers
hosts without keys.

A host the version-3 migration rewrote is pending adoption, a flag on its
`hosts` row outside the connection that neither the export nor the host
definitions document carries. For such a host, the check before a job's start,
or a connectivity check, accepts the key presented into an empty file and
records it as the pin, clearing the mark, in one compare-and-set that takes
effect only while the host is still pending. Every job then checks against the
committed pin, never the key it observed, so a job whose observation lost to
another adoption fails before its start. The adopting connection sends nothing
secret, and what it trusts is a deployed host's first answer after the upgrade,
which is what such a host was trusted with on every earlier contact; strict
refusal of every deployed host until an operator pins it would be an outage
from the upgrade on. Stating `host_keys`, or capturing, clears the mark, and a
host registered after the upgrade is never marked. The adoption is a
compatibility path with a scheduled retirement ([the release handbook,
"Compatibility to retire"](../../../docs/release-handbook.md#compatibility-to-retire)).

The port renders explicitly even at its default, so an inventory line states
what the registry holds rather than leaving the default implied by an absent
one. A malformed port fails its entry rather than degrading to a default: an
unreachable host is not a degraded host, and a substituted value turns an
operator's typo into a failure that resembles a network fault.

## Hosts are a reconciled declaration

Hosts reach the registry through the host API, the Ansible INI import route, or
a host definitions document. The document follows the rule every definition
document follows: a process start is not a submission and a changed document
is. Startup applies it only when its digest differs from the one recorded under
the kind `hosts`, recording the digest in the apply's own transaction, so an
edited and rolled document is applied and a restart against an unchanged one
leaves API edits alone. A site must be establishable from configuration alone,
since a deployment applies a chart with no operator API call in it, which is why
hosts keep a startup document at all. Seeding only an empty registry was
rejected because an edit to the file then did nothing and said nothing.

The document is YAML with the registration API's field names, not the Ansible
INI. The INI cannot state `enabled` or a connection's kind or version, always
names a key path, and reads an absent pool as "leave it", so reconciling it
would be a merge rather than a declaration. The YAML form is format-neutral:
the compute family library owns its parsing, validation, equality, session-scoped
apply, and export beside the host authority, and the service gates it as it
gates capacity, after the stored-pool check so every pool a host names exists.
The Ansible distribution keeps the INI parser and its import route, which
upserts as it always has; an operator who prepares hosts with Ansible keeps that
INI as a separate list.

An entry declares its whole host. Omitting `pool_id` unplaces the host and
omitting `enabled` enables it, so deleting a line from an entry means what it
says, as it does for capacity and relay entries; merging would bring back the
omitted-versus-null distinction a declaration exists to avoid. The cost is the
capacity document's: a host disabled or moved through the API is restored by the
next change to the document unless the document restates it. Equality is taken
after the connection's codec, with the stored connection as `previous`, so an
entry omitting a field the codec defaults equals a host stored with the default,
and an equal entry writes nothing and runs no pool-change hook. The codec types
the public fields strictly for every submission, because they are the values an
operator types by hand.

A host the document does not name is retained and reported, not disabled. Hosts
registered through the API, as every end-to-end lane registers them, must
coexist with the document, and disabling every host a document does not name
would take them out of service. Disabling a host keeps new deliveries off it
(["Disabling a host keeps new deliveries off it"](spec.md#requirement-disabling-a-host-keeps-new-deliveries-off-it)),
so a document that disabled the hosts it stopped naming would close their
listings on an edit to an unrelated entry.

A document that cannot be applied fails whole. The apply writes into the
caller's session and continues past a pool-change hook's refusal so that every
refusal is reported, then rolls back on any problem; whatever a refusing hook
wrote is discarded with the rest, so the hook contract needs no savepoint. A
refused move at startup keeps the service down until the edit is reverted,
because the leases that refuse it cannot drain while it is down; validating a
changed document through the import route before the release reports the same
refusal against live state without an outage.

The document names key material by `key_path`, or keeps a stored protected key
by naming none, and never carries it: registering key material stays an API act.

An existing site's first document comes from the canonical export, which
reproduces pools and enabled states set through the API, where converting an INI
would reproduce the file rather than the site. A site with no recorded `hosts`
digest applies its first document like any changed one. The export omits a host
it cannot state as an entry, one whose connection kind or stored version no
codec serves; such a host already runs nothing until it is submitted again, and
a document built from the export retains it and reports it as not named.

## Related contracts

- [Fulfillment](../fulfillment/spec.md)
- [Site capacity](../site-capacity/spec.md)
- [Resource-pool management](../resource-pool-management/spec.md)

## Provider operation correlation

A provider job identifier is the durable correlation point for an in-flight
Ansible run. Losing that correlation does not prove that creation failed or
never occurred, so recovery MUST NOT compensate by launching another create
playbook. The adapter remains the owner of provider metadata interpretation and
teardown-envelope construction.

## Buyer access to provisioned hosts

A provisioned host has an operator management connection and may also carry a
buyer route. They are separate authorities. The host registry stores the
management connection needed to render provisioning inventory. A direct
bare-metal route uses the host's buyer-facing `public_host` and `public_port`,
each falling back to the connection address and port. A relay-backed
bare-metal grant instead creates a per-lease TCP proxy from the host to a leased
relay port. A VM guest is reached through its own forwarded or relayed port; the
host's buyer-facing route is never the VM endpoint.

### Buyer SSH uses a leased TCP port

SSH sends no `Host` or SNI header and exchanges its version banner immediately,
so an HTTP-style subdomain cannot select a buyer's SSH session. A TCP proxy
uses a distinct remote port, which is the route the lease can allocate and
reclaim.

### Port allocation is not a relay-dashboard lock

A relay dashboard is a monitoring surface, not a distributed lock: querying it
for a free port adds relay credentials, reachability and a race to allocation,
and asking the relay whether a client registered its own proxy adds a roundtrip
to a third party about client-owned state. The provisioning service allocates
from its durable lease authority; the registering client verifies its proxy.

### Relay admission is local to the relay

The compute-family service allocates a port and signs one short, lease-bound
grant for it. The relay plugin verifies the grant locally; neither the plugin
nor the relay calls the provisioning service. The grant binds its audience,
port and expiry, and admission requires a TCP proxy on that exact port, inside
the configured issuer range and before expiry. The plugin and signer conform to the published grant protocol and vectors
([tool documentation](../../../tools/frp-grant-admission/README.md)); the shared
FRP role owns the verified 0.61.1 binary pin. Admission has no effect on an already registered proxy, so teardown
removes the proxy and a released port remains quarantined through grant expiry
plus the configured reuse margin. Keep service and relay clocks synchronized
well below that margin; the plugin checks expiry on its own clock without
leeway.

The versioned `frp-grant+jwt` carries a JCS-canonical compact token with `aud`,
`exp`, `jti`, and `port`, plus `sub` when a host is recorded; its `kid` is the
signing key's JWK thumbprint. `jti` names the owning reservation. The token has
no `iat` or `nbf`; issuer keys are configured in the plugin's published public
key format, and the signer is checked against the plugin's conformance vector.

### Relay credentials stay on the host and in the service

The buyer client runs on the host, never in a buyer-controlled VM. VM
guest-root control does not expose host-held relay credentials. On bare metal,
this boundary depends on the tenant remaining nonroot, the root-only client
configuration, and the authenticated admin API on a privileged port. The host's
buyer client uses a generated per-host admin password; binding below port 1024
prevents a nonroot tenant from impersonating it while the client is stopped. The management
client and management relay stay separate. Tasks that render, read or send the
grant, relay token or admin password use Ansible `no_log`, and each domain's
codec marks these values as secret fields for job redaction. Provider extras
cannot override the client baseline, proxy targets or task controls.

In the service, the relay token is decrypted only into a run's variables file,
created owner-only and exclusively under a random name in the process's
temporary directory and removed on every ending of the run, as decrypted host
keys are. That protection rests on the provisioning container never being
shared between users, which holds by design: a user who opens one to others, by
adding their own SSH keys or running their own tunnel into it, has stepped
outside what this repository and its deployment provide.

The `grant_key_secret_key` profile value is one-line standard base64 encoding
of an Ed25519 PKCS#8 DER private key; surrounding whitespace is stripped, and
invalid or missing values fail relay creation without echoing the secret. It is
read when a relay is created; later API rotation remains authoritative over
definitions reconciliation. Keep a
controlled private-key value in the deployment profile when an empty-database
reinstall must reproduce the plugin's trust. The relay stores its private key
encrypted and returns public key and lifecycle metadata only. Rotation stages a
new key, adds its public half to the plugin, then activates it; retain retired
keys until their outstanding grants expire. Service-generated keys survive only
with the service database. No live operation reissues existing grants or rotates
a shared client token across hosts.

### Relay installation and reload boundaries

The family `relay-server` role accepts the plugin wheel, hash-pinned runtime
requirements and configuration as operator inputs; it does not fetch or build
them. The native installer checks candidate configuration before publication,
uses a protected root-owned configuration (0640 under a protected 0750
directory) and a dedicated nonroot service identity with no login or extra
groups, and selects immutable fingerprinted program releases. A changed
program restarts the plugin; a configuration-only change reloads the same
program. The plugin keeps its listener bound across reload, so a native listener
change requires explicit drained maintenance and coordinated reinstallation.
Changes to frps version or configuration also require draining because frps
restart interrupts its sessions. These are operator deployment boundaries; the
service cannot prove a relay has admission configured. The [validation
runbook](../../../docs/development/VALIDATION_RUNBOOK.md#28-prepare-and-operate-buyer-relays)
contains the installation and deployed refusal procedures.

### Relay sharing and containment

A relay is shared routing state, not pool configuration. One host client has one
rendezvous and token, so pools on that host cannot choose independent relay
baselines. A shared relay can separate provisioning authorities with
nonoverlapping issuer ranges and keys, but still shares its token and sessions;
one operator's frps restart affects every user. A separate relay per operator
is recommended. For a compromised signing key, remove it immediately and deny
its next reconnects, or retain it until its leases end with the signing risk
limited to its issuer. A leaked client token requires draining the relay in
every provisioning service that registers its server, then rotating the token
and host baselines.

If teardown cannot reach the host, a relay operator must block the leased port
and end established sockets in the relay namespace; where firewall control is
unavailable, removing the port from `allowPorts` and restarting frps interrupts
the shared relay. Keep containment until expiry and registration removal are
verified. Relay containment closes the route only; reclaim still needs host
activity termination and verified cleanup.

A relayed delivery's port is leased on the relay its capacity declaration's pool
references, whatever pool, if any, its host is placed in, and the job adding its
proxy points the host's one buyer-facing client at that relay first:
`relay-proxy`'s `add.yml` includes `relay-client`, whose baseline
synchronization writes the job's relay address, port and token and restarts the
client when they change, before the proxy is added. The job's relay is resolved
from the lease, and the lease from the declaration's pool. That the relay the
host's client dials is the relay its deliveries are leased on rests on three
facts: a host has at most one capacity declaration, so every delivery on it is in
one pool; a pool's relay reference cannot change while it holds a lease; and the
site refuses to move a declaration to another pool while a reservation holds
capacity against it. A change relaxing any of them answers for the rule. Tests
hold both halves: a static test of the family roles, and an application test
leasing a host placed under another relay, and an unplaced host, on its
declaration's pool's relay.

A host's own pool is placement intent, and three rules read it where the relay
that matters is the declaration's pool's. The management-route rule claims only
the obvious case, since any admission-enforcing relay refuses a management
proxy; the host pool-change hook and the drain only refuse or withhold more than
necessary. Each errs toward caution, so none is moved to the declaration's pool,
which would need a relay seam into the site's declaration writes.

### Rebinding requires draining

A host's relay binding cannot change while any affected lease remains active.
The host authority composes the compute-family relay mechanism's pool-change
check; it refuses a relay-changing move while relay leases exist.

A drain is one lifecycle — stop new work, let existing work finish — at two
scopes, and there is no other. Disabling a pool drains that pool, which is what
a pool's relay reference and a host's move to a pool on another relay wait on.
Disabling a relay drains every pool referencing it, which is what a relay's
address, port, or token waits on, since each change affects every pool on the
relay. A refusal under the rebinding rule names the drain at the scope that
clears it, so an operator facing a relay-side refusal is not sent to disable
each pool on the relay in turn.

### Disabling a relay drains it

A relay's `enabled` is its drain, for VM and bare-metal delivery alike.
Disabling it stops new work on the relay in two places and lets every delivery
already holding a lease on it run to its end:

- **No new delivery is placed on it.** The compute composition reports to the
  site authority the hosts taking new delivery as the host authority's report
  less every host placed in, or with a declaration in, a pool referencing a
  disabled relay — the seam a disabled host already uses, so the site learns
  nothing of relays. Both are counted because a host's placement and its
  declaration's pool are recorded apart: a bare-metal host may be unplaced
  while its one declaration sits in a pool, and a delivery takes its relay from
  the declaration's pool.
- **No port on it is leased to a new owner.** The allocator, the one place a
  lease is created, refuses a new owner on a disabled relay, reading the relay
  row under a lock a concurrent disable cannot pass, so a disable committed
  while an acceptance is in flight either waits for it or is seen by it. An
  owner already holding a lease receives it again. A disabled relay's active
  leases therefore only shrink, and "drained" is stable once reached.

Execution does not refuse a disabled relay: a create whose lease was allocated
before the disable, and every teardown and reclaim, run, since refusing them
would leave guests reachable past their lease end and hold every failed
delivery's lease, and the relay would never drain.

The relay read reports `active_lease_count` and `drained`, true exactly when
the relay is disabled and holds no active lease, computed from the leases and
required in the typed response, so a client reading a service that does not
report them fails to parse rather than reading an unknown as an answer. The
condition is stated by the service, where the lifecycle rule lives, rather than
rebuilt by each reader, because the relay's operator relies on it to remove the
server. It does not wait for a released lease's grant to expire: a lease is
released only once its proxy is gone, and a grant is verified only by its own
relay's keys, which go with the server.

Disabling is reversible before or after the relay drains: it removes no proxy,
releases no lease, and changes neither the token nor a grant key. Removing the
relay server, or on a shared relay this relay's keys and range in the admission
plugin, is the relay operator's, outside this repository; the service never
verifies that a server exists, so a relay is enabled again only when one runs.
Nothing deletes a relay: a drained relay's row stays, disabled, as the record
its leases, retired keys, and pool references point at, and keeps holding its
rendezvous, so a server reinstated there is the same relay. A relay the
definition document stops listing is left as it is, since relays are also
created through the API and omission cannot mean drain; a listed relay is
drained through its entry's `enabled`. The procedure is the [seller relay
guide](../../../docs/seller-frp-setup.md#retiring-a-relay) and the [relay
runbook](../../../docs/development/VALIDATION_RUNBOOK.md#retire-a-relay).

## Bounded bare-metal working data

Bounded cleanup is an opt-in bare-metal policy; legacy key-removal, account-lock
and home-deletion policies keep their existing semantics. Trusted deployment
configuration selects the bounded policy and its identifier before grant, and
the accepted reservation carries that selection through reclaim. Buyer input
cannot select the UID, group, paths, or policy. Existing unreceipted accounts
and grants cannot be adopted into it.

A root-only host helper and protected host-local ledger own identity history.
The helper durably consumes a fresh UID/private primary GID pair before either
account object is created, retains consumption for the policy lifetime, and
returns the recorded numeric identity for cleanup even after NSS no longer
names the account. Retries of the same reservation reuse its receipt; another
reservation never reuses consumed IDs. Service database restore, image
redeployment and campaign reset preserve this ledger. A valid older ledger copy
cannot detect its own rollback, so known or suspected rollback requires host
quarantine until history is verified or the host is decommissioned.

The policy's protected home, scratch and path-backed IPC roots define the whole
deletion boundary. The helper binds root identity, device, inode and Linux mount
identity; it walks without following symlinks or mounts, rejects root/policy
aliases and overlap, and refuses foreign descendants, identity drift, unreadable
inventories or mutation races instead of broadening cleanup. A selected entry's
containing directory and ancestors must be controlled by trusted root or the
quiesced tenant; a foreign-owned ancestor or group/other-writable directory
without the sticky bit refuses cleanup. Effective POSIX ACL write masks are
reflected in those mode bits. The helper retains the checked descriptor during
removal and rechecks parent authority, so a concurrent replacement is a refusal. It removes only
attributable entries inside selected roots. System V IPC uses owner and creator
identity together, rechecks the object before removal, and verifies inventory
afterwards; a recycled numeric kernel object ID alone is not attribution.
Data outside covered roots is not deleted. Copies transferred to another UID
and hard-linked copies outside those roots remain outside this policy.

Reclaim removes the buyer proxy and revokes the bounded key through fixed-path,
descriptor-safe helper operations before the existing activity barrier. The
barrier verifies sessions and scheduled activity have ended; the helper separately
checks that no process retains the numeric UID. It then cleans attributable
scratch and IPC and validates the home. The role deletes the account without
recursive home removal, calls the helper's descriptor-verified `remove-home`,
removes only the receipted unused private group, then calls `verify-complete` to
independently verify absence and record completion. A refused step fails
teardown and keeps capacity held; retry re-reads the receipt and remaining
state. Grant operations accept only a `reserved` receipt: once `clean` marks it
`cleaned`, the account may already be deleted, so a grant that starts after
cleanup is refused rather than recreating the account and its key while
teardown is unproven. The helper's lock covers one call, not a grant's several
role steps; a grant already past `reserve` when cleanup starts is refused at
`verify-identity` or `install-key`, so no key is installed and reclaim's retry
recovers. The SSH key helper pins the home and `.ssh` through no-follow descriptors
and replaces or removes only the validated `authorized_keys` entry, avoiding
path traversal through tenant symlinks. This bounded key path does not change the
legacy policy's behavior. Neither policy promises erasure of transferred data,
external links or data outside the declared boundary.
