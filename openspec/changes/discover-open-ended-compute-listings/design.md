# Design

The decisions below were settled at goal level with the owner on 2026-10-28 for
[`ROADMAP.md`, Goal 8](../../../docs/development/ROADMAP.md#goal-8--sell-compute-by-the-period-until-either-party-stops),
and split out of `negotiate-open-ended-compute-terms` on the goal's fourth review
round. This change's own design review may reopen any of them with a finding; its
design session verifies them against the code as `store-registry-listings-as-published`
left it and adds the spec deltas.

## Context

Verified against the tree on 2026-10-28; re-verify before planning, since the
registry dependency changes it.

- The registry (`core/registry/filter-spec.yaml`, compute schema v2) declares
  `offering_mode`, `capacity_backing`, the shape dimensions, `asking_rate{amount,
  asset, period ∈ [hour]}`, and top-level `max_duration_seconds` (stored, no filter).
  The publish route persists an explicit carrier set and discards any other top-level
  field (`core/registry/src/core_registry/api/listing_routes.py`, `api/utils.py`);
  `store-registry-listings-as-published` owns the carrier policy. Settlement-option
  params are not indexed; buyer clauses such as `arkhai_payments.window` evaluate
  them locally after the query (`cli-query-language`).
- `drop-escrow-from-shared-wire` (ready for design) moves registry filtering onto
  namespaced settlement clause fields.

## Goals / Non-Goals

**Goals:** a buyer can find per-period and preemptible options and the seller's
bounds, and ask for a class by name.

**Non-Goals:** the terms; registry-side filtering on option fields ahead of the escrow
change.

## Decisions

### D1. The seller's bounds are registry fields; the option's terms are clause fields

`available_until_utc` and `max_duration_seconds` are facts about the capacity and
live at the listing level, so they are declared registry fields with minimum-bound
filters, carried on the model the registry dependency produces. The option's
`interruption` and billing period are terms of one option on a listing, so they are
buyer clause fields — `interruption.seller_may_interrupt`,
`interruption.notice_seconds`, `arkhai_payments.period` — evaluated locally after the
query as `arkhai_payments.window` is, and at the registry once
`drop-escrow-from-shared-wire` filters on namespaced clause fields there. A listing
matches a clause when any of its options does; the buyer selects the option.

*Rejected:* owning the carrier extension here, ahead of the registry's policy — a
migration the opaque policy makes redundant. *Rejected:* a listing-level summary of
the policy for registry indexing — two statements of one promise
(`negotiate-open-ended-compute-terms` D3). *Rejected:* carrying the bounds inside
`listing_resource`, which is the capability shape.

### D2. `--class` is sugar

`--class reserved|on_demand|spot` on both buyer CLIs expands to the clause on the
billing period and `seller_may_interrupt` from `negotiate-open-ended-compute-terms`
D1's table and is never a listing term; the expansion is shown in `--explain` output
so a buyer can see what it asked for.

## Open questions

- Whether the registry's clause filtering, when it lands, treats "any option matches"
  as this design states or needs an option-level projection; settled in design against
  `drop-escrow-from-shared-wire`'s decisions.

## Implementation cadence (recommended)

One round: the registry field and filters on the carrier model the dependency left,
the clause fields, `--class` with its explanation, and the discovery scenarios. One
session.

## Permanent documentation destinations

| Decision | Destination |
|---|---|
| D1 | `openspec/specs/registry-discovery/spec.md`; `cli-query-language` spec |
| D2 | `buyer-orchestration` spec |
