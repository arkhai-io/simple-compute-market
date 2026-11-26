# Report provisioning failures to operators

## Why

When real provisioning fails, an operator learns it late and has to read raw text
to find out why. Two gaps in Goal 1 of `docs/development/ROADMAP.md` cause that:

- **The real runner's failures aren't classified.** A job's executor reports a
  failure as a code, a message, and whether it's retryable
  (`ProvisioningErrorEnvelope` in
  `provisioning/compute/src/compute_provisioning/jobs/executor.py`). The Ansible
  executor reports every playbook failure as `execution_failed` with the message
  `"Playbook failed"`, the engine keeps only that text (`ansible_jobs.error`), and
  the transport, codec, and operator failure patterns are matched against it, so
  they classify only mocked failures and every real failure is retried.
- **Nothing tells an operator when work is held for them.** A bare-metal reclaim
  that refuses a foreign file, or a lease left `release_failed`, shows up only as the
  job's recorded error, its retry fields and log, and the lease's state, read through
  the operator's APIs. `VALIDATION_RUNBOOK.md`'s observation 5 states that no
  notification is pushed to an operator.

They are grouped because a notification is only as useful as the failure it
carries: classifying failures and delivering them to an operator is one design.

## What Changes

- **One eventing system** (design D2, D6, D16). A standalone component,
  `tools/eventing`, records declared kinds of event in the producer's own
  transaction, under a versioned envelope whose routing fields every consumer reads
  without knowing the kind, and delivers them at least once to named consumers, each
  with per-destination state, park and resume, and a finally sink. A new kind is one
  declaration and one call.
- **Operators route events to sinks** (D7, D8, D9). `kit/delivery`'s sinks serve
  events as well as introductions; a deployment's routes select events with an SQL
  condition evaluated by sqlglot; repeats are recorded once; stored state is pruned by
  time per table; an abandoned delivery goes to the finally sink, the log by default.
  The provisioning service runs a delivery worker and serves the events and their
  delivery state to an administrator.
- **The first kinds** (D13): a lease entering `release_failed`, a teardown attempt
  held for an operator-repairable failure, a job finishing, a lease's intended end,
  and a release of capacity.
- **A real playbook failure carries its class** (D3, D4, D5, D10). A callback
  plugin records each failed task; the executor and the domain codecs classify from
  that record; the class decides retry, and the job record and view keep it beside
  the message. `additional_non_retryable_errors` takes effect.
- **The lease-end report and the capacity-released callback become consumers**
  (D14, D15), the signed statements kept as their own retained table, and 0.4.0's
  pending deliveries carried over.

### Decided by the owner

- **D1: one change for failure reporting.** Goal 1's unowned gaps are grouped by
  theme. This change takes failure classification and operator notification.

### Moved into this change

- **Moving the lease-end report outbox, and the site's lease-end events it
  delivers, onto one eventing system** (D14). `replace-polling-with-authenticated-push`'s
  row said it would adopt the lease-end outbox; this change replaces that outbox with
  a consumer of the eventing system, and that change designs its push delivery, and
  the site's `capacity_events` feed, onto the same system. Its row records the move.
  `redesign-storefront-stage-events` designs the storefronts' stage events onto it;
  its row says so.

## Capabilities

### New Capabilities

- `eventing`: the standalone eventing component — envelope, kind declarations,
  recording, consumers and their delivery state, routes, retention.

### Modified Capabilities

- `physical-provisioning`: failure classification and retry, the job's structured
  failure, the provisioning kinds, routing events to sinks, the operator's event
  surface, and the lease-end report and capacity-released callback as consumers.
- `site-capacity`: the site's ending and release transitions record their events,
  and a failing transition records a caller's prepared event.
- `compute-provisioning-contract`: the job view's `failure`.
- `introduction-delivery`: sinks deliver any deliverable, a signing webhook signs as
  its composition says, and configured sinks receive the events their routes select.
