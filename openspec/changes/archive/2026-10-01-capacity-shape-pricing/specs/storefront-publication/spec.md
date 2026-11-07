## ADDED Requirements

### Requirement: Shape-resolvable commercial rates

A storefront MUST let a seller state a rate per unit per time unit for each capacity family
its domain's pricing projection names, in an asset, under the family it prices, in one nesting
shared by the configured default, the pool's pricing hint, and the storefront's pool override.
The domain's pricing projection MUST name, for each priced family, the one quantity it is priced
by and, where the family is priced per attribute value, that attribute; which families are keyed
MUST NOT be inferred from the schema. Within one family, a tier's rate list MUST replace lower
tiers' lists as a whole, and each family MUST resolve independently of the others. A family rate
MUST be positive decimal text; a zero rate MUST be refused.

A VM listing for which any family resolves a non-empty rate list is **shape-priced**: each of its
settlement clauses names mechanism, asset, and mechanism input, and for each clause whose
mechanism negotiates a scalar amount the storefront composes the clause's rate by evaluating the
listing's own shape against the family rates in that clause's asset. A clause whose mechanism
declines the scalar is published rateless in either mode. Otherwise the listing is
**flat-priced**: a clause's own rate is the listing's rate whatever its shape, and a stated flat
rate MUST NOT be reinterpreted as a rate for any one family.

A family the listing's shape does not name MUST NOT contribute to its price. A family its shape
names with no rate in a clause's asset MUST contribute nothing to that clause's price, and the
storefront MUST report it as included without a rate; no family is required to have a rate. A
candidate MUST be refused, with a reason naming the asset, when a scalar-negotiating clause's
composed rate is zero, so that no listing is published or negotiated free; and, with a reason, when
a shape-priced clause also states its own rate.

#### Scenario: A configuration states no family rates

- **WHEN** a storefront's tiers resolve no family rates for any listing and every clause rate
  converts exactly
- **THEN** every listing is flat-priced and publishes the same settlement options, with the same
  option identities, as a storefront without family-rate support

#### Scenario: A shape-priced listing composes its rate

- **WHEN** a listing of two H100 GPUs, sixteen vCPUs, and 128 GiB of memory resolves rates of 80 per
  card-hour, 0.5 per vCPU-hour, and 0.05 per GiB-hour in one asset
- **THEN** its clause in that asset publishes a rate of 174.4 per hour

#### Scenario: A family without a rate is not charged

- **WHEN** a shape-priced listing's shape names 64 GiB of memory and no tier states a memory rate in
  a clause's asset
- **THEN** that clause's rate is composed from the other families' rates, the listing publishes,
  and the storefront reports memory as included without a rate in that asset

#### Scenario: A listing would be free in an asset

- **WHEN** no family a shape-priced listing's shape names has a rate in a scalar clause's asset
- **THEN** the candidate is refused with a reason naming the asset, and nothing is posted to a
  registry

#### Scenario: Rates resolve from different tiers per family

- **WHEN** one family's rates are stated by a storefront override and another's are available only
  as a configured default
- **THEN** each family resolves independently from its own highest available tier

#### Scenario: A shape omits a family the seller prices

- **WHEN** a shape-priced listing's shape omits a family for which rates resolve
- **THEN** that family contributes nothing to the listing's price

#### Scenario: A shape-priced clause states its own rate

- **WHEN** a shape-priced listing's clause also states a rate
- **THEN** the candidate is refused with a reason, and neither source is chosen silently

#### Scenario: A published asking rate is present

- **WHEN** a listing also publishes a listing-level asking rate
- **THEN** that asking rate is neither read as a family rate nor reinterpreted as one, and no
  family rate is read as the asking rate

### Requirement: An unreadable family rate holds its pool

A family rate list that a tier states and the storefront cannot read MUST NOT be treated as absent:
the pool MUST be held, so its listings keep their last-published terms and nothing is published or
refreshed from it until the rate is readable. The storefront MUST report, per held pool, the tier,
family, and problem in the derivation report its system status serves. A malformed family rate in
the storefront's own configured defaults MUST prevent the storefront from starting.

#### Scenario: A pool hint states an unreadable rate

- **WHEN** a pool's hint states a memory rate the storefront cannot read and the storefront's
  configured default states a memory rate
- **THEN** the pool is held rather than priced from the configured default, its open listings keep
  their last-published terms, and system status names the hint, the family, and the problem

