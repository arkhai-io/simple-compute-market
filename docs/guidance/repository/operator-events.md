---
tags: [repository, operator-events, eventing]
---

# Operator events

How a state change an operator would want to know of becomes an event here: what
counts as one, where the market's kinds are declared, how a kind is declared and
recorded, and which kinds the provisioning service records. The shared rules are
[`eventing.md`](../engineering/eventing.md); the component that records, routes and
delivers events is `tools/eventing`, whose design is
[`eventing`'s architecture](../../../openspec/specs/eventing/architecture.md). How
an operator routes, reads and resumes them is the
[operator handbook's "Operator events"](../../operator-handbook.md#operator-events).

## An operator-relevant state change is an event kind

Any state change an operator may want to be told of is an event kind, not only work
held for them: a lease whose release failed, a teardown attempt held for a repair,
and a long job that finished are each one. The set is open. A producer adds a kind
with one declaration and one call to record it, and no sink, route syntax, consumer
or configuration schema changes for it: a deployment's routes select that kind by
its envelope fields and the attributes it declares, and its sinks receive it as they
receive every other
([`eventing.md`, "A service has one eventing system"](../engineering/eventing.md#a-service-has-one-eventing-system)).

A kind reports a state change, not an attempt the retry policy exists to absorb: a
job attempt that fails and will be retried is no kind, while a teardown attempt that
fails with a class an operator must repair before its retries run out is one.

## Where the market's kinds are declared

A kind is declared beside the state change it reports, in the package that owns that
change, never in the service composing it:

| Module | Package | Kinds |
|---|---|---|
| `market_site.events` | `kit/site` | `site.lease_ended`, `site.capacity_released` |
| `compute_provisioning.operator_events` | `provisioning/compute` | `provisioning.lease_release_failed`, `provisioning.teardown_attempt_held`, `provisioning.job_finished` |

A kind's name is its domain and the change in the past tense. A service's catalogue
composes the kinds of the packages it hosts and attaches any record-time hook its
composition needs: the provisioning service's `event_catalogue`
(`compute_provisioning_service.services.operator_events`) takes both modules' kinds
and attaches to `site.lease_ended` the hook that signs and keeps the lease end's
report.

## How a kind is declared

A kind is one `eventing.Kind` and a draft builder beside it:

- **Name and version.** Its `details` follow its version, raised only by an
  incompatible change
  ([`eventing.md`, "A kind's details follow its kind version"](../engineering/eventing.md#a-kinds-details-follow-its-kind-version)).
- **Severity.** `info`, `warning` or `action_required`; `action_required` only when
  an operator must act for the work to go on. A draft may state another severity
  than the kind's default, as `provisioning.job_finished` is `warning` for a job that
  did not succeed.
- **Dedup key.** The envelope paths that identify one occurrence — the subject and,
  where one subject has several occurrences, a detail or attribute such as
  `details.release_handle`, `details.retry_count` or `attributes.transition_key` — so
  a repeated transition records nothing again
  ([`eventing.md`, "An occurrence is recorded once per its declared key"](../engineering/eventing.md#an-occurrence-is-recorded-once-per-its-declared-key)).
- **Attributes.** The scalars a route filters on, each declared with its type:
  a failure class, an offering mode, a duration
  ([`eventing.md`, "Attributes are scalars"](../engineering/eventing.md#attributes-are-scalars)).
- **Subject and `related` references.** The subject is what the event is about — a
  lease as `lease:<reservation>`, a job as `job:<id>` — and every event concerning a
  lease names it among its `related` references through
  `market_site.events.lease_reference`, whoever records it, with its host as
  `host:<id>` and its job as `job:<id>` where it has them. One read by reference,
  `reference=lease:<reservation>`, then returns a lease's whole history.
- **Summary.** One line naming the lease, host or job and what happened, readable on
  its own in a push notification.
- **Details.** A model refusing unknown fields, holding only what may leave the
  service, already redacted
  ([`eventing.md`, "Details hold only what may leave the service, already redacted"](../engineering/eventing.md#details-hold-only-what-may-leave-the-service-already-redacted)).
  A job's failure reaches an event's details only where an executor classified it,
  since an executor redacts what it reports; the engine's own `configuration_refused`
  and `internal_error` carry an exception's text, so their events carry the class and
  whether it was retryable, and no message.

## An event is recorded in its state change's transaction

The producer records the event through the service's recorder in the session that
applies the change, before that session commits, so the change and its event commit
or roll back together and a transition that is not applied records nothing
([`eventing.md`, "An event is recorded in the transaction of the state change it reports"](../engineering/eventing.md#an-event-is-recorded-in-the-transaction-of-the-state-change-it-reports)).
A service composes one recorder and injects it into each producer — the site ledger
and the job engine take it as `event_recorder`, typed by
`market_site.events.EventRecorder` — and a producer composed without one records
nothing.

A component that does not hold the transaction hands a prepared event to the one that
does. The lease lifecycle decides that a lease enters `release_failed`, but the site
ledger commits that transition, so the lifecycle prepares
`provisioning.lease_release_failed` as an `EventDraft` (`Kind.draft`) from what it
read and passes it to the site's release-failure transition (`event=`), which records
it in its own transaction without knowing its kind; a stale transition the site
refuses records nothing. A further seam of this shape takes an optional prepared
event in the same way, rather than recording after the other component's commit.

## The provisioning service's operator events

The provisioning service records the site's kinds and compute provisioning's in its
own database, delivers them to the sinks its `[Events]` routes select, and serves them
to its administrator
([`physical-provisioning`'s configuration, "Operator events"](../../../openspec/specs/physical-provisioning/configuration.md#operator-events)).
The provisioning kinds are the `physical-provisioning` requirement "Compute
provisioning records operator-relevant events"
([specification](../../../openspec/specs/physical-provisioning/spec.md)), and the
site's are [`site-capacity`'s](../../../openspec/specs/site-capacity/spec.md):

| Kind | Recorded in the transaction of | Severity |
|---|---|---|
| `provisioning.lease_release_failed` | the site's release-failure transition, prepared by the lease lifecycle | `action_required` |
| `provisioning.teardown_attempt_held` | the job engine's retry transition of a teardown failing with an operator-repairable class | `action_required` |
| `provisioning.job_finished` | the job engine's terminal transition, a cancellation included | `info` succeeded, `warning` otherwise |
| `site.lease_ended` | the site's ending transition, with the lease's immutable end | `info` |
| `site.capacity_released` | the site's release that frees a reservation's capacity | `info` |

Which failure classes are operator-repairable is the domain's to say, not the family
kit's: the bare-metal adapter names them in `OPERATOR_REPAIRABLE_FAILURES`
(`cleanup_refused`), and the service hands that set to the job engine as
`held_failure_classes`. The lease-end report and the capacity-released callback are
consumers of `site.lease_ended` and `site.capacity_released`
([`physical-provisioning`'s architecture, "Lease-end report delivery"](../../../openspec/specs/physical-provisioning/architecture.md#lease-end-report-delivery)).
