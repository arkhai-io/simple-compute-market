# Design

## Context and authority

Discover the terms that `offer-per-period-vm-terms` and
`negotiate-open-ended-compute-terms` publish, using the common codec of the archived
`agreed-evidence-and-early-termination`. Mixed-option listings have no single
interruption policy. Discovery must narrow an actual option, not combine attractive
facts from unrelated options. The existing DSL already correlates one clause to one
option and treats repeated clauses as ordered alternatives
(`cli-query-language`, "Settlement clauses are correlated ordered alternatives").

What already exists:

- The common lifecycle projections — `early_termination.payer`,
  `early_termination.payee`, `early_termination.payee.notice_seconds`,
  `early_termination.premature_stop_penalty` (asset-correlated),
  `delivery_deadline_seconds`, `adjudication.dispute.interface` and
  `adjudication.dispute.account` — are compiled locally
  (`kit/settlement-runtime/src/market_settlement_runtime/clauses.py`) and pushed to the
  registry with every predicate correlated to one option
  (`core/registry/src/core_registry/filter-spec.yaml`), as the permanent
  `cli-query-language` requirement "Common settlement fields include the lifecycle
  projections" states.
- The registry schema carries `max_duration_seconds` (an integer of at least one, or
  null) and does not filter it; no listing carries `available_until_utc`.
- The Arkhai payments registration contributes `arkhai_payments.payee_account`,
  `arkhai_payments.window` (the approval window) and
  `arkhai_payments.deposit_agreement`; `offer-per-period-vm-terms` adds
  `arkhai_payments.period` with its typed missing-period representation, and documents
  class recipes over it and the lifecycle projections.
- `store-registry-listings-as-published` owns the registry's opaque storage policy,
  which decides whether a listing's explicit null and an absent field stay distinct.

## Decisions

### D1. Bounds are registry fields, not option policy summaries

