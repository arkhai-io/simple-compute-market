## ADDED Requirements

### Requirement: Compute discovery consumes common lifecycle projections

Compute discovery MUST consume the shared codec's common
`early_termination.payer`, `early_termination.payee`,
`early_termination.payee.notice_seconds`, `early_termination.premature_stop_penalty`, `adjudication.dispute.interface` and
`adjudication.dispute.account` projections. Billing period MUST remain the registered
`arkhai_payments.period` projection. Shared selection MUST NOT decode opaque
mechanism params or depend on the final placement of common terms.

#### Scenario: Buyer asks for seller notice

- **WHEN** a clause requests payee entitlement and at least 120 seconds payee notice
- **THEN** both predicates are evaluated by the common codec on the same option
- **AND** an absent payee notice is not treated as zero

#### Scenario: Malformed option has no usable class

- **WHEN** common terms contain an unsupported version or invalid entitlement
- **THEN** the option fails validation rather than being classified by missing-field fallback

### Requirement: Penalty projection is asset-correlated

Compute discovery MUST consume the foundation-owned premature_stop_penalty projection under cli-query-language's “Settlement fields have common and mechanism-owned namespaces”. Penalty predicates MUST correlate with asset and every other predicate on that same option. A positive match MUST NOT replace buyer acceptance policy or claim money remains held.

#### Scenario: Penalty and asset belong to different options

- **WHEN** one option satisfies the requested asset and another alone satisfies the penalty floor
- **THEN** their combination does not qualify either option

### Requirement: Class expansion narrows every settlement alternative

A compute class shortcut MUST compile to typed predicates over registered billing
kind and common entitlements, with release-condition eligibility for prepaid
options. It MUST conjoin those predicates with every explicit settlement
alternative. It MUST NOT create an OR alternative, fabricate a duration sentinel
for absent period, or silently extend the public comparison grammar. Explanation
MUST show the typed expansion and actual local/pushed evaluation.

#### Scenario: Class and explicit alternatives

- **WHEN** a buyer requests spot with two explicit settlement clauses
- **THEN** each alternative requires recurring billing and payer/payee entitlements
- **AND** no non-spot option survives by satisfying only an explicit clause
