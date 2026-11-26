# Design: filter-listings-by-capacity-bounds

## Context

**What a listing states.** Every listing published through the registry client states
`max_duration_seconds`, as a positive integer or as null when the seller sets no relative
limit (`core/registry-client/src/registry_client/models.py`); a legacy row rebuilt from
its carriers states it too (`core/registry/src/core_registry/api/utils.py`). The compute
schema refuses a nonpositive value. Both compute storefronts publish `available_until_utc`
only when the seller sets one, as a UTC timestamp ending in `Z`, with fractional seconds
when the seller stated them, and never as null
(`kit/resource-pools-contracts/src/market_resource_pools_contracts/capacity_bounds.py`;
`domains/vms/storefront/src/market_storefront/services/publication_service.py`;
`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/publication_service.py`).
The registry keeps it as an admitted property its schema does not name.

**What an unset bound means to the seller.** The seller's horizon resolver reads an unset
bound as no limit on that axis
(`kit/settlement-runtime/src/market_settlement_runtime/horizon.py`). A recurring option is
published only where at least one bound is finite
(`kit/settlement-runtime/src/market_settlement_runtime/rate_publication.py`); an option
billed once is published with neither.

**What the filter grammar offers.** A filter declares a path, an operator, a value type
and a missing-value rule (`core/registry/src/core_registry/api/filter_spec.py`):

- The value types are `string`, `integer`, `number`, `boolean`, `address` and
  `decimal_text`. None is an instant, and a range over a string never matches, because
  the evaluator compares only numbers in a range
  (`core/registry/src/core_registry/api/filter_eval.py`).
- The missing-value rule is `fail` or `pass`. The evaluator drops a JSON null before any
  operator runs, so a null and an absent value both fall to that rule. A query may flip
  the rule for one request with `strict.<filter>`; no buyer command sends it.
- The buyer's query language has four value types, `string`, `integer`, `decimal` and
  `boolean` (`core/src/market_core/query_dsl.py`), and the resource-query compiler maps
  each registry type onto one (`core/registry-client/src/registry_client/query.py`).

**What a released buyer does with a changed specification.** The compiler in marketplace
0.4.0, the release the tag `marketplace-v0.4.0` records, refuses a whole filter
specification that declares a value type or a missing-value rule it does not know, so
every resource query from that buyer fails against a registry serving one. It ignores a
key it does not know on a declaration. A filter added with known types changes only the
specification's ETag, which a buyer refetches. `docs/guidance/repository/package-versions.md`
says a released client is not owed compatibility with a later storefront; it does not
speak of a later registry.

## Decisions

None is settled. The scope is the proposal's: both lower-bound filters, the schema's
declaration of `available_until_utc`, and the grammar extension they need.

## Open Questions

Each is decided in this change's design session.

### Q1 — What a listing that states no bound answers

A buyer asks for at least a duration, or availability until at least an instant. A
listing may state a null relative bound, or no absolute bound.

- (a) Three ways: a null relative bound satisfies a minimum; an absent relative bound and
  an absent absolute bound fail it. This needs a third missing-value rule and an
  evaluator that tells null from absent, and a seller stating only a relative bound
  disappears from every date query. `discover-open-ended-compute-listings` carried this
  rule, taken with the owner, before the horizon resolver and bound publication existed.
- (b) `pass` on both filters: a seller stating no limit satisfies a minimum, as its own
  resolver reads an unset bound. No grammar change; the `token` filter is the precedent.
- (c) `fail` on both: every listing with a null relative bound vanishes from duration
  queries.
- (d) `pass` on the relative bound, `fail` on the absolute. No grammar change.

`docs/development/ARCHITECTURE.md`, "Omission states no commitment", supports failing an
omitted term: an unstated bound is not a commitment to any date. The resolver supports
passing it: the seller will negotiate that horizon.

Recommended: (b). A filter narrows candidates and the seller rechecks the horizon at
acceptance, so a false match costs a refused negotiation while a false miss hides the
least constrained sellers. If the omission principle is held to govern, (d).

### Q2 — How an instant is compared, and what a released buyer is owed

The declaration and what a buyer writes, under each alternative:

```yaml
# (a) a new value type, written as a quoted ISO instant
- {name: available_until_utc_min, query_name: available_until_utc, path: $.available_until_utc,
   op: range, value_type: utc_instant, alias_kind: lower_bound}
#   --resource 'available_until_utc>="2027-06-01T00:00:00Z"'

# (b) an integer filter over an epoch-seconds projection the evaluator derives
- {name: available_until_utc_min, query_name: available_until, path: $.available_until_utc,
   op: range, value_type: integer, alias_kind: lower_bound}
#   --resource 'available_until>=1811808000'
```

- (a) reads as the term is published and compares instants. A 0.4.0 buyer refuses the
  specification, so registry and buyers upgrade together.
- (b) keeps a 0.4.0 buyer's other queries working. The evaluator gains a field it
  projects itself, as it does the lifecycle fields, and a buyer writes epoch seconds.
- (c) The storefront publishes a second, integer term. It duplicates a signed listing
  fact and changes what storefronts publish.
- (d) Comparing the published strings. Two spellings of one instant, with and without
  fractional seconds, order wrongly.

Recommended: (a), with the specification's `version` raised, if a released buyer is not
owed a later registry; (b) if it is. Which holds is the release policy's to state
(`docs/guidance/engineering/versioning.md`, "Compatibility is owed to what has been
deployed"). The precedent for a new value type is `registry-discovery`'s "The filter
grammar can compare exact decimal values".

### Q3 — How the schema declares `available_until_utc`

Open: whether the declaration admits only the UTC form storefronts publish, refusing
another offset as the storefront's own reader does; whether it admits null; and whether
a registry upgraded to it could refuse a listing a released storefront republishes.
Recommended: an optional string in the published UTC form, fractional seconds admitted,
never null, which every released storefront's publication satisfies.

### Q4 — The filters' names

Convention, provisional: `max_duration_seconds_min` and `available_until_utc_min`, each
with the bare field name as its query name, as `gpu_count_min` is declared and
`registry-discovery`'s "A bound filter's bare query name is the bound a buyer searches
by" requires. Under Q2 (b) the second filter's query name is the projection's.

## Verification

Provisional levels, for planning and review to confirm. Evaluation, the missing-value
rule and any new value type are unit-tested in the registry, the registry client and the
query language. Publication and query round-trips run as registry application
integration through the typed client.
