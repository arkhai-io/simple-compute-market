## MODIFIED Requirements

### Requirement: Scalar negotiation participation is a mechanism declaration

A settlement mechanism's registration MUST declare whether it negotiates a scalar
amount. For a scalar-declaring mechanism, the existing strict behavior applies,
including rejection of a proposal missing the amount. For a mechanism that declines
the scalar, negotiation MUST proceed take-it-or-leave-it over the published option,
the missing-amount rejection MUST NOT apply, and buyer ordering MUST treat its
listings as priceless.

A seller's default negotiation policy MUST accept an exact selection of an
advertised option that bargains no amount once the selection and the inventory
behind it have passed the seller's guards, and no scalar bargaining policy MAY
counter such a selection: a policy that waits for an amount the option never
carries would counter it forever. A buyer MUST accept a seller acceptance that
carries no amount for such an option, and MUST refuse one that omits the amount for
an option bargained through an `amount` rate; a rate on any other field does not
make an option bargain an amount.

#### Scenario: A non-scalar mechanism reaches acceptance

- **WHEN** a buyer opens negotiation with a settlement selection for a mechanism that
  declares no scalar and no `fields.amount`
- **THEN** the round is not rejected for a missing amount and the negotiation can
  reach acceptance on the published option's terms

#### Scenario: The default policy accepts an unpriced selection

- **WHEN** a buyer opens negotiation with an exact selection of an advertised option
  that bargains no amount, under the seller's default policy
- **THEN** the seller accepts on the published option's terms rather than countering

#### Scenario: The buyer distinguishes an amount rate from other rates

- **WHEN** a seller accepts with no amount a selected option whose only rate is on a
  field other than `amount`
- **THEN** the buyer accepts the agreement
- **AND** an amountless acceptance of an option with an `amount` rate is refused

#### Scenario: A scalar mechanism keeps the guard

- **WHEN** a buyer opens negotiation under a scalar-declaring mechanism without an
  amount
- **THEN** the proposal is rejected exactly as today
