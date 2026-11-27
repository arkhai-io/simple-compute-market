## Why

A compute listing states how long its capacity lasts in two listing-level terms:
`max_duration_seconds`, the longest deal from its start, and `available_until_utc`, the
last instant any lease may end. A buyer sees both before approval and its signed horizon
is checked against them, but cannot narrow a registry query by either. The compute filter
specification declares `max_duration_seconds` and filters neither bound, and it does not
declare `available_until_utc`, which both compute storefronts publish
(`core/registry/src/core_registry/filter-spec.yaml`).

The filter grammar cannot express the two filters as it stands. It has no value type for
an instant, and its evaluator reads a null as an absent value, so a listing that states no
relative limit cannot be told from one that states nothing
(`core/registry/src/core_registry/api/filter_spec.py`,
`core/registry/src/core_registry/api/filter_eval.py`).

## What Changes

- The compute filter specification declares `available_until_utc` beside
  `max_duration_seconds`.
- It exposes a lower-bound filter on each, so a buyer's resource query can ask for
  capacity lasting at least a duration and available until at least an instant.
- The filter grammar gains what those filters need: how an instant is compared, and what
  a listing that states no bound answers. Both are open in the design, with what a
  released buyer is owed when the specification changes.

## Capabilities

### Modified Capabilities

- `registry-discovery`: the two bound filters, the schema's declaration of
  `available_until_utc`, and the grammar extension.
- `cli-query-language`: the comparison grammar, if the design adds a value type a buyer
  writes.

### New Capabilities

None.

## Non-Goals

- Finding an option by class, and how buyers select: `discover-open-ended-compute-listings`.
- Computing whether a deal of a given length is admissible. The seller resolves the
  horizon from both bounds at the agreed start, and the buyer checks the signed horizon;
  a filter narrows candidates and promises nothing.
- A stored class or a summary of a listing's options.
- Changing how storefronts resolve or publish either bound.
- Indexed execution of the filters: `index-registry-filters`.

## Dependencies and Related Changes

- Nothing gates this change.
- `discover-open-ended-compute-listings` owns the buyer half of discovery. The two changes
  share no code.
- `publish-shape-bounds` and `drop-escrow-from-shared-wire` edit the compute filter
  specification later. Whichever lands second reverifies against the other.
  `publish-shape-bounds` declares a listing term there and adds no filter; a filter over
  a shape constraint, if one is ever added, takes this change's answer to what a
  listing that states no bound answers (its design, D4).

## Impact

`core/registry` (the compute filter specification, the filter model and evaluator),
`core/registry-client` (the resource-query compiler), `core/src/market_core/query_dsl.py`
if the grammar gains a value type, and `docs/buyer-quickstart.md`. The registry's served
filter specification changes, which every buyer reads before a resource query.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- The bound filters, the declared term and their missing-value rule:
  `openspec/specs/registry-discovery/spec.md` and its architecture companion.
- A grammar value type, if one is added: `openspec/specs/cli-query-language/spec.md`.
- How a buyer filters by a seller's bounds: `docs/buyer-quickstart.md`.
