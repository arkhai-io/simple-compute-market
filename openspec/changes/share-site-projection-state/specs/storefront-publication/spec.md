## MODIFIED Requirements

### Requirement: Publication runs as a controllable storefront lifecycle loop

The VM and bare-metal storefronts, alone or within the combined compute-family
storefront, MUST each run publication in their own process as a timer-driven lifecycle
loop on the storefront's lifecycle controller. Each cycle derives candidates from its configured sources, publishes new
listings, refreshes open listings, closes listings whose source no longer supports
them, holds listings whose source is unresolvable, and reopens listings reconciliation
closed, subject to the listing identity comparison. A change in a site's resource-pool
projection generation, read from the per-site projection state the storefront holds,
MUST wake the loop.

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
used. After accepting a write, a storefront that caches site projections MUST cause its
cached projection of that site to refresh, without writing the live result into the cache
itself, and its publication loop MUST be caused to run. A failed refresh MUST NOT fail the
accepted write.

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

Whenever a bare-metal storefront rechecks a listing against its source, it MUST
re-derive the listing's shape and region from the resource-pool projection it holds for
the listing's own site, at its bound pool and Physical Resource, and MUST NOT fetch that
projection from the site to do so. It MUST refuse with a declared-match
reason when any of these hold:

- the shape digest differs from the binding's;
- the region differs from the published region;
- the Physical Resource is absent or disabled.

It MUST refuse with the availability reason when the site's capacity snapshot shows the
Physical Resource taken, and as retryable when the projection it holds for the site has
no value, or no site authority is configured.

#### Scenario: A declaration shrinks beneath its listing

- **WHEN** a buyer opens a negotiation on a bare-metal listing whose Physical Resource now
  declares fewer GPUs than it published
- **THEN** the opening is refused with a declared-match reason

#### Scenario: The Physical Resource is taken

- **WHEN** a buyer opens a negotiation on a bare-metal listing whose Physical Resource is
  reserved by another deal
- **THEN** the opening is refused with the availability reason

#### Scenario: The site's projection is not held

- **WHEN** a buyer opens a negotiation on a bare-metal listing whose site's projection the
  storefront does not hold
- **THEN** the opening is refused as retryable, and the site is not called
