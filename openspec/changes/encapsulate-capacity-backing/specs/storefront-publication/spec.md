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
storefront operation that reserves, commits, releases, or truncates capacity, or
schedules or dispatches against it, MUST pass through the listing's binding and be
refused by the binding's backing delegate before any site call unless an admission
authority stands behind the listing; no such operation MAY reach a site without that
guard. A refused admission MUST be reported as a conflict, distinct from an identity
fault such as an unknown site or a changed binding. Operations that compare, copy, or
carry listing identity MUST accept a binding of either backing.

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

#### Scenario: Recovery reserves for an accepted deal

- **WHEN** a storefront's fulfillment, fulfillment recovery, or administrator control reserves or commits capacity for a listing
- **THEN** the effect passes the listing binding's admission guard before reaching the listing's site

#### Scenario: An administrator reserves against an unbacked listing

- **WHEN** an administrator requests a reservation for a listing with no admission authority behind it
- **THEN** the request is refused as a conflict, not reported as an unconfigured site or a server error

### Requirement: A backing change closes and republishes

A listing's backing is fixed for the life of its durable binding. Where the supply
behind a listing moves between backed and unbacked, the existing listing MUST close
and a new listing MUST bind with its own durable identity and its own backing
discriminator.

An implementation MUST NOT attempt an in-place update of a listing's backing, in
either the durable binding or the published payload. Every domain MUST compare a
listing's bound backing with the backing its source now declares before any other
comparison, on every refresh, every reopen, and every source check, and a mismatch
MUST close an open listing and refuse any reopen or refresh. Backing MUST be neither
an identity field nor a term of sale, because a pool re-created under the same
identifier with the opposite backing yields a candidate under the same derivation
identity.

#### Scenario: Supply moves from unbacked to backed

- **WHEN** the supply behind an unbacked listing is moved to a pool declaring capacity backing
- **THEN** the unbacked listing closes and a new listing binds with a distinct durable identity and a capacity-backed discriminator
- **AND** the original binding row is unmodified

#### Scenario: A pool is re-created with the opposite backing

- **WHEN** a pool is removed and re-created under the same identifier with the opposite backing, and publication derives a candidate under an open listing's derivation identity
- **THEN** that listing closes rather than refreshing in place, and it is reopened by no path

#### Scenario: A source check finds the backing changed

- **WHEN** a seller decision rechecks a listing whose source now declares the opposite backing
- **THEN** the check reports a declared mismatch

### Requirement: An unbacked listing publishes only settlement options its domain does not fulfil through capacity

Every domain whose listings are admitted against capacity MUST declare, on each
settlement stage it composes, whether settling through that stage's mechanism delivers
through the domain's capacity-backed fulfillment. The declaration MUST be required of
every stage, so a stage that does not make it cannot be composed, and MUST NOT
default.

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

#### Scenario: A stage omits the declaration

- **WHEN** a domain composes a settlement stage that does not declare whether it delivers through capacity
- **THEN** the stage cannot be constructed, and the storefront does not start
