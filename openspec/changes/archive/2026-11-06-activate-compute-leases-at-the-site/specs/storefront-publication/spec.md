## MODIFIED Requirements

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
offering mode, and source declaration identity — from admission provenance. Every
storefront operation that reserves, commits, activates, releases, or truncates
capacity, or schedules or dispatches against it, MUST pass through the listing's
binding and be refused by the binding's backing delegate before any site call unless
an admission authority stands behind the listing; no such operation MAY reach a site
without that guard. A refused admission MUST be reported as a conflict, distinct from
an identity fault such as an unknown site or a changed binding. Operations that
compare, copy, or carry listing identity MUST accept a binding of either backing.

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

- **WHEN** a reservation, commit, lease activation, release, scheduling, or dispatch operation is attempted for an unbacked listing
- **THEN** the operation is refused before any effect, so no reservation record is created with no authority behind it

#### Scenario: Recovery reserves for an accepted deal

- **WHEN** a storefront's fulfillment, fulfillment recovery, or administrator control reserves or commits capacity for a listing
- **THEN** the effect passes the listing binding's admission guard before reaching the listing's site

#### Scenario: An administrator reserves against an unbacked listing

- **WHEN** an administrator requests a reservation for a listing with no admission authority behind it
- **THEN** the request is refused as a conflict, not reported as an unconfigured site or a server error
