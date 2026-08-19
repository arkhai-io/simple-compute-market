## ADDED Requirements

### Requirement: Pre-terms mechanism dispatch is registration-owned

The settlement mechanism for a deal MUST be resolved exactly once, from the buyer's
settlement selection or the legacy flat-proposal coercion, and every subsequent
mechanism-shaped decision — proposal interpretation, verification, accepted-artifact
construction, settle-route and status projection — MUST reach the resolved mechanism's
registration hooks. Domain code MUST NOT branch on a concrete mechanism identifier at
these decision points.

#### Scenario: A third mechanism is composed

- **WHEN** a new mechanism registration is added to a domain's composition root and
  enabled in `[Settlement]`
- **THEN** its deals negotiate, verify, settle, and report through the registration
  hooks with no new conditional arms in any domain

#### Scenario: A mechanism conditional is sought in domain code

- **WHEN** the pre-terms path of any composed domain is inspected
- **THEN** no `if <mechanism> … else` branch on a concrete mechanism identifier exists
  outside the composition root's registration list

### Requirement: Deal identity is mechanism-neutral for every mechanism

Every deal, regardless of mechanism, MUST have a durable `settlement_obligations`
record keyed by its `obligation_ref`, with any mechanism-issued identifier (such as an
escrow uid) recorded as that mechanism's `mechanism_ref`. Cross-mechanism tooling MUST
correlate deals by `obligation_ref`.

#### Scenario: An Alkahest deal is recorded neutrally

- **WHEN** an Alkahest deal settles
- **THEN** it has a `settlement_obligations` record whose `mechanism_ref` is the
  escrow uid, in addition to its legacy mechanism-surface records
