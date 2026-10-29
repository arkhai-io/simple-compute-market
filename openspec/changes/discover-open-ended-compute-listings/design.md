# Design

## Context and authority

Discover the terms from `negotiate-open-ended-compute-terms` using the common codec
from `agreed-evidence-and-early-termination`. Mixed-option listings have no single
interruption policy. Discovery must narrow an actual option, not combine attractive
facts from unrelated options. The existing DSL already correlates one clause to one
option and treats repeated clauses as ordered alternatives.

The registry filter spec stores a relative duration but does not filter it; the
current publish carrier is explicit. `store-registry-listings-as-published` owns
opaque storage policy. The foundation introduces common lifecycle projections and
query support; this change applies them to compute discovery instead of waiting for
or reimplementing that namespace work in another mechanism change.

## Decisions

### D1. Bounds are registry fields, not option policy summaries

Keep `max_duration_seconds` and `available_until_utc` at listing level. Declare the
absolute date as UTC and add typed lower-bound resource filters on both fields,
using the carrier left by the storage dependency. Bare query names follow the
existing more-is-better bound convention. Retain filter-spec identity/ETag checks.
Recommendation: compare UTC dates as instants, not lexical timestamps; retain
seconds precision without rounding a horizon upward.

Recommendation for missing relative bound: known null/nonpositive unlimited means
an unbounded relative capacity limit, so it satisfies a finite minimum; an absent
legacy value or missing absolute availability is unknown and does not satisfy an
explicit minimum. An explicit unbounded absolute state is not introduced here.
This separates an unlimited relative policy from an unsupported assertion about a
seller's last available date. Explanations must distinguish unknown from too short.
The terms change still omits recurring options if neither bound is finite.

A relative-duration and absolute-date conjunction does not calculate final agreement
admission: actual start and both bounds are rechecked by the seller. Changing a
listing date does not extend accepted deals.

### D2. Common terms come from the shared codec, per option

Use these exact common fields, read through the shared codec from the option's `lifecycle` rather than raw paths:

- `early_termination.payer` and `early_termination.payee`: presence of that entitlement;
- `early_termination.payee.notice_seconds`: its integer notice, missing if absent;
- `adjudication.dispute.interface` and `adjudication.dispute.account`;
- `early_termination.premature_stop_penalty`: integer minor units in the option asset,
  zero if absent; compare only within the same asset-correlated option. A positive
  filter is candidate discovery, not proof of buyer acceptance or held-money recovery.

For a valid option without early_termination, entitlement presence projects false;
missing notice is not zero. Malformed/unsupported terms fail validation, not fallback
to a convenient class. Preserve the codec's agreed missing-value rules if its landed
API is stricter; reverify at the dependency gate, do not silently fork semantics.
An account filter narrows discovery but does not replace the buyer's exact accepted
authority check of interface, origin, account, key and interface params.

Billing remains mechanism-owned: `arkhai_payments.period` comes from the rate
registration, implemented with its billing-kind projection by spot task 2.1.
Discover task 1.4 owns Alkahest's billing-kind/release eligibility. Use
`arkhai_payments.approval_window` for approval expiry; dispute
holds come only from adjudication. Do not resurrect `interruption.*` or the old
`arkhai_payments.window`, and do not add common aliases for billing internals.
`asking_rate.period` and rate `per` values retain their declared units; billing
period is not an instruction to rewrite the advertised hourly rate.

Every predicate in one clause must match the same option. A listing survives iff at
least one eligible option satisfies the complete clause; preserve the surviving
advertised option IDs through selection; the accepted option carries the advertised ID. If registry pushdown is available, use the same
projections and correlation there. Otherwise evaluate after the resource query and
say so in explanation. Any coarse server filtering must be conservative: it may
return extra options, never discard one that local evaluation would accept.

### D3. Class is a transparent shorthand, not a fourth authority

Both CLIs accept `--class reserved|on_demand|spot`:

| Class | Billing predicate | Payee predicate |
|---|---|---|
| reserved | prepaid/once | no payee entitlement; non-interruptible release condition |
| on_demand | per period | `early_termination.payee=false` |
| spot | per period | `early_termination.payee=true` |

The billing-kind predicate must come from the mechanism's public registration,
not a shared parser decoding the mechanism's opaque settlement parameters. Recurring classes require a payer
entitlement as well. A setup once part beside the rate remains recurring. The
legacy splitter is prepaid interruptible, not reserved, on-demand or spot; its own
release-condition projection excludes it from reserved without inventing a common
payee entitlement for an unsupported adapter. A prepaid recipient Alkahest option
may match reserved through its actual release condition.

Recommendation: compile class sugar into typed billing-kind/presence predicates
plus the codec's entitlement predicates, using the registration's public projection
API. Absence of period is not a fabricated duration string or zero-length period.
Before wiring this, freeze the typed missing-period/billing-kind representation with
the rate registration and existing DSL. If it needs a new public field/operator,
record and validate that explicit grammar delta first; do not silently invent
`exists` syntax in a language that only accepts comparisons. This is an implementation
decision gate, not a prescribed new field name.

Apply the class predicate conjunctively to each explicit settlement alternative;
never add it as a separate OR alternative. No match is an actionable empty result,
not permission to relax class, enable a disabled mechanism or switch after acceptance.
`--explain` reports the expansion as typed predicates, filter-spec identity, pushed
versus local work, eligible option IDs/counts and sanitized rejection reasons. The
same inputs/listings produce the same explanation with no negotiation or mutation.

### D4. Gates and first use

Consume the foundation's common query implementation before adding class sugar.
Reverify term placement without tying projections to that placement. Registry
implementation waits for the carrier/migration dependency; local option clauses do
not wait for server pushdown. Activation waits for discovery plus servicing and the
hosted revision; no extra minimum-spend primitive is awaited.

First-use fixtures have one mixed listing per domain with differently priced
reserved, on-demand and spot options, differing notices, two bound values and an
option-level negative correlation case. Explain spot selection, then buy with no
horizon. Start each run with lane readiness and report double-backed evidence
separately from live deployment. This design reconciliation deploys nothing.

## Rejected alternatives

- `interruption.*` or mechanism-owned entitlement aliases: duplicates the common codec.
- Listing-level class/policy summaries: mixed-option listings have no single truth.
- Satisfying predicates across options: selects a promise no option actually makes.
- Treating missing payee notice as zero: invents a notice promise.
- Treating a matching authority account as buyer approval: exact authority identity is required.
- Hard-coding option paths in discovery: projections read through the codec, so the registry does not depend on how the option is laid out.
- Waiting for server-only clauses: shared local evaluation can already narrow options.
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

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| D1 bound fields, filters and missing-value semantics | `openspec/specs/registry-discovery/spec.md`; `openspec/specs/registry-discovery/architecture.md` |
| D2 shared projections including asset-correlated premature-stop penalty and same-option correlation | `openspec/specs/cli-query-language/spec.md`; `openspec/specs/settlement-configuration/spec.md` |
| D3 class sugar and deterministic explanation | `openspec/specs/buyer-orchestration/spec.md`; `openspec/specs/buyer-orchestration/architecture.md` |
| D4 delivery/dependency currency | `docs/development/ROADMAP.md`; `openspec/changes/README.md` at integration/closeout |