#### Scenario: A configured default states an unreadable rate

- **WHEN** the storefront's configured defaults state a family rate that cannot be read
- **THEN** the storefront refuses to start, naming the setting

### Requirement: Price aggregation is replaceable

Deriving a price from a shape and one asset's family rates MUST occur behind a replaceable
aggregation interface that the domain selects; operator configuration MUST NOT select it. The
interface MUST return an exact price in the asset's display units per time unit, computed without
binary floating point and without rounding. Converting that price to base units is the consumer's
step, under the consumer's stated rule. No consumer of a price MAY reconstruct or assume a total by
combining individual family rates and quantities directly, and evaluation MUST be callable outside
the negotiation path.

#### Scenario: A domain selects a different aggregation

- **WHEN** a domain selects a different price aggregation
- **THEN** prices change accordingly with no change to negotiation, publication, or settlement
  code paths

#### Scenario: A consumer needs a shape's price

- **WHEN** any component needs the price of a shape
- **THEN** it obtains it through the aggregation interface rather than by multiplying a family's
  rate by its quantity

#### Scenario: A price has more significant digits than a fixed-precision context holds

- **WHEN** family rates and quantities produce a price with more than 28 significant digits
- **THEN** the aggregation returns that price exactly

### Requirement: A shape-priced listing records the rates that could price a revised shape

A shape-priced listing MUST record, on the storefront's generic listing record, every family's
resolved rate list for the listing — including families its own shape omits — and the storefront's
listing read MUST return it; a flat-priced listing records none. The record is a term of sale: a
change MUST refresh the listing in place, and the record MUST NOT be hashed into the listing's
identity, its shape digest, or any settlement option's identity. A settlement option's identity
MUST continue to cover its rates, so a change that alters a listing's composed rate changes that
option's identity while the listing's identity is unchanged. Publication to a registry MUST carry
each settlement option's composed rate for the listing's own shape and MUST NOT depend on the
registry keeping any listing field it does not already keep.

#### Scenario: A family rate changes

- **WHEN** a shape-priced listing's composed rate changes while its shape and source do not
- **THEN** the listing keeps its identity, its options carry the new composed rate under new
  option identities, and its storefront listing read returns the new rates

#### Scenario: A rate changes for a family the listing's shape omits

- **WHEN** a GPU-only shape-priced listing's resolved memory rate changes
- **THEN** the listing is refreshed in place with the new recorded rate, and its composed rate and
  option identities are unchanged

#### Scenario: A listing is published to a registry

- **WHEN** a shape-priced listing is published
- **THEN** the registry receives the listing's settlement options with their composed rates in the
  existing option fields, and no additional listing-level field

## MODIFIED Requirements

### Requirement: Domain-owned publication and hold hints
A storefront domain MAY interpret a projected pool's `listing_cardinality_mode`, `max_reservation_hold_seconds`, `region`, `sla`, and `pricing` policy tags. `listing_cardinality_mode`'s scope is cardinality: how many listing candidates a pool yields and how each is independently identified. A value describing what is offered, how a deal settles, or whether an admission authority backs the listing is out of scope for this hint and MUST NOT be added to it. Each domain MUST own its accepted `listing_cardinality_mode` values and structural default.

A storefront MUST accept the former `listing_mode` key as a deprecated alias on projection ingestion, resolving it to the same cardinality it names and emitting an operator-visible deprecation notice. Accepting the alias is what prevents a projection produced by an unupgraded site from being silently reclassified to the structural default across version skew. The deprecated alias applies to the projected policy tag a site emits, which is the only spelling an unupgraded peer can send; every other surface naming this hint — the resolver, the durable reconciliation rows, and the operator-facing explanation field — MUST use the settled name alone, so an operator reading why a pool fell back to its structural default is not told about a key the projection no longer carries.

A supplied value the selected domain does not recognize MUST fall back to that domain's structural default with an operator-visible explanation, rather than failing projection ingestion or blocking publication. An absent value MUST fall back to the same default; where a pool has no cardinality question to answer, absence is the encoding and the fallback MUST be silent. The operator-visible explanation is owed for supplied-but-unrecognized values, not for absence. A deprecation notice and a fallback explanation are distinct and MUST remain separately identifiable: the first says a declared value was honored under a key that is going away, the second says a declared value was not usable and a default was substituted, and a pool in both conditions is owed both.

