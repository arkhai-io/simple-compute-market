## ADDED Requirements

### Requirement: A settlement stage event carries the domain's settlement identity

A domain's settlement stage events MUST carry the settlement identity that domain's own
records are keyed by, in addition to the mechanism-neutral claim reference the core engine
emits. A caller correlating a claim with the deal it settles has the domain identity and
not the neutral one, and an event carrying only the neutral reference cannot be joined to
the deal without knowing the two are equal for the mechanism in use.

The translation MUST occur at the domain's own event seam. Core claim carriers and the
claims engine MUST continue to emit only the mechanism-neutral reference, so that mechanism
vocabulary does not enter a core carrier.

#### Scenario: A submitted claim is correlatable to its deal

- **WHEN** a storefront records that it has submitted a seller claim
- **THEN** the recorded event carries both the mechanism-neutral claim reference and the
  domain's settlement identity for that deal, and the two agree

#### Scenario: Core remains mechanism-neutral

- **WHEN** the core claims engine emits a claim lifecycle event
- **THEN** it names only the mechanism-neutral claim reference, and any domain identity is
  added by the composing domain rather than by the engine
