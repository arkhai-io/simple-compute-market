## Why

Capacity backing is a declared property of a Resource Pool and an immutable property
of every listing binding, but what backing *means* is not held anywhere. Each
consumer decides it for itself by comparing the `capacity_backing` label:

- the pool declaration rules branch on the label (a backed pool advertises only what
  it delivers; an unbacked pool delivers nothing);
- VM publication, reconciliation, negotiation, the source check, settlement option
  admissibility, and fulfillment each branch on it, or on the binding class it
  selects;
- bare metal assumes every listing is backed — a `Literal["backed"]` listing field,
  hard-coded binding writes, and a refusal of unbacked pools;
- the two compute domains disagree where they handle the same concern: VM refuses to
  refresh or reopen a listing whose binding's backing disagrees with its source's,
  while bare metal treats backing as a term and would refresh it in place; VM
  separates source reconciliation from capacity-availability reconciliation by an
  explicit backed-only scope, while bare metal folds both into its per-resource
  classes.

`unbacked-bare-metal-listings` needs bare metal to handle unbacked supply. Doing that
by adding bare-metal branches beside VM's would duplicate every decision a second
time and leave the divergences in place. This change first gathers backing's meaning
into one delegate and moves both domains onto it.

## What Changes

- A backing delegate owns every decision that differs between backed and unbacked
  supply. The pool's declared `capacity_backing` label selects it; the label remains
  the durable and published value in pool declarations, listing bindings, the
  resource-pool projection, and the published listing.
- Every switch on backing moves into the delegate: callers ask the delegate to act
  and never compare the label or test the binding class themselves.
- Where VM and bare metal handle a backing concern differently, the behaviour is
  unified as it moves. Backing is not a domain concern, so no domain keeps its own
  variant.
- The delegate lives in a repository-wide kit beside the vocabulary it interprets,
  not in core and not in the compute family: it applies to every market whose
  listings are admitted against capacity an authority holds — physical capacity for
  VM and bare metal, quota for API credits — and to none whose listings are not.
- Compute-family code that consumes backing — the site's publication views and both
  compute storefronts' candidate derivation — reaches it only through the delegate.

The change preserves behaviour except where a divergence is unified. Bare metal still
publishes no unbacked listing when it lands; `unbacked-bare-metal-listings` lifts that.

## Capabilities

### Modified Capabilities

- `resource-pool-management`: one backing delegate, selected by the declared label,
  makes every decision that differs by backing; the shared resolver returns it.
- `storefront-publication`: every capacity effect passes the binding delegate's
  admission guard and a refused admission is a conflict; one backing comparison runs
  first on every refresh, reopen, and source check; every domain declares, per
  settlement stage, whether it delivers through capacity.
- `market-composition`: the kit's one `PublicationBinding` carries the delegate, every
  domain builds it from the durable listing binding, and every capacity effect goes
  through the kit's capacity runtime.
- `api-credits`: listings record a durable binding and read their pool's declared
  backing, a listing-source check joins the negotiation runtime, the quota guard
  applies only where availability bounds the listing, and a database without listing
  bindings is refused.

### New Capabilities

None.

## Non-Goals

- A pluggable interface for a third backing category. Its semantics are not defined,
  so an interface written now would encode guesses. Encapsulation keeps that
  extraction local: when a category is defined, the delegate splits into
  implementations without touching a caller.
- Any new backing value, or any change to the label's wire, persistence, or published
  form.
- Unbacked bare-metal listings, which are `unbacked-bare-metal-listings`'.
- Unifying VM and bare-metal publication beyond backing. Shape origin, cardinality,
  and listing codecs are genuine domain differences. How each storefront obtains its
  site projections is owned by `kit-owned-listing-and-fulfillment-lifecycles` and
  `resolve-compute-family-findings`. The duplicated publication pipeline — candidate
  classification, holds, the identity and term comparison, and the shape of the
  reconciliation passes — has no owner and is recorded as such in the change index.

## Impact

- `kit/resource-pools-contracts`: the delegate and its selection from the label.
- `kit/capacity-publication`: one `PublicationBinding` carrying the delegate, the shared
  backing comparison, and `CapacityEffects`, the guarded reserve, commit, release, and
  lease truncation that `CapacityRuntime` composes and bare metal composes over its own
  aggregate client.
- `kit/resource-pools` and the compute provisioning service: declaration validation
  and publication views through the delegate.
- The VM storefront and `domains/vms/listings`; the bare-metal domain and storefront;
  the API-credit domain, storefront, and service, which move onto the delegate in full.
  API credits records a durable listing binding per listing, keyed by the listing, and
  two of its defects in the files this change rewrites are fixed: the CLI's listing
  service construction and the publish route dropping submitted settlement clauses.
- `kit/site-client`'s resource-pool fixture, which validates its label through the
  delegate registry.
- `core/storefront`'s listing binding, which validates its label through the delegate
  rather than its own copy of the vocabulary.
- No wire, database, or deployment break is intended. Each unified divergence is a
  behaviour change recorded in its decision.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — kit areas: the backing delegate's home and
      the scope it serves.
- [x] Existing subsystem specification — `resource-pool-management`,
      `storefront-publication`, `market-composition`, and `api-credits`, and their
      architecture companions.
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- The backing delegate, its home beside the label, and the scope of markets it serves →
  `ARCHITECTURE.md`, "Kit areas", and `resource-pool-management`'s companion,
  "Advertisement, delivery, and backing".
- One `PublicationBinding` carrying the delegate, and `CapacityEffects` as the one
  guarded boundary for capacity effects → `ARCHITECTURE.md`, "Capacity publication and
  multi-domain storefront composition", and `market-composition`'s spec.
- The backing comparison, reconciliation scope, and settlement admissibility rules →
  `storefront-publication`'s spec and its companion, "Reconciliation".
- `fulfils_through_capacity` as the stage-table convention each domain reads →
  `market-composition`'s companion, "Settlement runtime composition".
- API credits' durable binding, keyed by listing, its source check, and its
  fresh-database refusal → `api-credits`' spec and its companion, "Explicit database
  reset".

## Dependencies

- **Prerequisite of `unbacked-bare-metal-listings`**, which resolves bare metal's
  unbacked pools through this delegate.
- No blocking dependency. It borders, and must be reconciled with in planning:
  `inject-site-pool-authority` (moves the pool declaration readers into
  `kit/resource-pools-contracts`), `kit-owned-listing-and-fulfillment-lifecycles`
  (moves the seller listing lifecycle into `kit/capacity-publication`),
  `resolve-compute-family-findings`, and `align-package-paths-with-layers`.
- Must pass `make check-architecture`, which the archived `enforce-package-layers`
  added: `kit/resource-pools-contracts` carries a package allowlist of
  `arkhai-kit-capability-shape` and `pydantic`, so the delegate may add no
  dependency.
