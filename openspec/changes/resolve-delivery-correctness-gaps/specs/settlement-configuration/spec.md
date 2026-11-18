## ADDED Requirements

### Requirement: A storefront reads again a registry whose recommendations it could not read

A storefront MUST keep, for each registry it publishes through, whether its last descriptor read succeeded and when it last failed. Each publication cycle MUST read again, before composing listing options, every registry whose last read failed, so that its recommended dispute authorities reach the first publication after it answers, without a restart. A successful read MUST be kept until the storefront restarts. While a registry is unread and `use_registry_dispute_authorities` is true, the storefront's settlement readiness MUST report the blocker `dispute_authorities_unread` on each mechanism whose options name a dispute authority, naming the registry and when its read last failed. The storefront's health MUST NOT depend on it.

#### Scenario: A storefront starts before its registry

- **GIVEN** a storefront whose startup read of its registry's descriptor failed, so it offers no option naming a recommended authority
- **WHEN** the registry answers and the next publication cycle runs
- **THEN** the cycle reads the registry's recommendations and publishes the options they allow, without a restart

#### Scenario: A registry is still unread

- **WHEN** an operator reads the settlement status of a storefront whose registry has not been read
- **THEN** each mechanism whose options name a dispute authority reports the blocker `dispute_authorities_unread`, naming the registry and when its read last failed, and the storefront's health is unaffected

#### Scenario: A registry was read

- **WHEN** a publication cycle runs after a registry's descriptor was read successfully
- **THEN** the registry is not read again until the storefront restarts
