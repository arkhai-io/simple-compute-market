## MODIFIED Requirements

### Requirement: Operator-visible acceptance and projection state

The storefront MUST expose enough operator state to distinguish global
negotiation pause from listing state, and a site projection the storefront holds
from one it does not hold, per site and projection family as "Per-site projection
load-state visibility" in the site-capacity specification requires.

System status MUST NOT report a storefront-wide count, such as `resource_count`,
in place of per-site projection state or publication outcome. Whether a site
declares inventory is observed through that site's projection and provisioning's
inventory administration; whether that inventory became sellable is observed
through the storefront's listings and publication diagnostics; an
inventory-import failure is reported by provisioning, which owns the import.
Liveness health MUST remain independent of per-site projection state.

System status MUST report each of the storefront's lifecycle loops by its controller
state, so a loop that has exited or been cancelled is named, and MUST report the outcome
of the most recent publication cycle, whether a timer or an operator's step ran it: when
it finished, whether it completed or failed, and a failure's error. A storefront that
derives listings from site projections MUST report, per site, the latest derivation's
holds and their reasons, including a site whose projection generation its domain refused.

#### Scenario: Storefront is globally paused

- **WHEN** a buyer starts a negotiation while global pause is active
- **THEN** the storefront rejects it with HTTP 503 and a global-pause reason
  until an authenticated operator resumes the process

#### Scenario: A site's projection has not loaded

- **WHEN** a configured site's projection family holds no generation, even if
  another family or site has loaded
- **THEN** system status reports that family's own load state for that site,
  without treating the site as empty

#### Scenario: An operator checks inventory readiness

- **WHEN** an operator reads a storefront's system status
- **THEN** it reports each configured site's projection-family state and
  carries no `resource_count` field

#### Scenario: Publication fails every cycle

- **WHEN** each publication cycle fails, for example because a registry cannot be reached
- **THEN** system status reports the publication loop as running and its last cycle as
  failed with the error, without waiting for an operator to read the logs

#### Scenario: A bare-metal site serves a generation bare metal refuses

- **WHEN** a site's resource-pool projection is held but bare-metal publication refuses its
  generation
- **THEN** system status reports the projection as loaded and reports, for that site, the
  latest derivation's hold with the refusal as its reason

### Requirement: Projection-backed listing candidate derivation

Individual-resource publication consumes `site_resource_pools`, which carries the physical inventory facts required to create a listing for a specific resource. Capacity-oriented publication consumes vertically grouped `site_capacity_buckets`. Grouped capacity is advisory publication input only and is never an allocation target; authoritative reservation admission remains resource-granular inside the provisioning site authority, which applies each pool provider's host requirement.

A storefront SHALL hold one per-site projection state for its process, holding the resource-pool and capacity-bucket projections of every configured site, and every publication source, listing-source check, override status, and status report in the process SHALL read that one state rather than querying a site per listing type. It SHALL load both projections at startup, poll their independent revision-and-digest identities, and replace each cached generation atomically. Refresh failure SHALL retain the last complete generation and mark it stale rather than representing an empty projection; this holds for a refresh of every site at once as for a poll. Topology-sensitive authoritative errors MAY trigger one coalesced drift check of every held family but SHALL NOT automatically retry a state-changing request. A resource-pool generation change observed by polling or a drift check SHALL wake publication.

Projection-backed candidate derivation SHALL be a storefront's only listing-candidate path. A storefront SHALL NOT retain a local, non-projection physical-inventory table as an alternative source, and SHALL NOT expose a configuration option selecting between projection-backed and local derivation.

#### Scenario: One projection refresh fails
- **WHEN** a storefront cannot refresh one site projection after previously loading a complete generation
- **THEN** it retains that generation as stale without replacing the other independently versioned projection

#### Scenario: An operator refreshes every site during an outage
- **WHEN** an operator refreshes every site's projections while one site cannot be reached
- **THEN** that site keeps its last generation, reported stale, and its listings keep deriving from it rather than becoming unknown

#### Scenario: A refused reservation reveals drift
- **WHEN** a site refuses a state-changing request with a topology-sensitive error
- **THEN** the storefront checks every projection family of that site once, does not retry the request, and wakes publication if the resource-pool generation changed

