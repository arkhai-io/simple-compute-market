## ADDED Requirements

### Requirement: A listing's origin site is not its admission authority

Every storefront listing binding MUST record the site the listing originated from
and, separately, whether an admission authority stands behind it. The origin site
is populated for every listing including an unbacked one, because an unbacked
listing is projected from a site like any other.

The durable binding MUST carry an explicit backing discriminator rather than
encoding the category as an absent site or an absent field. The discriminator MUST
be covered by the binding's immutability guarantee so a listing cannot change
category after binding, and a binding written without it MUST be refused rather
than classified by a default.

Publication provenance MUST separate common listing identity — origin site,
offering mode, and source declaration identity — from admission provenance. Only
operations that reserve, commit, release, schedule, or dispatch MUST require the
capacity-backed binding variant; operations that compare, copy, or carry listing
identity MUST accept either.

#### Scenario: An unbacked listing binds

- **WHEN** a storefront publishes a listing derived from a pool declaring no admission authority
- **THEN** the durable binding records the origin site, the offering mode, the source declaration identity, and an explicit unbacked discriminator
- **AND** the binding is otherwise indistinguishable in shape from a capacity-backed listing's

#### Scenario: A binding names no backing

- **WHEN** a writer inserts a listing binding without a backing discriminator
- **THEN** the insert is refused rather than recorded as either value

#### Scenario: A bound listing's backing is changed

- **WHEN** a writer attempts to change a recorded binding's backing discriminator
- **THEN** the change is refused and the binding is unchanged

#### Scenario: An unbacked listing enters a negotiation

- **WHEN** a buyer opens a negotiation against an unbacked listing
- **THEN** the durable listing binding is copied to the negotiation thread with its origin site, offering mode, domain identity, and contract version
- **AND** no step of the negotiation lifecycle refuses the listing for lacking an admission authority

#### Scenario: A capacity operation receives an unbacked listing

- **WHEN** a reservation, commit, release, scheduling, or dispatch operation is attempted for an unbacked listing
- **THEN** the operation is refused before any effect, so no reservation record is created with no authority behind it

### Requirement: Backing is declared by the projected pool

A storefront MUST resolve a listing's backing from the declared value on the
projected pool it derives from, reading that projected tag live at each point of
need and never caching it as storefront-local inventory. The backing discriminator
recorded on a listing's durable binding is derived from that value at publication
and is immutable; it is a storefront fact about a bound listing rather than a cached
copy of a site fact, and the two MUST NOT be conflated. Backing MUST NOT be inferred
from absent capacity data, an empty projection, or a stale generation.

A storefront MUST judge a projection's declarations jointly, per site and per
projection generation. A generation that projects pools, none of which carries either
the backing or the advertisement declaration, comes from a producer that predates them:
every pool in it MUST resolve as capacity-backed with delivery authorization serving
as advertisement authorization, reproducing the contract that applied before the
declarations existed, under one compatibility rule that is logged and reported in
the storefront's system status. That rule is retained until a future change acquires
a reliable signal that no producer relies on it; self-hosted sites may lag without
bound, so no release count is a meaningful removal condition.

In any other generation, a pool whose declarations are absent, malformed, or
violate a cross-declaration rule is unresolvable. An unresolvable pool MUST yield no
new listing candidates, and its existing listings MUST be neither closed nor
refreshed until it resolves, because an unknown declaration is not a withdrawn one.
Each unresolvable pool MUST be reported in the storefront's system status with the
reasons it could not be resolved.

#### Scenario: A producer predates the declarations

- **WHEN** a storefront ingests a site's projection generation in which no pool declares backing or advertisement authorization
- **THEN** every pool resolves as capacity-backed with delivery authorization serving as advertisement authorization
- **AND** the compatibility rule is logged and reported in system status
- **AND** listings previously derived from that site continue to publish unchanged

#### Scenario: A generation projects no pools

- **WHEN** a site's projection generation contains no pools
- **THEN** it is not read under the compatibility rule, and system status does not report the site as an older producer

#### Scenario: A producer omits a declaration for one pool

