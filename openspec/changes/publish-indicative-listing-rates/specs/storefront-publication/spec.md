## ADDED Requirements

### Requirement: A listing's asking rate is declared per shape

A compute listing MAY publish the rate its seller is asking for the listing's shape,
as an `asking_rate` object on the published listing resource carrying `amount`,
`asset`, and `period`. The rate prices one listing shape: listings of different
shapes from the same pool carry independently declared rates, and a rate MUST NOT be
decomposed per capacity dimension.

The rate MUST resolve through this precedence, highest first:

1. The storefront's site-scoped pool override for the listing's site, pool, and
   offering mode, when it states asking rates.
2. Otherwise, the `asking_rates` declaration on the Resource Pool the listing derives
   from, read from the site's projection.
3. Otherwise, no asking rate.

Each tier states rates as a list of entries, each naming the capability shape it
prices. An entry applies to the listing whose shape has the same canonical digest.
An override's list MUST replace the pool's list as a whole; an empty override list
MUST be accepted and MUST mean that no listing of that pool publishes an asking rate.
An override is available for a pool at any site the storefront publishes for.

No storefront configuration default MAY supply an asking rate. Every published rate
is either the declaration of the listing's origin pool or an explicit override for
that site and pool, so a storefront publishing for several seller sites never
advertises its own blanket price as another site's.

A listing whose shape no applicable entry prices MUST publish normally with no
asking rate. An entry naming a shape the pool does not publish has no effect and MUST
be reported in the storefront's system status.

A storefront MUST publish only a complete rate: all three fields present, `amount`
exact positive decimal text without an exponent, `asset` a trimmed non-empty opaque
identifier, and `period` a unit this version accepts, which is `hour` alone.

The asking rate MUST NOT participate in any shape digest or derivation identity.

#### Scenario: A pool prices each of its shapes

- **WHEN** a pool publishes a 1-GPU and an 8-GPU shape and declares a rate for each
- **THEN** each listing publishes the rate declared for its own shape

#### Scenario: A shape is priced nowhere

- **WHEN** a pool publishes a shape that neither its declaration nor an override prices
- **THEN** that listing publishes normally with no asking rate

#### Scenario: The storefront overrides a remote site's rate

- **WHEN** the storefront's override for a pool at a site other than its first
  configured site states an asking rate for one of the pool's shapes
- **THEN** that listing publishes the override's rate and not the pool's declaration

#### Scenario: The storefront withholds every rate

- **WHEN** the storefront's override for a pool states an empty asking-rate list
- **THEN** no listing of that pool publishes an asking rate, whatever the pool declares

#### Scenario: A storefront configures pricing defaults

- **WHEN** a pool declares no asking rates, no override states any, and the storefront
  configures negotiation-floor or settlement defaults
- **THEN** no listing of that pool publishes an asking rate

### Requirement: A malformed asking-rate declaration holds its pool

A pool `asking_rates` declaration or an override's asking rates that the storefront
cannot read MUST hold every listing of that pool — neither published, closed, nor
refreshed — and MUST be reported in the storefront's system status. It is unreadable
when an entry's shape is outside the offering mode's vocabulary, when two entries
price the same shape, or when any entry's amount, asset, or period is invalid.

An unreadable declaration MUST NOT fall through to a lower tier or to no rate. An
absent declaration and a malformed one are different: falling through would silently
drop a price the seller believes they advertised.

#### Scenario: A declaration names an unknown shape field

- **WHEN** a pool's asking-rate entry names a shape field the offering mode does not
  define
- **THEN** that pool's listings are held and the storefront reports the declaration
  unreadable

#### Scenario: A rate uses an unsupported period

- **WHEN** a declaration or override quotes a rate per a period other than `hour`
- **THEN** that pool's listings are held rather than published with or without the rate

#### Scenario: Two entries price one shape

- **WHEN** two entries in one list name shapes with the same canonical digest
- **THEN** that pool's listings are held rather than either rate being chosen