- `deployment-state`: a chart passing a service's configuration through is no longer
  required to carry a values-schema fragment generated from the service's models
  (design D9, owner's notes 39 O1).

## Non-Goals

- Rerunning a teardown that never reached its executor.
  `resolve-delivery-correctness-gaps` owns that, using the job's recorded start
  (`execution_started_at`) rather than a failure class.
- Buyer-facing notification.
- Moving the site's `capacity_events` feed or the storefronts' `stage_events` onto
  the eventing system, which their changes own.
- Folding introduction delivery into the eventing system (D7).
- A CloudEvents rendering, throttling or digests, and retention by kind or severity.

## Impact

- New: `tools/eventing` (the component, its structure test, and its tests).
- `provisioning/compute/ansible/src/compute_provisioning_ansible/` (`executor.py`,
  `runner.py`, `codec.py`, `mock.py`, and a callback plugin), the VM and bare-metal
  codecs and the bare-metal `bounded-reclaim.yml` task tags.
- `provisioning/compute/src/compute_provisioning/jobs/` (the engine, the job record
  and a migration for `failure`), `lease_lifecycle.py`, and the provisioning kinds.
- `provisioning/compute/contracts` and `provisioning/compute/client` (the job view's
  `failure`, a minor bump).
- `kit/site` (recording its kinds and a caller's prepared event in its transitions).
- `kit/delivery` and `kit/delivery-apprise` (`Deliverable`, the configurable signing
  role, the event-sink consumer; a minor bump).
- The provisioning service (`[Events]` configuration, `EventDeliveryWorker`, the
  administrator routes, the signed-report table, the peer and capacity-release
  consumers, the retirement of both outboxes and a data migration of their 0.4.0
  rows); the provisioning chart is unchanged, passing `Events` through its `config`.
- `docs/guidance/engineering/helm.md`, `helm-render-tests.md` and
  `docs/guidance/repository/chart-render-tests.md`: a chart's values schema types the
  chart's own values, never a pass-through service configuration.
- `docs/operator-handbook.md`, `VALIDATION_RUNBOOK.md`'s observation 5,
  `docs/development/ARCHITECTURE.md`, `docs/development/DEPLOYMENT_AND_CONFIG.md`,
  and the roadmap's Goal 1.
- What the change changes against `marketplace-v0.4.0`: the job view gains the
  optional `failure`; one additive compute-provisioning migration adds
  `ansible_jobs.failure`; real failures of the classes D4 marks not retried stop being
  retried; `additional_non_retryable_errors` keeps its meaning and takes effect;
  `arkhai-kit-delivery`'s sinks read `reference` beside `obligation_ref`; the two
  outboxes' tables are replaced, their pending rows migrated, the signed report and
  the callback unchanged on the wire; a new `[Events]` section.

## Dependencies and Related Changes

- `resolve-delivery-correctness-gaps` (archived): its rerun predicate and the
  meaning it gave `release_failed` are what `provisioning.lease_release_failed`
  reports.
- `replace-polling-with-authenticated-push` and `redesign-storefront-stage-events`
  design their event logs onto this change's eventing system ("Moved into this
  change").

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `physical-provisioning`, `site-capacity`,
  `compute-provisioning-contract`, `introduction-delivery`
- [x] New subsystem specification: `eventing`
- [ ] No permanent documentation change

### Knowledge to promote

- D1: no permanent destination — the grouping of this change's scope is the change's
  own, not the system's.
- D2: a new repository guidance file, `operator-events.md` under the repository guidance's directory, with a repository tag:
  operator-relevant state changes are an open set of event kinds a producer extends
  with one declaration and one call; `physical-provisioning`'s specification for the
  provisioning service's operator events.
- D3: `physical-provisioning`'s specification (classification from Ansible's result
  records, the codec's `classify`, tags declaring domain classes, the mock's records)
  and architecture companion (why the callback plugin rather than parsing output or
  rescue facts).
- D4: `physical-provisioning`'s specification (the classes and their retry
  decisions, `cleanup_refused` as operator-repairable) and architecture companion
  (why a mid-run unreachable host is retried); `VALIDATION_RUNBOOK.md`'s observation
  5; the operator handbook (reading a failure class).
- D5: `physical-provisioning`'s specification (the job's structured failure) and
  `compute-provisioning-contract`'s specification (the job view's `failure`).
- D6: a new engineering guidance file, `eventing.md` under the engineering guidance's directory, with an `eventing` tag: one
  eventing system per service, outboxes as its consumers, recording in the state
  change's transaction, the delivery guarantees relied on (at least once with a
  stable identity, at most once where chosen), and the envelope's evolution rules;
  `eventing`'s specification and companion (the envelope);
  `docs/development/ARCHITECTURE.md` referencing the guidance.
- D7: `introduction-delivery`'s specification (sinks deliver a `Deliverable`, the
  configurable signing role, the event-sink consumer) and companion (why one sink
  layer, and why introduction delivery keeps its own claim).
- D8: `eventing`'s specification (routes, dedup keys, per-table time retention gated
  by consumers, per-consumer retry, the finally sink);
  `docs/guidance/engineering/persistence.md` (state kept for notification or audit is
  retained by time, configured per table); `physical-provisioning`'s
  `configuration.md` (routes and sinks).
- D9: `physical-provisioning`'s `configuration.md` (`[Events]`);
  `docs/development/ARCHITECTURE.md`, "Recovery workers" (`EventDeliveryWorker`);
  `docs/development/DEPLOYMENT_AND_CONFIG.md` (`Events` passed through the chart's
  `config`, its secret sink settings in the Secret overlay); the operator
  handbook (routes, sinks, the event reads, resuming a destination).
- D10: `physical-provisioning`'s `configuration.md`
  (`additional_non_retryable_errors` matched against the failure record) and the
  operator handbook.
- D11: no permanent destination — which capabilities a change touches is the
  change's own record.
- D12: no permanent destination — the implementation cadence is this change's plan,
  not the system's.
- D13: `physical-provisioning`'s specification (the provisioning kinds, their
  severities, dedup keys and attributes) and `site-capacity`'s specification (the
  site kinds, and a failing transition recording a caller's prepared event).
- D14: `docs/development/ARCHITECTURE.md` (the lease-end report and the
  capacity-released callback as consumers of the eventing system); the roadmap's
  Goal 1 current state.
- D15: `physical-provisioning`'s specification (the signed statements' own table,
  the peer destination's park, resume and new-peer rule) and architecture companion
  (why evidence stays domain state).
- D16: `docs/guidance/repository/package-layers.md` (infrastructure that is not
  specific to the market is built as a standalone `tools/` component, ready to lift
  into a repository of its own); `eventing`'s companion (why built, what was weighed,
  why sqlglot).
