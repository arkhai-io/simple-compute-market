# Report provisioning failures to operators

## Why

When real provisioning fails, an operator learns it late and has to read raw text
to find out why. Two gaps in Goal 1 of `docs/development/ROADMAP.md` cause that:

- **The real runner's failures aren't classified.** A job's executor reports a
  failure as a code, a message, and whether it's retryable
  (`ProvisioningErrorEnvelope` in
  `provisioning/compute/src/compute_provisioning/jobs/executor.py`). The Ansible
  executor reports every playbook failure as `execution_failed`, and the job
  record keeps the failure only as text (`ansible_jobs.error`). The transport,
  codec, and operator failure patterns classify only mocked failures. A successful
  result is read in either callback form and linked to its job, but a failure is
  still just a message.
- **Nothing tells an operator when cleanup is refused or teardown is held.** A
  bare-metal reclaim that refuses a foreign file, or a teardown that's exhausted its
  retries, shows up only as the reclaim job's recorded error, its retry fields, and
  its log, read through the operator's job API, and as the lease held `releasing`.
  `VALIDATION_RUNBOOK.md`'s observation 5 states that no notification is pushed to
  an operator.

They are grouped because a notification is only as useful as the failure it
carries: classifying failures and delivering them to an operator is one design.

## What Changes

- **A real playbook failure carries its class.** The executor reports a failure
  from the real runner as a structured code an operator and the retry policy can
  read, such as unreachable host, authentication refused, cleanup refused, or task
  failed, with the failing host and task. The job record keeps it as structured
  data beside the message.
- **An operator is told when work is held for them.** A teardown that has
  exhausted its retries, a cleanup refusal, and a lease held `releasing` past a
  bound each produce an operator event. The event is recorded durably and sent to
  the sinks the deployment configures.

### Decided by the owner

- **D1: one change for failure reporting.** Goal 1's unowned gaps are grouped by
  theme. This change takes failure classification and operator notification.

### Open for design, not decided here

- **The failure classes and where they come from.** Ansible's callback output, task
  tags, or a structured result the roles emit. Which classes change the retry
  decision and which only inform the operator.
- **The event store and its sinks.** The roadmap names an operator event store with
  sinks spanning provisioning, `kit/delivery`, and its chart. Whether the existing
  delivery sinks (`kit/delivery`, `kit/delivery-apprise`) serve operator events, or
  operator events need a store of their own. What the provisioning chart configures.
- **Which conditions notify.** The bound after which a held lease notifies, whether
  a retry that later succeeds notifies, and how repeats are suppressed.

## Capabilities

### Modified Capabilities

Provisional; settled in design.

- `physical-provisioning`: the structured failure a job records, and the operator
  events provisioning raises.
- `fulfillment`: what convergence reports when teardown is held.

### New Capabilities

Possibly an operator-events capability, if design gives operator events a store of
their own.

## Non-Goals

- Rerunning a teardown that never reached its executor.
  `resolve-delivery-correctness-gaps` owns that, using the job's recorded start
  (`execution_started_at`) rather than a failure class.
- Buyer-facing notification.

## Impact

- `provisioning/compute/ansible/src/compute_provisioning_ansible/executor.py`, its
  runner, and the domain roles' failure output.
- `provisioning/compute/src/compute_provisioning/jobs/` (the job record and engine)
  and a migration for structured failure data.
- `kit/delivery` and the provisioning chart, as design settles.
- `docs/operator-handbook.md` and `VALIDATION_RUNBOOK.md`'s observation 5.

## Dependencies and Related Changes

- `resolve-delivery-correctness-gaps`, before this change's design. Its rerun
  predicate's `spent` outcome and a lease's `release_failed` with
  `teardown_timeout` past the stalled-teardown grace are what this change's events
  for an exhausted teardown and a held lease read.
- `replace-polling-with-authenticated-push` and `redesign-storefront-stage-events`
  also concern event delivery. Design checks whether operator events share their
  transport.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `physical-provisioning`, `fulfillment`
- [ ] New subsystem specification, if design creates one for operator events
- [ ] No permanent documentation change

### Knowledge to promote

To be determined at design completion. Expected destinations: the
`physical-provisioning` specification and architecture companion, the operator
handbook, `docs/development/DEPLOYMENT_AND_CONFIG.md` for sinks, and
`docs/development/ROADMAP.md`'s Goal 1 current state.