- **WHEN** a projection generation declares backing and advertisement for some pools and omits them for another it projects
- **THEN** the omitting pool is unresolvable rather than resolving to either value

#### Scenario: A producer emits only one of the two declarations

- **WHEN** a projection generation carries a backing declaration on some pool but no advertisement declaration on any
- **THEN** the generation is not read as an older producer's, and every pool lacking either declaration is unresolvable

#### Scenario: A declared backing value is unrecognized

- **WHEN** a projected pool declares a backing value outside the accepted set
- **THEN** that pool is unresolvable rather than falling back to a structural default

#### Scenario: An unresolvable pool has published listings

- **WHEN** a pool with open listings becomes unresolvable
- **THEN** no new listing is derived from it, its existing listings stay as they are, and system status names the pool and its problems
- **AND** when the pool resolves again its listings are reconciled against the resolved declarations

### Requirement: A listing advertises only a mode its pool authorizes

A listing a storefront derives from a site's resource-pool projection MUST offer only
an offering mode its Resource Pool declares advertisable, whether the listing is
capacity-backed or unbacked. The listing's offering mode continues to resolve from
the frozen contribution registration, and the public offer's mode MUST continue to
equal the recorded offering mode. Bare-metal publication derives its candidates from
the site's capacity snapshot rather than that projection, and reads no pool
declaration.

The pool's delivery authorization MUST continue to be rechecked at reservation,
scheduling, and provider dispatch, and those rechecks apply only to capacity-backed
listings because only they reach those layers.

#### Scenario: A pool authorizes advertisement but not delivery

- **WHEN** an unbacked pool declares a mode advertisable that its provider configuration does not prove deliverable
- **THEN** a listing derived from that pool may offer that mode
- **AND** no reservation, scheduling, or dispatch path is reachable for that listing

#### Scenario: A listing offers a mode its pool does not authorize

- **WHEN** candidate derivation would produce a listing offering a mode its pool does not declare advertisable
- **THEN** the candidate is refused rather than published

### Requirement: A listing's identity is the physical resource it offers

A listing's identity MUST be the physical resource it offers: the supply it draws
from (site, and pool or Physical Resource), what the resource is (offering mode,
resource type and subtype, and categorical attributes), where it is (region), and how
much of it one listing offers (the enumerated quantity and every other declared
dimension the listing publishes). Every other published field — price and pricing
hints, settlement options, maximum duration, and service level — is a term of sale.

A listing commits only to the fields it publishes. A field a listing does not publish
is no commitment. Reconciliation MUST NOT add an identity field to a listing that did
not publish one, because that would make a new commitment under an existing listing
identity.

A change to a term of sale MUST update the listing in place and retain its identity. A
change to an identity field MUST NOT be applied to an existing listing in place. Where
the listing's derivation identity captures the changed field, the existing listing
closes and a newly derived listing is published. Where it does not, the existing
listing MUST close and MUST NOT reopen while its published value differs from its
source, and the refusal MUST be logged naming the source and the differing fields.

Capacity backing is not an identity field under this requirement: it is recorded on
the binding at creation and governed by the backing requirements.

#### Scenario: A term of sale changes

- **WHEN** the price or settlement options behind an open listing change
- **THEN** the listing is updated in place at the storefront and every registry, and retains its listing identity and derivation key

#### Scenario: An identity field outside derivation identity changes

- **WHEN** a declaration behind an open listing changes a published categorical attribute that the listing's derivation identity does not capture
- **THEN** the listing closes and is not reopened while the published value differs from the declaration
- **AND** the refusal is logged naming the declaration and the differing attribute

#### Scenario: A newly published field is absent from an existing listing

- **WHEN** publication begins emitting an identity field that an existing listing did not publish
- **THEN** the existing listing is neither closed nor updated to carry the field, because it made no commitment about it
- **AND** listings published afterwards carry the field

#### Scenario: A pool returns with the opposite backing

