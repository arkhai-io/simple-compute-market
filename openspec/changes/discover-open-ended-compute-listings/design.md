# Design

## Context and authority

Discover the terms that the archived `negotiate-open-ended-compute-terms` publishes, using the common codec of the archived
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
  null) and does not filter it. Both compute storefronts publish `available_until_utc`
  (`domains/vms/storefront/src/market_storefront/services/publication_terms.py`), which
  the registry schema neither declares nor filters.
- The Arkhai payments registration contributes, among its local clause fields,
  `arkhai_payments.period` (absent for once-only options), `arkhai_payments.billing_kind`
  (`total` or `per_period`) and `arkhai_payments.approval_window`, the approval window
  under its renamed name (`kit/arkhai-payments/src/market_arkhai_payments/settlement_config.py`;
  permanent `settlement-configuration` spec, which reads it under either name). No
  documentation shows class recipes over them.
- `store-registry-listings-as-published` (archived) retains each signed listing as
  published, nulls and unknown admitted properties included, so an explicit null and an
  absent field stay distinct.

## Decisions

### D1. Bounds are registry fields, not option policy summaries

Keep `max_duration_seconds` and `available_until_utc` at listing level and add typed
lower-bound resource filters on both. Bare query names follow the existing
more-is-better bound convention (`registry-discovery`, "A bound filter's bare query
name is the bound a buyer searches by"). Retain filter-spec identity/ETag checks.
Compare UTC dates as instants, not lexical timestamps; retain seconds precision
without rounding a horizon upward.

The `max_duration_seconds` filter needs no new carrier. The `available_until_utc`
field is published and the as-published carrier has landed, so its schema declaration
and filter wait only for task 1.3's reverification.

Missing values: a known unlimited relative bound satisfies a finite minimum; an
absent legacy relative bound, or a missing absolute availability, is unknown and
does not satisfy an explicit minimum. An explicit unbounded absolute state is not
introduced. This separates an unlimited relative policy from an unsupported
assertion about a seller's last available date. Explanations distinguish unknown
from too short. The registry schema admits no nonpositive `max_duration_seconds`,
so "known unlimited" is an explicit null; the as-published carrier retains an explicit
null apart from an absent field, so the rule applies in full, subject to task 1.3's
reverification (were the two indistinguishable, every null would be unknown). The terms changes still omit recurring options if
neither bound is finite.

A relative-duration and absolute-date conjunction does not calculate final agreement
admission: actual start and both bounds are rechecked by the seller. Changing a
listing date does not extend accepted deals.

### D2. Common terms come from the shared codec, per option

Discovery uses the common lifecycle projections as they exist; this change adds
none and creates no second evaluator. Billing remains mechanism-owned:
`arkhai_payments.period` is the registration's local projection, which
`negotiate-open-ended-compute-terms` added; it is not pushed to the registry. Task 1.4 owns
Alkahest's billing-kind/release eligibility. Approval expiry is
`arkhai_payments.approval_window`, the name the registration now uses (`window` before
the rename); dispute holds come only from adjudication. Do not
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
payments it is the typed `arkhai_payments.billing_kind` and `arkhai_payments.period`
representation that landed with `negotiate-open-ended-compute-terms`, which task 1.2
confirms. Recurring classes require a payer entitlement
as well. A setup once part beside the rate remains recurring. The legacy splitter is
prepaid interruptible, not reserved, on-demand or spot; its own release-condition
projection excludes it from reserved without inventing a common payee entitlement
for an unsupported adapter. A prepaid recipient Alkahest option may match reserved
through its actual release condition.

Class sugar compiles to the same typed predicates this change's recipes document in
`docs/buyer-quickstart.md`, using
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

Nothing open gates this change: the bounds, the payments registration's fields and the
carrier have landed with archived changes. Only `available_until_utc`'s filter waits on
task 1.3's reverification. Activation waits for discovery plus
servicing and the hosted revision; no extra minimum-spend primitive is awaited.

First-use fixtures have one mixed listing per domain with differently priced
reserved, on-demand and spot options, differing notices, two bound values and an
option-level negative correlation case. Explain spot selection, then buy with no
horizon. Start each run with lane readiness and report double-backed evidence
separately from live deployment.

### D5. What landed before this change

The archived foundation implemented task 1.1 and 2.2's common fields and their
pushdown. The archived `negotiate-open-ended-compute-terms` implemented the payments
registration's `arkhai_payments.period` and `arkhai_payments.billing_kind` fields
(task 1.2's representation and the local half of 2.2), unit preservation through the
agreed-price accessor and `pricing.asking_rate` (2.3), and the published
`available_until_utc` (2.1a's publication). Those tasks stay here as confirmations for
this change's design session. This change keeps the bound filters, the recipes,
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

## Goal 8 rescoping

The owner disposed this change's rescoping on 2026-11-10: the period field stays
local, and D1's missing-value rule is a decision, scoped to the store-registry outcome.
After `negotiate-open-ended-compute-terms` and `store-registry-listings-as-published`
archived, this change keeps the scope D5 states and none of its tasks belongs to a Goal
8 MVP change. The delta specifications mark, inline, each requirement that went stale,
and keep its text until this change's design reconciles them.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| D1 bound fields, filters and missing-value semantics | `openspec/specs/registry-discovery/spec.md`; `openspec/specs/registry-discovery/architecture.md` |
| D2 shared projections and same-option correlation | none new — already `openspec/specs/cli-query-language/spec.md`; the period field landed with `negotiate-open-ended-compute-terms` |
| D3 class sugar, recipes, Alkahest projections and deterministic explanation | `docs/buyer-quickstart.md` (recipes); `openspec/specs/buyer-orchestration/spec.md`; `openspec/specs/buyer-orchestration/architecture.md`; `openspec/specs/cli-query-language/spec.md`; `openspec/specs/settlement-configuration/spec.md` |
| D4 delivery/dependency currency | `docs/development/ROADMAP.md`; `openspec/changes/README.md` at integration/closeout |
| D5 what landed before this change | none — a sequencing record |