A cooperating storefront MUST treat a valid `max_reservation_hold_seconds` as an advisory upper bound on its own requested reservation-hold TTL — it MUST NOT change what the site ledger itself enforces, and an unresolvable or invalid preference MUST leave the caller's requested TTL unchanged rather than block hold placement.

A `fungible` pool's publishable capacity range is bounded by what a single member can satisfy, never by a sum across members: for a capacity-backed pool, what a single member can currently satisfy, sourced from grouped `site_capacity_buckets` data when it is available; for an unbacked pool, what a single member declares. A `specific_resource` pool publishes one independently identified, independently reservable listing candidate per currently enabled member, regardless of member count. No listing/hold hint's projected value may be persisted into storefront-local storage — a consumer reads it live from the current projection each time it is needed.

`region` has no storefront-side override — a storefront overriding where hardware physically sits would misrepresent a fact, not adjust a policy. `sla` and per-family rates (per capacity family and, for a family the domain prices per attribute value, per that value) each resolve through a three-tier precedence, highest to lowest: a storefront-specific override on a specific pool; the pool's own declared hint; the storefront's own configured default. `sla`'s middle tier is additionally gated behind a storefront-wide trust setting — a storefront MAY decline to consult a pool's declared SLA at all, independent of whether any specific pool has an override. The negotiation floor applied to a listing whose settlement option advertises no rate is the storefront's configured default alone: it is not resolved per pool or per model, and it constructs no settlement option. A pool hint or storefront override that still states the retired `min_price` or `token` pricing keys MUST remain readable; neither key is read, and the storefront MUST report them as retired rather than holding the pool. Settlement option assets, rates, units, and mechanism inputs come only from complete typed clause lists, with a pool's clauses — from a storefront override on that pool or the pool's own declared hint — replacing the storefront's configured defaults as whole lists. Every term of sale MUST come from a durable source: no command-line argument may supply or replace a settlement clause or a maximum duration, because reconciliation must be able to re-derive every term a listing publishes.

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
- **WHEN** a pool's pricing hint or a stored storefront override states `min_price` or `token`
- **THEN** neither value is read, the pool's listings are neither held nor refused for it, and system status reports the retired keys
- **AND** every settlement option derives exclusively from the effective complete typed clause list and, for a shape-priced listing, its resolved family rates

#### Scenario: Terms come only from durable sources
- **WHEN** a publication cycle re-derives an open listing whose pool clauses and configured defaults are unchanged
- **THEN** the listing's settlement options and maximum duration are unchanged, because no term of sale came from a source the cycle cannot re-read

### Requirement: Publication pricing is explicit per settlement clause

Every priced settlement publication clause MUST carry one asset-scoped decimal rate and unit: stated on the clause for a flat-priced listing, or composed for a shape-priced listing from the listing's own shape and its family rates in that clause's asset. The owning mechanism MUST normalize the rate to canonical integer minor or base units using authoritative asset scale, with exact arithmetic whatever the rate's number of significant digits, MUST reject a conversion that is not a whole number of units or exceeds `2**256 - 1`, and MUST include the normalized rate in deterministic option identity. A resource-level `min_price` or other untyped scalar MUST NOT be reused as the price of more than one mechanism, and a family rate in one asset MUST NOT price a clause in another.

#### Scenario: Dual listing uses equal human prices

- **WHEN** a seller explicitly publishes USD 2/hour and six-decimal-token 2/hour clauses for one resource
- **THEN** the resulting options carry 200 and 2000000 canonical units respectively and both display as 2 asset units/hour

#### Scenario: Dual listing omits one mechanism rate

- **WHEN** a resource has one valid mechanism clause and another enabled mechanism has no explicit rate-bearing clause
- **THEN** publication does not infer the missing mechanism's price from the first clause

#### Scenario: A rate has more significant digits than a fixed-precision context holds

- **WHEN** a clause's rate, stated or composed, has more than 28 significant digits and is not a whole number of the asset's base units
- **THEN** the mechanism refuses it rather than rounding it into an apparently exact value

#### Scenario: A shape-priced clause's asset has rates for some families only

- **WHEN** a shape-priced listing has a clause in an asset in which only some of the families its shape names have rates
- **THEN** that clause's rate is composed from those families alone, and no rate is taken from another asset's family rates