- **WHEN** a site's pool is recreated under an existing pool ID with backing opposite to the discriminator on listings bound from it
- **THEN** those listings close and are not reopened, and the refusal is logged naming the pool
- **AND** no replacement listing binds under their derivation identity

### Requirement: Source publication and capacity availability reconcile separately

Source-publication reconciliation MUST apply to every listing regardless of backing:
a removed or disabled source declaration MUST close the listings derived from it, and
a changed source declaration MUST be reflected in what is published according to the
listing identity requirement. A projected pool that declares itself disabled is a
disabled source. Source-publication reconciliation MUST re-derive open listings and
compare them with what is published, so that a change to a term of sale reaches an open
listing.

Every path that reopens a listing MUST apply the same comparison first: a listing whose
published identity differs from its source, or whose binding's backing disagrees with
its source's, MUST NOT be reopened by any path, including one driven by a capacity
event.

Capacity-availability reconciliation and its close-before-reopen sequencing MUST
apply only to capacity-backed listings. An unbacked listing's quantity is bounded by
what its source declares, never by availability, which is what its inexhaustibility
means; it is not an exemption from having its published state follow its
declaration.

An unbacked listing MUST be derived only from the site projection. No
storefront-local table may source its shape or capacity; its storefront-local records
are its listing row and its immutable binding. That prohibition does not exempt it
from source-publication reconciliation.

#### Scenario: An unbacked listing's source declaration is removed

- **WHEN** a capacity resource or pool an unbacked listing derives from is removed or disabled
- **THEN** the published listing closes

#### Scenario: An unbacked source is re-enabled

- **WHEN** a disabled declaration behind closed unbacked listings is enabled again with the same declared shape
- **THEN** those listings reopen under their original listing identities

#### Scenario: A declared shape change alters derivation identity

- **WHEN** a source declaration changes a field the derivation source envelope carries
- **THEN** the existing listing closes and a newly derived listing is published with a different derivation key
- **AND** the original binding row is unmodified

#### Scenario: A pool is disabled at its site

- **WHEN** a projected pool that open listings derive from declares itself disabled
- **THEN** those listings close

#### Scenario: A capacity release would reopen a diverged listing

- **WHEN** a capacity event makes a closed listing's slice available again while a published identity field of that listing still differs from its source
- **THEN** the listing is not reopened and the refusal is logged

#### Scenario: Capacity deltas do not reach an unbacked listing

- **WHEN** capacity-availability reconciliation runs, including after a settlement against an unbacked listing
- **THEN** no unbacked listing is closed, reopened, or resized by it

### Requirement: The seller's inventory guard checks a listing against its own source

Before a seller agrees terms, seller negotiation policy MUST recheck every published
field of the listing that is sourced from its declaration or pool against that
source: the listing's own site and pool or Physical Resource, never a resource
elsewhere. A categorical field MUST equal its source and a quantity MUST fit the
declared capacity. Fields whose authority is the storefront are not rechecked.

Seller policy MUST additionally check that the listing's published quantity is
available only for a capacity-backed listing. For an unbacked listing it MUST NOT
consult availability or contact a site authority.

A declared-match failure MUST be reported with a reason distinct from an availability
failure, so a buyer and an operator can tell a shape the seller no longer declares
from capacity that is temporarily taken.

#### Scenario: An unbacked listing matches its declaration

- **WHEN** a buyer negotiates against an unbacked listing whose published fields match its enabled source declaration
- **THEN** the declared match passes without any availability read or site call

#### Scenario: A declaration no longer supports its listing

- **WHEN** a buyer negotiates against a listing whose source declaration has shrunk below, or been disabled beneath, its published shape
- **THEN** seller policy rejects with a declared-match reason rather than an availability reason

#### Scenario: Matching capacity exists only elsewhere

- **WHEN** a listing's own source no longer supports it but another pool or site holds matching available capacity
- **THEN** seller policy rejects the listing

#### Scenario: A backed listing matches but capacity is taken

- **WHEN** a capacity-backed listing matches its declaration but its published quantity is not available
- **THEN** seller policy rejects with the availability reason

#### Scenario: A fungible listing matches one member