Keep `max_duration_seconds` and `available_until_utc` at listing level and add typed
lower-bound resource filters on both. Bare query names follow the existing
more-is-better bound convention (`registry-discovery`, "A bound filter's bare query
name is the bound a buyer searches by"). Retain filter-spec identity/ETag checks.
Compare UTC dates as instants, not lexical timestamps; retain seconds precision
without rounding a horizon upward.

The `max_duration_seconds` filter needs no new carrier and lands first. The
`available_until_utc` field and filter wait for its publication
(`negotiate-open-ended-compute-terms` task 2.2) and for the carrier
`store-registry-listings-as-published` delivers.

Missing values: a known unlimited relative bound satisfies a finite minimum; an
absent legacy relative bound, or a missing absolute availability, is unknown and
does not satisfy an explicit minimum. An explicit unbounded absolute state is not
introduced. This separates an unlimited relative policy from an unsupported
assertion about a seller's last available date. Explanations distinguish unknown
from too short. The registry schema admits no nonpositive `max_duration_seconds`,
so "known unlimited" is an explicit null; whether the registry can tell an explicit
null from an absent field is the carrier policy's, and this rule applies as
`store-registry-listings-as-published` settles it: if the carrier cannot keep them
apart, every null is unknown. The terms changes still omit recurring options if
neither bound is finite.

A relative-duration and absolute-date conjunction does not calculate final agreement
admission: actual start and both bounds are rechecked by the seller. Changing a
listing date does not extend accepted deals.

### D2. Common terms come from the shared codec, per option

Discovery uses the common lifecycle projections as they exist; this change adds
none and creates no second evaluator. Billing remains mechanism-owned:
`arkhai_payments.period` is the registration's local projection, which
`offer-per-period-vm-terms` adds; it is not pushed to the registry. Task 1.4 owns
Alkahest's billing-kind/release eligibility. Approval expiry is
`arkhai_payments.window`; dispute holds come only from adjudication. Do not
resurrect `interruption.*` and do not add common aliases for billing internals.
`asking_rate.period` and rate `per` values retain their declared units; billing
period is not an instruction to rewrite the advertised hourly rate.

Every predicate in one clause must match the same option. A listing survives iff at
least one eligible option satisfies the complete clause; the surviving advertised
option IDs reach selection, and the accepted option carries the advertised ID. Where
a predicate is not pushed to the registry it is evaluated after the resource query,
and explanation says so. Any coarse server filtering must be conservative: it may
return extra options, never discard one that local evaluation would accept.

### D3. Class is a transparent shorthand, not a fourth authority

Both CLIs accept `--class reserved|on_demand|spot`:

| Class | Billing predicate | Payee predicate |
|---|---|---|
| reserved | prepaid/once | no payee entitlement; non-interruptible release condition |
| on_demand | per period | `early_termination.payee=false` |
| spot | per period | `early_termination.payee=true` |

The billing-kind predicate comes from the mechanism's public registration, not a
shared parser decoding the mechanism's opaque settlement parameters; for Arkhai
payments it is the typed `arkhai_payments.period` representation
`offer-per-period-vm-terms` defines. Recurring classes require a payer entitlement
as well. A setup once part beside the rate remains recurring. The legacy splitter is
prepaid interruptible, not reserved, on-demand or spot; its own release-condition
projection excludes it from reserved without inventing a common payee entitlement
for an unsupported adapter. A prepaid recipient Alkahest option may match reserved
through its actual release condition.

Class sugar compiles to the same typed predicates the MVP's recipes document, using
the registrations' public projection API. Absence of period is not a fabricated
duration string or zero-length period, and the public comparison grammar is not
silently extended.

Apply the class predicate conjunctively to each explicit settlement alternative;
never add it as a separate OR alternative. No match is an actionable empty result,
not permission to relax class, enable a disabled mechanism or switch after acceptance.
`--explain` reports the expansion as typed predicates, filter-spec identity, pushed
versus local work, eligible option IDs/counts and sanitized rejection reasons. The
same inputs/listings produce the same explanation with no negotiation or mutation.

### D4. Gates and first use

Only `available_until_utc` waits for the carrier and for its publication; the
`max_duration_seconds` filter, `--class` and the Alkahest projections build on what
exists and on `offer-per-period-vm-terms`. Activation waits for discovery plus
servicing and the hosted revision; no extra minimum-spend primitive is awaited.

First-use fixtures have one mixed listing per domain with differently priced
reserved, on-demand and spot options, differing notices, two bound values and an
option-level negative correlation case. Explain spot selection, then buy with no
horizon. Start each run with lane readiness and report double-backed evidence
separately from live deployment.

### D5. What the MVP took

`offer-per-period-vm-terms` took task 1.2 (the period field and its typed
representation), the local half of 2.2, 2.3 (unit preservation) and, in place of
3.1's shortcut, documented recipes. The archived foundation had already implemented
task 1.1 and 2.2's common fields and pushdown. This change keeps the bound filters,
`--class` in both CLIs and the Alkahest projections.

## Rejected alternatives

- `interruption.*` or mechanism-owned entitlement aliases: duplicates the common codec.
- Listing-level class/policy summaries: mixed-option listings have no single truth.
- Satisfying predicates across options: selects a promise no option actually makes.
- Treating missing payee notice as zero: invents a notice promise.
- Treating a matching authority account as buyer approval: exact authority identity is required.
- Hard-coding option paths in discovery: projections read through the codec, so the registry does not depend on how the option is laid out.
- Waiting for server-only clauses: shared local evaluation can already narrow options.
- Pushing `arkhai_payments.period` to the registry: the filter spec pushes only common projections, and local evaluation is authoritative.
- Owning carrier migration here: the storage dependency decides that policy.
- Mapping prepaid splitter to spot or reserved: its billing and release terms differ.
- Bare-metal minimum-spend discovery gate: churn is seller pricing/policy, not protocol.
- Reserve-ahead or billing horizon as a safety filter: buyer guarantees rest on authority actions and held evidence.

## Design validation

On 2026-10-29, pinned OpenSpec 1.14.0 strict validation and
`make check-change CHANGE=discover-open-ended-compute-listings` passed, including
comment hygiene, agent skills, citations, task structure and the current change
index. No runtime implementation, new tests, deployment or permanent-document
promotion was performed. Runtime, packaging and end-to-end checks remain the
implementation tasks' gates, not claimed evidence for this design reconciliation.

## Goal 8 MVP rescoping

On 2026-11-10 the owner sequenced Goal 8's MVP changes before this one and disposed
its rescoping: the period field stays local; the approval window is named as the
code names it, `arkhai_payments.window`; D1's missing-value rule is a decision,
scoped to the store-registry outcome. D5 states the split. The delta specifications
mark, inline, each requirement the MVP owns or that went stale, and keep its text
until this change's design reconciles them.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| D1 bound fields, filters and missing-value semantics | `openspec/specs/registry-discovery/spec.md`; `openspec/specs/registry-discovery/architecture.md` |
| D2 shared projections and same-option correlation | none new — already `openspec/specs/cli-query-language/spec.md`; the period field is promoted by `offer-per-period-vm-terms` |
| D3 class sugar, Alkahest projections and deterministic explanation | `openspec/specs/buyer-orchestration/spec.md`; `openspec/specs/buyer-orchestration/architecture.md`; `openspec/specs/cli-query-language/spec.md`; `openspec/specs/settlement-configuration/spec.md` |
| D4 delivery/dependency currency | `docs/development/ROADMAP.md`; `openspec/changes/README.md` at integration/closeout |
| D5 scope split | none — a sequencing record |