### Requirement: The asking rate is a listing attribute, not a settlement option rate

No settlement option, escrow term, or accepted obligation MAY be constructed from a
published asking rate, and an agreed amount MUST remain absent rather than zero until
one is negotiated. This constrains what the system builds from the number, not how
far a buyer should trust it: like every published field, an asking rate is a seller
assertion, and nothing in the marketplace verifies any of them.

A listing MAY publish an asking rate and also advertise a rate inside a settlement
carrier — an accepted escrow's rate slots or a settlement option's rates. The two
MUST be treated as independent carriers: a mechanism rate governs what the runtime
constructs for that mechanism, and the asking rate governs nothing. They MUST NOT be
required to agree, and where they disagree neither corrects the other.

Neither may be derived from the other. A storefront MUST NOT populate an asking rate
from a rate advertised in a settlement carrier, and MUST NOT write an asking rate
into a settlement option, escrow term, or obligation. Deriving it in either direction
would make the field's provenance unreadable, and it is undefinable for a listing
advertising escrows in several assets.

A storefront MAY derive an asking rate from a seller's negotiation-side rate
structure where the seller's declared policy says so, once such a structure exists;
the structure does not replace, subsume, or reinterpret the published asking rate.

A listing whose only settlement option is under a mechanism declining scalar
participation carries no mechanism rate. Such a listing MUST still be able to publish
an asking rate. Asking rates MUST be available to backed and unbacked listings alike.

#### Scenario: A deal is agreed against a listing carrying an asking rate

- **WHEN** a negotiation concludes against a listing publishing an asking rate
- **THEN** the agreed amount comes from the negotiation
- **AND** the published asking rate does not constrain or supply it

#### Scenario: A listing carries both an asking rate and an escrow rate

- **WHEN** publication builds a candidate whose shape has an asking rate and whose
  settlement configuration advertises escrow rates
- **THEN** both appear in the published listing
- **AND** the asking rate is not populated from, reconciled against, or written into
  any settlement carrier

#### Scenario: The two published rates disagree

- **WHEN** a listing's asking rate differs from the rate advertised in its settlement
  carrier
- **THEN** publication is not refused on that ground

#### Scenario: A rateless mechanism carries a declared asking rate

- **WHEN** a listing's only settlement option is under a mechanism declining scalar
  participation and its shape has an asking rate
- **THEN** the listing publishes the asking rate and the option remains rateless

### Requirement: An asking-rate change refreshes the listing in place

An asking rate is a term of sale under the requirement that a listing's identity is
the physical resource it offers. Changing the amount, asset, or period that applies
to a listing MUST refresh the listing in place at the storefront and every registry,
retaining its identity and derivation key. Removing the rate that applies to a
listing MUST refresh it without an asking rate; it remains discoverable and becomes
absent from rate-bounded queries.

A rate change MUST NOT close a listing and publish it under a new identity.

#### Scenario: A seller changes a declared rate

- **WHEN** the rate declared for a published shape changes
- **THEN** the listing is refreshed carrying the new rate under its existing identity

#### Scenario: A seller removes a declared rate

- **WHEN** the entry pricing a published shape is removed
- **THEN** the listing is refreshed without an asking rate
- **AND** it remains discoverable while absent from rate-bounded queries

#### Scenario: The storefront overrides a declared rate

- **WHEN** an override starts stating a different rate for a shape the pool already
  prices
- **THEN** the listing is refreshed carrying the override's rate under its existing
  identity

### Requirement: Bare metal joins the site-scoped pool-override store

A bare-metal storefront MUST contribute a market vocabulary for the `bare_metal` offering
mode to the site-scoped pool-override store, and MUST serve the same authenticated
administrator operations, through the same signed-resource contract, as every storefront
that serves overrides.

The bare-metal vocabulary is:

- settlement clauses;
- the terms `min_duration_seconds` and `max_duration_seconds`;
- asking rates, resolved as every compute listing's asking rate is.