- **WHEN** a buyer negotiates against a listing derived from a fungible pool whose enabled members declare different counts
- **THEN** the declared match passes only if some single enabled member has equal categorical attributes and declares at least the published quantity

#### Scenario: A dry-run evaluation applies the same checks

- **WHEN** a seller evaluates a proposal against a listing without opening a negotiation
- **THEN** the evaluation applies the same declared match and, for a capacity-backed listing only, the same availability check as a negotiation round

### Requirement: A listing's published shape comes from its source declaration

A listing's published compute shape is derived from the shape its source
declaration carries, for capacity-backed and unbacked listings alike. Nothing in
publication verifies that shape against hardware, and this requirement makes no
claim that it does.

Derivation MUST NOT substitute a value for a quantity a declaration does not carry. A
declaration that omits the quantity a domain enumerates listings by MUST yield no
listing, and the omission MUST be reported to the operator naming the declaration. A
declaration that declares that quantity as zero MUST yield no listing without a
report. A declaration whose quantity is malformed MUST be treated as unresolvable:
it yields no new listing and its existing listings are held. In a fungible pool one
unresolvable member holds every listing derived from the pool, because the pool's range
cannot be computed without it; in a specific-resource pool it holds only its own.

Where a listing is capacity-backed, the published quantity is additionally bounded
by the availability its site projects, so it moves as capacity is reserved and
released. An unbacked fungible pool's listings range up to the largest single
member's declared quantity, never a sum across members, because a reservation would
land on one member. An unbacked listing has no availability to bound it and no reservation
consumes it; that difference is carried by the listing's published backing and MUST
NOT be encoded a second time in a separate published field.

#### Scenario: A declaration omits the enumerated quantity

- **WHEN** a source declaration carries no GPU count
- **THEN** no VM listing is derived from it, listings previously derived from it close, and the operator is told which declaration omits it

#### Scenario: A declaration declares zero

- **WHEN** a source declaration declares a GPU count of zero
- **THEN** no VM listing is derived from it and no report is made

#### Scenario: An unbacked listing's published quantity does not move

- **WHEN** any number of buyers settle against an unbacked listing
- **THEN** its published quantity is unchanged, because no reservation consumes it

### Requirement: A backing change closes and republishes

A listing's backing is fixed for the life of its durable binding. Where the supply
behind a listing moves between backed and unbacked, the existing listing MUST close
and a new listing MUST bind with its own durable identity and its own backing
discriminator.

An implementation MUST NOT attempt an in-place update of a listing's backing, in
either the durable binding or the published payload. Because the pool a listing
derives from carries backing that is itself fixed at creation, a supply move is a
move between pools, and the republished listing's derivation identity differs by
construction.

#### Scenario: Supply moves from unbacked to backed

- **WHEN** the supply behind an unbacked listing is moved to a pool declaring capacity backing
- **THEN** the unbacked listing closes and a new listing binds with a distinct durable identity and a capacity-backed discriminator
- **AND** the original binding row is unmodified

### Requirement: An unbacked listing publishes only settlement options its domain does not fulfil through capacity

A domain that can publish unbacked listings MUST declare in its settlement
composition, for every settlement mechanism it composes, whether settling through that
mechanism delivers through the domain's capacity-backed fulfillment. The declaration
MUST be explicit for each composed mechanism and MUST NOT default. A domain whose
listings are always capacity-backed owes no such declaration.

Publication MUST NOT give an unbacked listing a settlement option whose mechanism its
domain fulfils through capacity. Such options MUST be dropped from an unbacked
candidate with an operator-visible notice naming the pool and the dropped mechanisms.
An unbacked candidate left with no settlement option MUST yield no listing, with the
same notice. Capacity-backed candidates are unaffected.

This is decided by how the domain composes each mechanism, so no pool-level or
listing-level field names a settlement mechanism.

#### Scenario: Every composed mechanism fulfils through capacity

- **WHEN** an unbacked candidate's resolved settlement clauses name only mechanisms its domain fulfils through capacity
- **THEN** no listing is derived from it and an operator notice names the pool and the dropped mechanisms

