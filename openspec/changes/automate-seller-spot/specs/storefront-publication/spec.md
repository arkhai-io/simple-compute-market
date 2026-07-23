## ADDED Requirements

### Requirement: Interruptible agreement control and decision evidence

A storefront MUST expose an authenticated view of active interruptible agreements with references to their listing, agreement, site reservation/fulfillment, and settlement state. Every dry-run or live strategy evaluation MUST have durable stable identity and record policy/version/config digest, referenced inputs, decision/reason, mode, and resulting operation identifiers.

#### Scenario: Strategy evaluates an agreement in dry-run mode

- **WHEN** an authorized runner evaluates an active interruptible agreement without live execution
- **THEN** no lease or settlement mutation occurs and durable decision evidence records the proposed action and rationale

#### Scenario: Agreement changes before live action

- **WHEN** referenced agreement/site/settlement state no longer matches the evaluated input
- **THEN** live execution stops or reevaluates rather than applying the stale decision

#### Scenario: Operator inspects partial interruption

- **WHEN** settlement, truncation, teardown, or release has not converged
- **THEN** the control view reports each authoritative step separately and does not claim one event proves completion
