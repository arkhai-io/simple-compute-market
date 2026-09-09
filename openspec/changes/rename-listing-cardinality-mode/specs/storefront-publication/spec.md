## MODIFIED Requirements

### Requirement: Domain-owned publication and hold hints
A storefront domain MAY interpret a projected pool's `listing_cardinality_mode`, `max_reservation_hold_seconds`, `region`, `sla`, and `pricing` policy tags. `listing_cardinality_mode`'s scope is cardinality: how many listing candidates a pool yields and how each is independently identified. A value describing what is offered, how a deal settles, or whether an admission authority backs the listing is out of scope for this hint and MUST NOT be added to it. Each domain MUST own its accepted `listing_cardinality_mode` values and structural default.

A storefront MUST accept the former `listing_mode` key as a deprecated alias on projection ingestion, resolving it to the same cardinality it names and emitting an operator-visible deprecation notice. Accepting the alias is what prevents a projection produced by an unupgraded site from being silently reclassified to the structural default across version skew.

A supplied value the selected domain does not recognize MUST fall back to that domain's structural default with an operator-visible explanation, rather than failing projection ingestion or blocking publication. An absent value MUST fall back to the same default; where a pool has no cardinality question to answer, absence is the encoding and the fallback MUST be silent. The operator-visible explanation is owed for supplied-but-unrecognized values, not for absence.

A cooperating storefront MUST treat a valid `max_reservation_hold_seconds` as an advisory upper bound on its own requested reservation-hold TTL — it MUST NOT change what the site ledger itself enforces, and an unresolvable or invalid preference MUST leave the caller's requested TTL unchanged rather than block hold placement.

A `fungible` pool's publishable capacity range is bounded by what a single member can currently satisfy, never by a sum across members, and MUST be sourced from grouped `site_capacity_buckets` data when it is available; a `specific_resource` pool publishes one independently identified, independently reservable listing candidate per currently enabled member, regardless of member count. No listing/hold hint's projected value may be persisted into storefront-local storage — a consumer reads it live from the current projection each time it is needed.

`region` has no storefront-side override — a storefront overriding where hardware physically sits would misrepresent a fact, not adjust a policy. `sla` and negotiation-floor pricing policy (per resource family and, within a family, per model) each resolve through a three-tier precedence, highest to lowest: a storefront-specific override on a specific pool; the pool's own declared hint; the storefront's own configured default. `sla`'s middle tier is additionally gated behind a storefront-wide trust setting — a storefront MAY decline to consult a pool's declared SLA at all, independent of whether any specific pool has an override. A resolved `min_price` is only a negotiation floor, and a resolved `default_token_address` is only demand-side policy input; neither constructs a settlement option. Settlement option assets, rates, units, and mechanism inputs come only from complete typed clause lists, with resource clauses replacing command clauses and command clauses replacing configured defaults as whole lists.

#### Scenario: Listing mode is absent or invalid

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

- **WHEN** a fungible pool's members currently have different available capacity
- **THEN** the storefront publishes candidate slice sizes no larger than the largest currently available single member, not a sum across members

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