#### Scenario: One mechanism settles without fulfillment

- **WHEN** an unbacked candidate's resolved clauses name one mechanism its domain fulfils through capacity and one it does not
- **THEN** the listing publishes only the option whose mechanism does not reach capacity-backed fulfillment, and the notice names the dropped mechanism

#### Scenario: A backed candidate names the same mechanisms

- **WHEN** a capacity-backed candidate's resolved clauses name mechanisms its domain fulfils through capacity
- **THEN** every ready option publishes as before

### Requirement: Publication runs as a controllable storefront lifecycle loop

The VM storefront, alone or within the combined compute-family storefront, MUST run
its publication in its own process as a timer-driven lifecycle loop. Bare-metal
publication is operator-invoked and is outside this requirement. Each cycle derives candidates from its configured sources, publishes new
listings, refreshes open listings, closes listings whose source no longer supports
them, holds listings whose source is unresolvable, and reopens listings reconciliation
closed, subject to the listing identity comparison. A change in a site's resource-pool
projection generation MUST wake the loop.

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

### Requirement: A seller's close is durable

Every close of a listing MUST record whether its seller or reconciliation closed it,
and a closed listing MUST NOT be recorded without that reason. Reopening a listing
MUST clear it. A later close of a listing its seller closed, by any write, MUST keep
the seller as its reason.

No reconciliation path — a capacity event, the publication loop, or any other — MUST
reopen a listing its seller closed, and publication MUST NOT bind a replacement listing
under that listing's derivation identity. A seller MUST be able to reopen a listing
they closed, after which it is reconciled like any open listing. A seller request to
reopen a listing reconciliation closed MUST be refused with a conflict naming the
reason, because its source does not currently support it.

#### Scenario: A seller closes a listing

- **WHEN** a seller closes an open listing and a later capacity event or publication cycle finds its slice available
- **THEN** the listing stays closed and no replacement listing is published for that slice

#### Scenario: A seller reopens a listing they closed

- **WHEN** a seller resumes a listing they closed
- **THEN** it reopens, its closure reason is cleared, and it is published and reconciled like any open listing

#### Scenario: A seller tries to reopen a reconciliation close

- **WHEN** a seller resumes a listing that reconciliation closed
- **THEN** the request is refused with a conflict naming the closure reason and the listing is unchanged

#### Scenario: Reconciliation closes a listing its seller already closed

- **WHEN** reconciliation writes a close for a listing its seller closed
- **THEN** the listing's closure reason remains the seller, and no later reconciliation reopens it

#### Scenario: A close names no reason

- **WHEN** a writer closes a listing without recording who closed it
- **THEN** the write is refused

### Requirement: Registries converge on each listing's local status

This requirement governs VM publication and API-credit publication; bare-metal
publication is outside it.

For those, a listing's local status is the publication decision and its registries
follow it. A close or reopen MUST change the local listing before any registry is
told, and a local change that fails MUST be reported to its caller with no registry
told — a seller's close is reported as retryable. Each registry's outcome for every
publish, close, and reopen MUST be recorded durably. Every publication pass — each
VM publication cycle and each API-credit capacity reconciliation — MUST then resend,
to each configured registry whose recorded outcome disagrees with its listing's
local status, exactly what that status implies — a close for a closed listing, and
for an open one the listing republished and reopened — and to no other registry. A
registry still unreachable stays recorded as diverged for the next pass.

#### Scenario: A registry misses a close

- **WHEN** a listing closes locally and one of its registries fails the close
- **THEN** the next publication pass sends the close to that registry alone

#### Scenario: A registry misses a reopen

- **WHEN** a listing reopens locally and one registry fails to reopen it
- **THEN** the next publication pass republishes and reopens the listing at that registry alone

#### Scenario: A local close fails

- **WHEN** the local close of a listing fails
- **THEN** no registry is told, and a seller's close is reported as retryable with the listing unchanged

## MODIFIED Requirements

