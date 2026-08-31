## ADDED Requirements

### Requirement: Scalar negotiation participation is a mechanism declaration

A settlement mechanism's registration MUST declare whether it negotiates a scalar
amount. For a scalar-declaring mechanism, the existing strict behavior applies,
including rejection of a proposal missing the amount. For a mechanism that declines
the scalar, negotiation MUST proceed take-it-or-leave-it over the published option,
the missing-amount rejection MUST NOT apply, and buyer ordering MUST treat its
listings as priceless.

#### Scenario: A non-scalar mechanism reaches acceptance

- **WHEN** a buyer opens negotiation with a settlement selection for a mechanism that
  declares no scalar and no `fields.amount`
- **THEN** the round is not rejected for a missing amount and the negotiation can
  reach acceptance on the published option's terms

#### Scenario: A scalar mechanism keeps the guard

- **WHEN** a buyer opens negotiation under a scalar-declaring mechanism without an
  amount
- **THEN** the proposal is rejected exactly as today