#### Scenario: Listing candidates are derived
- **WHEN** a storefront derives publishable listing candidates
- **THEN** they come from the site projections, with no local-table path available and no configuration option to select one

#### Scenario: Operator seeks to derive from local inventory
- **WHEN** an operator wants a storefront to derive candidates from local inventory
- **THEN** no configuration value produces that behavior

#### Scenario: Grouped capacity is used for publication
- **WHEN** a storefront publishes from the capacity-bucket projection
- **THEN** it treats grouped capacity as advisory publication input and never as an allocation target

### Requirement: Publication runs as a controllable storefront lifecycle loop

The VM storefront, alone or within the combined compute-family storefront, and the
bare-metal storefront MUST each run their domain's publication in their own process as a
timer-driven lifecycle loop on the storefront's lifecycle controller. Each cycle derives
candidates from its configured sources, publishes new listings, refreshes open listings,
closes listings whose source no longer supports them, holds listings whose source is
unresolvable, and reopens listings reconciliation closed, subject to the listing identity
comparison. A change in a site's resource-pool projection generation, observed by the
storefront's per-site projection state, MUST wake the loop.

The loop MUST be held by the storefront's lifecycle pause like every other storefront
loop, without affecting trading. While held, an operator MUST be able to run exactly one
cycle — the cycle the timer runs, not an alternate transition — and to preview one: a
preview MUST report every publish, refresh, close, reopen, and hold the cycle would
perform with its reason, MUST apply none of them, and MUST report the same result when
repeated.

The loop MUST publish through the storefront's own services. A publication command
MUST reach the loop only through the storefront's API and MUST NOT read or write the
storefront's database directly.

The loop MUST build only the publication sources of the domains it publishes. A
storefront may register several domains whose publication runs in different places;
each publisher names the domains it builds, and naming one no registration carries
MUST fail before any source is built.

#### Scenario: A site declares new supply

- **WHEN** a site's projection gains an advertisable pool with enabled declarations and the loop is not held
- **THEN** the storefront publishes the derived listings without any operator command

#### Scenario: The loop is held

- **WHEN** the lifecycle loops are held and a site's projection changes
- **THEN** no listing is published, refreshed, closed, or reopened until an operator runs a cycle or resumes the loops

#### Scenario: An operator previews a cycle

- **WHEN** an operator previews a publication cycle twice without an intervening change
- **THEN** both previews report the same planned actions and reasons, and no listing, binding, or registry publication changed

#### Scenario: A storefront registers another domain beside the one its loop publishes

- **WHEN** a storefront registers both the domain its loop publishes and another whose publication runs elsewhere
- **THEN** each cycle builds only the loop's own domain's sources and completes

#### Scenario: An operator runs one cycle while held

- **WHEN** an operator runs one publication cycle while the loops are held
- **THEN** exactly the actions a preview reported are applied and the loops remain held

#### Scenario: A bare-metal site declares new supply

- **WHEN** a site's projection gains a pool advertising `bare_metal` with an enabled declaration and the bare-metal storefront's loop is not held
- **THEN** the storefront publishes the derived listing without any operator command

#### Scenario: An operator runs the bare-metal publication command

- **WHEN** an operator runs `bare-metal-storefront publish` against a running storefront
- **THEN** the command runs one cycle through the storefront's administrator API and reports it, and opens no database itself

### Requirement: Storefront pool overrides are written against the site's live projection

A storefront MUST expose authenticated administrator operations to replace, read, list, and
delete a pool override. They MUST address the site, pool, and offering mode in the request
body or query rather than the path, and MUST bind them into the signed resource with an
unambiguous encoding. Replacement MUST replace the whole record. Deletion MUST be idempotent.

Before accepting a replacement, the storefront MUST refuse:

- a site it has not configured;
- a structurally invalid record, including a shape outside the domain's vocabulary;
- asking rates its domain cannot read, judged exactly as publication reads them, so an
  accepted write never later holds the pool.

It MUST then fetch that site's resource-pool projection live through the site's
authenticated client, not from its cache:

- a pool absent from the live projection MUST be refused;
- an unreachable site, or a response that does not verify, MUST be refused as retryable,
  with a reason distinct from an absent pool;
- a pool present in the live projection MUST be accepted even when its declarations are
  unresolvable.

A shape no member of the live projection is feasible for MUST NOT cause refusal. The
response MUST report feasibility per shape against that live projection and identify the projection generation it
used. After accepting a write, the storefront MUST cause its held projection of that site to
refresh, without writing the live result into the held state itself, and MUST cause its
publication loop to run. A failed refresh MUST NOT fail the accepted write.

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

#### Scenario: An override states a rate its domain cannot read

- **WHEN** an administrator writes an override whose asking rate names a shape outside
  the domain's vocabulary, a period this version does not accept, or a shape another
  entry already prices
- **THEN** the write is refused without contacting the site

#### Scenario: A bare-metal override is accepted between runs

- **WHEN** an administrator writes an override for a bare-metal pool while the loops are
  not held
- **THEN** the write is stored and reported, the site's held projection is refreshed,
  and the woken publication loop publishes under it

### Requirement: A site whose projection is not held holds its listings

A storefront MUST treat a configured site whose resource-pool projection holds no value as
unknown, not empty: every listing derived from that site MUST be held, neither closed nor
refreshed, until the site's projection holds a value. A site whose projection is not held
MUST NOT yield listings from any other source in its place.

#### Scenario: The storefront starts while a site is unreachable

- **WHEN** a storefront with open listings from a site restarts while that site cannot be
  reached, and a publication cycle runs
- **THEN** those listings stay open, and none is closed as having lost its source

#### Scenario: No site's projection is held

- **WHEN** no configured site's projection holds a value and a publication cycle runs
- **THEN** no listing is derived and no listing is closed

#### Scenario: The site returns

- **WHEN** the unknown site's projection loads
- **THEN** its listings are reconciled against it as usual

#### Scenario: A bare-metal site is unreachable during a publication run

- **GIVEN** open bare-metal listings derived from a site
- **WHEN** a bare-metal publication cycle runs while that site's projection holds no value
- **THEN** those listings stay open and unchanged, and the cycle reports the site as unknown
- **AND** every other configured site is reconciled as usual

### Requirement: Bare-metal opening rechecks its listing against its source

Whenever a bare-metal storefront rechecks a listing against its source, it MUST re-derive
the listing's shape and region from the resource-pool projection it holds for the
listing's own site, at its bound pool and Physical Resource, after accepting that
generation's bare-metal views as publication accepts them, and MUST NOT fetch that
projection from the site to do so. It MUST refuse with a declared-match reason when any of
these hold:

- the shape digest differs from the binding's;
- the region differs from the published region;
- the Physical Resource is absent or disabled.

It MUST refuse with the availability reason when the held projection's bare-metal view
shows the Physical Resource unavailable, and as retryable when the projection it holds for
the site has no value, when that generation's bare-metal views are refused, or when no site
authority is configured. Availability read from a held projection may lag the site by up to
one poll; admission at the site remains authoritative.

#### Scenario: A declaration shrinks beneath its listing

- **WHEN** a buyer opens a negotiation on a bare-metal listing whose Physical Resource now
  declares fewer GPUs than it published
- **THEN** the opening is refused with a declared-match reason

#### Scenario: The Physical Resource is taken

- **WHEN** a buyer opens a negotiation on a bare-metal listing whose Physical Resource is
  reserved by another deal, as the held projection shows
- **THEN** the opening is refused with the availability reason

#### Scenario: The site's projection is not held

- **WHEN** a buyer opens a negotiation on a bare-metal listing whose site's projection the
  storefront does not hold
- **THEN** the opening is refused as retryable, and the site is not called

#### Scenario: The held generation is refused

- **WHEN** a buyer opens a negotiation on a bare-metal listing whose site's held generation
  carries a bare-metal view naming a different pool than its container
- **THEN** the opening is refused as retryable

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
replace the storefront's configured publication clauses for that site's pool as a
whole. Each of its duration bounds replaces its configured counterpart independently,
as configuration overlays do, and the effective pair a listing would publish MUST be
ordered. A write whose minimum exceeds the effective maximum MUST be refused. Because
configuration can change after a write, publication MUST also check the effective
pair, holding the pool's listings and reporting the conflict rather than publishing
an unordered pair or failing the cycle.