### Requirement: Domain-owned publication and hold hints
A storefront domain MAY interpret a projected pool's `listing_cardinality_mode`, `max_reservation_hold_seconds`, `region`, `sla`, and `pricing` policy tags. `listing_cardinality_mode`'s scope is cardinality: how many listing candidates a pool yields and how each is independently identified. A value describing what is offered, how a deal settles, or whether an admission authority backs the listing is out of scope for this hint and MUST NOT be added to it. Each domain MUST own its accepted `listing_cardinality_mode` values and structural default.

A storefront MUST accept the former `listing_mode` key as a deprecated alias on projection ingestion, resolving it to the same cardinality it names and emitting an operator-visible deprecation notice. Accepting the alias is what prevents a projection produced by an unupgraded site from being silently reclassified to the structural default across version skew. The deprecated alias applies to the projected policy tag a site emits, which is the only spelling an unupgraded peer can send; every other surface naming this hint — the resolver, the durable reconciliation rows, and the operator-facing explanation field — MUST use the settled name alone, so an operator reading why a pool fell back to its structural default is not told about a key the projection no longer carries.

A supplied value the selected domain does not recognize MUST fall back to that domain's structural default with an operator-visible explanation, rather than failing projection ingestion or blocking publication. An absent value MUST fall back to the same default; where a pool has no cardinality question to answer, absence is the encoding and the fallback MUST be silent. The operator-visible explanation is owed for supplied-but-unrecognized values, not for absence. A deprecation notice and a fallback explanation are distinct and MUST remain separately identifiable: the first says a declared value was honored under a key that is going away, the second says a declared value was not usable and a default was substituted, and a pool in both conditions is owed both.

A cooperating storefront MUST treat a valid `max_reservation_hold_seconds` as an advisory upper bound on its own requested reservation-hold TTL — it MUST NOT change what the site ledger itself enforces, and an unresolvable or invalid preference MUST leave the caller's requested TTL unchanged rather than block hold placement.

A `fungible` pool's publishable capacity range is bounded by what a single member can satisfy, never by a sum across members: for a capacity-backed pool, what a single member can currently satisfy, sourced from grouped `site_capacity_buckets` data when it is available; for an unbacked pool, what a single member declares. A `specific_resource` pool publishes one independently identified, independently reservable listing candidate per currently enabled member, regardless of member count. No listing/hold hint's projected value may be persisted into storefront-local storage — a consumer reads it live from the current projection each time it is needed.

`region` has no storefront-side override — a storefront overriding where hardware physically sits would misrepresent a fact, not adjust a policy. `sla` and negotiation-floor pricing policy (per resource family and, within a family, per model) each resolve through a three-tier precedence, highest to lowest: a storefront-specific override on a specific pool; the pool's own declared hint; the storefront's own configured default. `sla`'s middle tier is additionally gated behind a storefront-wide trust setting — a storefront MAY decline to consult a pool's declared SLA at all, independent of whether any specific pool has an override. A resolved `min_price` is only a negotiation floor, and a resolved `default_token_address` is only demand-side policy input; neither constructs a settlement option. Settlement option assets, rates, units, and mechanism inputs come only from complete typed clause lists, with a pool's clauses — from a storefront override on that pool or the pool's own declared hint — replacing the storefront's configured defaults as whole lists. Every term of sale MUST come from a durable source: no command-line argument may supply or replace a settlement clause or a maximum duration, because reconciliation must be able to re-derive every term a listing publishes.

#### Scenario: Listing cardinality mode is absent or invalid
- **WHEN** a projected pool supplies a `listing_cardinality_mode` value unsupported by the selected domain
- **THEN** publication uses the domain's structural default and exposes an operator-visible explanation without failing projection ingestion
- **AND WHEN** a projected pool instead omits the value because no cardinality question applies to it
- **THEN** publication uses the domain's structural default silently, with no operator-visible explanation for the absence

#### Scenario: A projection carries only the deprecated key
- **GIVEN** a site that has not been upgraded emits `listing_mode`
- **WHEN** a storefront ingests that projection
- **THEN** the pool resolves to the cardinality that key names
- **AND** an operator-visible deprecation notice is emitted
- **AND** the pool does not fall back to the structural default

