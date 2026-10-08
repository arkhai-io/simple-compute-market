## ADDED Requirements

### Requirement: Pricing rate-list hint validation

A Resource Pool management surface that accepts the `pricing` key MUST check the structure of every
rate list it carries: any `rates` value found under a family, or under a key within a family, of
`pricing` MUST be a list of entries, each carrying an `asset` that is a trimmed, non-empty string, a
`rate` that is positive decimal text without a sign or an exponent, and a `per` that is a canonical
lowercase unit token, with no asset appearing twice in one list. An empty list MUST be accepted.

The check MUST NOT depend on any domain's family or field names, and MUST NOT restrict which units
are accepted: which families are priced, by what key, and which units a rate may use MUST be
validated by the domain that reads the hint. Every surface capable of persisting a Resource Pool's
`policy_tags` MUST apply the same check, as it does for `asking_rates`, and the value MUST be
projected verbatim. Values of `pricing` other than rate lists are unaffected.

#### Scenario: Operator supplies a malformed family rate

- **WHEN** an operator submits a pool whose `pricing.memory.rates` holds an entry whose rate is a
  JSON number, whose asset is blank, or whose asset repeats another entry's, through any pool-write
  surface
- **THEN** Resource Pool validation rejects the update without changing the stored policy metadata,
  naming the entry

#### Scenario: Operator prices a family no domain defines

- **WHEN** an operator submits a structurally well-formed rate list under a family no domain prices
- **THEN** Resource Pool validation accepts it, and a storefront whose pricing projection does not
  name that family holds the pool's listings and reports the rate unreadable