A bare-metal override MUST NOT state listing shapes. An override's settlement clauses
replace the storefront's configured publication clauses for that site's pool, and its
duration bounds replace the configured bounds.

A bare-metal storefront's command line MUST offer the same replace, read, list, and delete
operations through its administrator API, with the offering mode never defaulted, and MUST
NOT read or write its database to do so.

A bare-metal storefront MUST record durably, for each site, the last resource-pool projection
generation a publication run accepted, whichever process ran it, and its override status MUST
be judged against that generation. A site with no recorded generation is `unknown`.

#### Scenario: A bare-metal override is written

- **WHEN** an operator writes an override for a pool at a configured site in the
  `bare_metal` offering mode
- **THEN** bare metal validates it, and it applies only to that site's pool's bare-metal
  listings

#### Scenario: A bare-metal override states a shape

- **WHEN** an operator writes a `bare_metal` override that states listing shapes
- **THEN** the write is refused without contacting the site

#### Scenario: An operator writes a bare-metal override from the command line

- **WHEN** an operator runs the bare-metal storefront's override command with a record for
  the `bare_metal` mode
- **THEN** the command sends it through the administrator API, which checks it against
  the site's live projection, and prints the stored override

#### Scenario: Publication runs from the command

- **WHEN** an operator runs `bare-metal-storefront publish` in its own process and the run
  accepts a site's generation holding the override's pool
- **THEN** the running storefront reports the override as applied

#### Scenario: Status before the first run

- **WHEN** a bare-metal storefront reports override status before any publication run has
  accepted a generation for the override's site, including after a restart that follows
  no run
- **THEN** the override is reported as unknown

## MODIFIED Requirements

### Requirement: Storefront pool overrides are written against the site's live projection

A storefront MUST expose authenticated administrator operations to replace, read, list, and
delete a pool override. They MUST address the site, pool, and offering mode in the request
body or query rather than the path, and MUST bind them into the signed resource with an
unambiguous encoding. Replacement MUST replace the whole record. Deletion MUST be idempotent.

Before accepting a replacement, the storefront MUST refuse:

- a site it has not configured;
- a structurally invalid record, including a shape outside the domain's vocabulary.

It MUST then fetch that site's resource-pool projection live through the site's
authenticated client, not from its cache:

- a pool absent from the live projection MUST be refused;
- an unreachable site, or a response that does not verify, MUST be refused as retryable,
  with a reason distinct from an absent pool;
- a pool present in the live projection MUST be accepted even when its declarations are
  unresolvable.

A shape no member of the live projection is feasible for MUST NOT cause refusal. The
response MUST report feasibility per shape against that live projection and identify the projection generation it
used. After accepting a write, a storefront that caches site projections MUST cause its
cached projection of that site to refresh, without writing the live result into the cache
itself, and a storefront that runs a publication loop MUST cause it to run. A failed refresh
MUST NOT fail the accepted write. A storefront whose publication is operator-invoked applies
an accepted write at its next publication run.

#### Scenario: The pool is unknown to the site

- **WHEN** an administrator writes an override for a pool the site's live projection does
  not contain, while the storefront's cached projection still lists it
- **THEN** the write is refused and nothing is stored

#### Scenario: The site is unreachable

- **WHEN** an administrator writes an override while the named site cannot be reached
- **THEN** the write is refused as retryable, naming the site as unavailable rather than the
  pool as unknown

#### Scenario: An override's shape is feasible nowhere

- **WHEN** an administrator writes an override whose only shape no member of the live
  projection is feasible for
- **THEN** the override is stored, the response reports the shape as infeasible, and
  the next publication cycle publishes no listing for it

#### Scenario: A shape outside the vocabulary

- **WHEN** an administrator writes an override whose shape names a family or field the
  domain does not define
- **THEN** the write is refused without contacting the site

#### Scenario: A bare-metal override is accepted between runs

- **WHEN** an administrator writes an override for a bare-metal pool while no publication
  run is in progress
- **THEN** the write is stored and reported without starting a run, and the next
  operator-invoked run publishes under it