#### Scenario: A fungible pool's members have unequal availability
- **WHEN** a capacity-backed fungible pool's members currently have different available capacity
- **THEN** the storefront publishes candidate slice sizes no larger than the largest currently available single member, not a sum across members

#### Scenario: An unbacked fungible pool's members declare unequal capacity
- **WHEN** an unbacked fungible pool's members declare different quantities
- **THEN** the storefront publishes candidate slice sizes no larger than the largest single member's declared quantity, not a sum across members

#### Scenario: A specific-resource pool has more than one member
- **WHEN** a pool resolves to `specific_resource` and has multiple currently enabled members
- **THEN** the storefront derives one listing candidate per member rather than one pooled candidate

#### Scenario: Hold preference is shorter than storefront policy
- **WHEN** a valid positive `max_reservation_hold_seconds` is lower than the storefront's configured acceptance-hold TTL
- **THEN** the storefront requests no more than the projected preference while live site admission remains authoritative

#### Scenario: A storefront declines to trust a pool's declared SLA
- **WHEN** a storefront has not enabled its SLA trust setting
- **THEN** publication resolves SLA from a per-pool storefront override or the storefront's own default, never from the pool's own declared hint, regardless of whether that pool has one

#### Scenario: A pool supplies negotiation pricing hints
- **WHEN** pricing precedence resolves `min_price` or a token-address policy hint for a listing candidate
- **THEN** the storefront may use those values only for negotiation-floor or demand policy and derives every settlement option exclusively from the effective complete typed clause list

#### Scenario: Terms come only from durable sources
- **WHEN** a publication cycle re-derives an open listing whose pool clauses and configured defaults are unchanged
- **THEN** the listing's settlement options and maximum duration are unchanged, because no term of sale came from a source the cycle cannot re-read

### Requirement: Storefront owns seller settlement UX

Seller configuration, readiness, mechanism administration, and publication MUST be exposed through the storefront CLI and generated role config surface. Normal publication MUST derive options from mechanism-neutral settlement clauses and MUST NOT expose provider-, chain-, or escrow-specific flags. Mechanism administration MUST remain under `settlement <mechanism>`. The storefront CLI's publication command MUST run or preview a cycle of the storefront's publication loop through the storefront API rather than deriving or publishing listings itself. A hosted client MAY supply workflow primitives, but a separate provider-specific seller executable or top-level mechanism-specific publication flow MUST NOT be the normal marketplace entry point.

#### Scenario: Seller inspects all settlement mechanisms

- **WHEN** `market-storefront settlement status --json` runs
- **THEN** it returns the common status schema for every installed mechanism in configured order without a listing or financial side effect

#### Scenario: Seller publishes two mechanisms

- **WHEN** normal publication resolves valid Stripe and Alkahest settlement clauses
- **THEN** the storefront derives both through their ready registrations without invoking a mechanism-specific publication command

#### Scenario: Seller runs the publication command

- **WHEN** a seller runs the storefront CLI's publication command
- **THEN** it runs or previews one cycle of the storefront's publication loop through the storefront API, and it reads no storefront database

### Requirement: Per-resource settlement input uses the common clause contract

Configured defaults, pool-declared hints, storefront pool overrides, imported resource records, and reconciliation inputs that describe settlement options MUST parse to the same typed settlement-clause model before option derivation. Unknown fields, conflicting duplicate values, role-inapplicable fields, and malformed rates MUST fail the affected candidate without creating a partially interpreted option.

#### Scenario: Imported resource overrides settlement defaults

- **WHEN** one resource record supplies its own complete settlement clauses
- **THEN** those clauses replace the configured defaults for that resource and are validated through the same grammar and registrations

