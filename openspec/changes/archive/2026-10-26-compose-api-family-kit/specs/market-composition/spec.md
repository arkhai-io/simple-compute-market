## ADDED Requirements

### Requirement: The api family shares one access vocabulary and kit

API credits, and every API-selling domain that follows it, MUST form the `api`
family, with one vocabulary package under `domains/api` and one family kit of
distributions beneath it, placed under the family directory the scope rule
names. Neither domain MUST define the purchase shape, issuance digests, key
authority, issuance composition, buyer flows, mechanism stages, or bearer gate
of its own, and neither MUST obtain them by importing the other. A third
domain selling prepaid bearer access MUST be able to compose the kit by
supplying contributions alone, without the kit learning its listing schema or
branching on its identity; access sold without a prepaid balance — by
subscription, by invoice, or under a provider's own authentication — is outside
the kit's scope until its ledger-free distribution exists.

#### Scenario: API credits composes the kit

- **WHEN** the API-credits storefront, authority service, gated sample app, and
  buyer plugin are built
- **THEN** each imports the family distributions and no other domain, and the
  architecture check classifies every family project from its path with no
  override row

#### Scenario: A third prepaid-access domain is added

- **WHEN** a new domain under the `api` family selling prepaid bearer access
  supplies its selling and buying bundles, its capacity profile, and its
  service root
- **THEN** it composes the storefront, authority, gate, and buyer flows without
  a change to any `domains/api` distribution