A bare-metal storefront's command line MUST offer the same replace, read, list, and delete
operations through its administrator API, with the offering mode never defaulted, and MUST
NOT read or write its database to do so.

A stored bare-metal override that cannot be read MUST hold its pool's listings, neither
publishing, closing, nor refreshing them, and MUST be reported; configuration MUST NOT speak
for a pool whose override exists but cannot be read.

A bare-metal storefront's override status MUST be judged against the resource-pool projection
it holds for the override's site. A site whose projection the storefront does not hold is
`unknown`. The storefront MUST NOT persist a projection generation for override status.

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

#### Scenario: An override minimum exceeds the configured maximum

- **WHEN** an operator writes a bare-metal override stating only a minimum duration
  above the storefront's configured maximum
- **THEN** the write is refused, naming the effective maximum

#### Scenario: Configuration falls below an accepted override

- **WHEN** an override's minimum was accepted and the configured maximum is later set
  below it
- **THEN** the next publication cycle holds that pool's listings and reports the
  conflict

#### Scenario: A stored bare-metal override cannot be read

- **WHEN** a publication cycle finds a stored override for a pool that cannot be decoded
  or read in the bare-metal vocabulary
- **THEN** the pool's listings are held rather than published under configured terms,
  and the cycle reports why

#### Scenario: Status while a site's projection is held

- **WHEN** a bare-metal storefront holds a projection of the override's site that contains
  the override's pool
- **THEN** the override is reported as applied, and as orphaned once a held generation no
  longer contains the pool

#### Scenario: Publication runs from the command

- **WHEN** an operator runs `bare-metal-storefront publish`, which runs one cycle through the
  storefront's administrator API, while the storefront holds a projection of the override's
  site containing its pool
- **THEN** the running storefront reports the override as applied, with no generation
  recorded for the purpose

#### Scenario: Status before the first run

- **WHEN** a bare-metal storefront reports override status before it holds a projection of
  the override's site, including just after a restart
- **THEN** the override is reported as unknown

## ADDED Requirements

### Requirement: A storefront that cannot publish refuses to start

A storefront that publishes listings MUST refuse to start, naming each problem, when its
publication cannot be configured: no settlement publication clause; registry discovery
enabled with no registry, or a registry without an authority pin; or, for a storefront
whose domain requires a lease bound, no positive maximum lease duration. A storefront that
only services deals already accepted is not a supported deployment.

#### Scenario: A bare-metal storefront has no registry

- **WHEN** a bare-metal storefront starts with no `[registry].urls`
- **THEN** it refuses to start, naming the missing registry, and starts no loop

#### Scenario: A VM storefront has no publication clauses

- **WHEN** a VM storefront starts with an empty `[pricing].settlements`
- **THEN** it refuses to start, naming the missing clauses

#### Scenario: A bare-metal storefront has no maximum lease duration

- **WHEN** a bare-metal storefront starts with `[pricing].default_max_duration_seconds`
  absent or zero
- **THEN** it refuses to start, naming the missing bound

### Requirement: An Alkahest listing advertises its release conditions

A listing that publishes an Alkahest settlement option MUST advertise, per chain it
publishes on, the release condition its escrow will use: the arbiter and its demand data,
derived by the Alkahest mechanism from the seller's `[Settlement.alkahest]` policy, the
seller wallet, and the chain's address book, identically for every domain that composes
Alkahest. A domain MUST declare which release models it can deliver, and a storefront MUST
refuse to start with a configured release model its domain cannot deliver.

#### Scenario: A bare-metal listing offers Alkahest settlement

- **WHEN** a bare-metal storefront publishes a listing with an Alkahest option on a chain,
  under the default release policy
- **THEN** the listing advertises the recipient arbiter paying the seller's wallet on that
  chain, as a VM listing under the same policy does

#### Scenario: A domain is configured for a release model it cannot deliver

- **WHEN** a bare-metal storefront starts with `[Settlement.alkahest]` configured as
  interruptible
- **THEN** it refuses to start, naming the release model