### Requirement: Commercial mapping identity
A VM listing's commercial mapping between an authoritative capacity identity and the published listing MUST be its immutable common listing binding. VM publication, reconciliation, close, and reopen MUST NOT read or write `derived_compute_listings`; a closed listing is found again by its candidate's derivation key in the common binding. A domain that still keeps its own mapping table (`derived_bare_metal_listings`) MUST NOT duplicate it as a separate schema. Pricing, settlement terms, and seller policy MUST continue to live on the generic `listings` table, addressed by `listing_id` — no mapping carries commercial fields of its own. Each derivation key MUST include the owning `site_id`, since a pool or resource identifier is only unique within one site, never globally. A derivation key MUST be collision-resistant by construction against any values its constituent fields (`site_id`, `pool_id`, `resource_id`) may take — these are operator-chosen strings with no character restrictions, so a naive delimiter-joined encoding is not sufficient.

#### Scenario: Two sites name a pool identically
- **WHEN** two different sites each have a pool sharing the same operator-chosen `pool_id`
- **THEN** their listing bindings have distinct derivation keys and neither binding is silently overwritten by the other's

#### Scenario: An operator-chosen identifier contains a delimiter character
- **WHEN** a `site_id`, `pool_id`, or `resource_id` value contains a character that would otherwise separate fields in a naively joined key
- **THEN** the resulting derivation key remains distinct from any other combination of values that could produce the same joined string

#### Scenario: Two specific-resource candidates share a pool
- **WHEN** a multi-member pool publishes more than one `specific_resource` candidate, each naming a different physical resource
- **THEN** each candidate's derivation key is resource-keyed and distinct, and binding one candidate does not overwrite another's

#### Scenario: A closed listing's slice becomes publishable again
- **WHEN** a closed VM listing's candidate is derived again with the same derivation identity
- **THEN** the listing bound under that derivation key reopens, rather than a new listing being bound under a colliding key

### Requirement: Site-pinned claim routing
A capacity claim for a capacity-backed listing with a known site mapping MUST be routed to exactly that site, with no fallback to a different site on refusal or error — this applies to every such listing, whether the underlying capacity is fungible (pool-derived) or pinned to a specific physical resource, never only to resource-pinned listings. A capacity-backed listing with no recorded site mapping MAY be routed by placement policy across configured sites. An unbacked listing constructs no capacity claim, so it has no claim to route; refusing claim construction for it is a fail-closed guard against a reservation record with no authority behind it, not a control on what a seller may publish.

#### Scenario: A mapped listing's site would lose to placement policy
- **WHEN** a capacity-backed listing is mapped to one site but placement policy would otherwise prefer a different configured site with more available capacity
- **THEN** the claim is routed only to the listing's mapped site, regardless of what placement policy would have chosen for an unmapped claim

#### Scenario: A mapped site refuses or errors
- **WHEN** a capacity-backed listing's mapped site refuses the claim or the request to that site fails
- **THEN** the claim is not retried against a different configured site

#### Scenario: An unbacked listing is queried for a claim route
- **WHEN** claim construction is attempted for an unbacked listing
- **THEN** no claim is constructed and the attempt is refused

### Requirement: Trusted listing mappings route to one site

A capacity-backed listing with a durable site mapping MUST route all capacity claims to exactly that configured site and pinned authority. Refusal, outage, missing trust, or mode disagreement at that site MUST fail closed and MUST NOT fan out to another site. An unbacked listing's durable site mapping records its origin and routes no capacity claim.

#### Scenario: A normalized listing disagrees with its binding

- **WHEN** a normalized domain listing projects an `offering_mode` different from its registration or durable binding
- **THEN** publication is refused rather than publishing a listing whose public mode disagrees with its provenance

#### Scenario: A published shape is submitted under the retired key

- **WHEN** a listing is submitted carrying the published shape under `offer_resource` or `offer`
- **THEN** it is rejected rather than accepted under a second spelling

#### Scenario: Another site could satisfy the claim

- **WHEN** the bound site refuses a capacity-backed listing's claim while another configured site has compatible capacity
- **THEN** the storefront reports the bound-site refusal and the other site receives zero calls

#### Scenario: An unbacked listing's origin site is unreachable

- **WHEN** the origin site recorded on an unbacked listing's binding is unreachable
- **THEN** no capacity claim is attempted at it or at any other site
