## ADDED Requirements

### Requirement: Compute buyers can discover by derived class

Both compute buyer CLIs MUST accept `--class reserved|on_demand|spot` as a shorthand
over actual option terms, never a stored listing or Agreement field. Reserved MUST
mean prepaid and non-interruptible; on-demand MUST mean recurring with payer and no
payee entitlement; spot MUST mean recurring with payer and payee entitlements.
A setup once part beside a rate MUST remain recurring. No match MUST NOT enable a
disabled mechanism, relax the class or permit post-acceptance substitution.

#### Scenario: Mixed-option listing

- **WHEN** a buyer selects spot on a listing with reserved, on-demand and spot options
- **THEN** only eligible spot option identities reach negotiation

#### Scenario: Existing splitter is not a named recurring product

- **WHEN** the only option is a prepaid interruptible Alkahest splitter
- **THEN** none of reserved, on-demand or spot matches it

#### Scenario: Explain without buying

- **WHEN** the buyer uses class with explanation mode
- **THEN** the output deterministically shows expanded predicates, resource/option survivors and rejection categories
- **AND** no negotiation, settlement or provider mutation occurs
