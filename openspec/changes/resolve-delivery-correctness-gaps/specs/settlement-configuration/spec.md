## ADDED Requirements

### Requirement: A storefront reads again a registry whose recommendations it could not read

A storefront MUST keep, for each registry it publishes through, whether its last descriptor read succeeded and when it last failed. Each publication cycle MUST read again, before composing listing options, every registry whose last read failed, so that its recommended dispute authorities reach the first publication after it answers, without a restart. A successful read MUST be kept until the storefront restarts. While a registry is unread and `use_registry_dispute_authorities` is true, the readiness of each mechanism whose options name a dispute authority MUST report, in its public details under `dispute_authorities_unread`, each unread registry and when its read last failed. The report MUST NOT be a readiness blocker and MUST NOT change the mechanism's readiness: the options the storefront's local dispute entries allow MUST still be published while a registry is unread. The storefront's health MUST NOT depend on it.

#### Scenario: A storefront starts before its registry

- **GIVEN** a storefront whose startup read of its registry's descriptor failed, so it offers no option naming a recommended authority
- **WHEN** the registry answers and the next publication cycle runs
- **THEN** the cycle reads the registry's recommendations and publishes the options they allow, without a restart

#### Scenario: A registry is still unread

- **WHEN** an operator reads the settlement status of a storefront whose registry has not been read
- **THEN** each mechanism whose options name a dispute authority reports `dispute_authorities_unread` in its public details, naming the registry and when its read last failed, with no readiness blocker for it, and the storefront's health is unaffected

#### Scenario: A storefront with local authorities whose registry is unread

- **GIVEN** a storefront with `use_registry_dispute_authorities` true and a local dispute entry its options can use
- **WHEN** its registry's descriptor read fails and a publication cycle runs
- **THEN** the options the local entry allows are published, the mechanism stays ready, and its readiness reports the unread registry

#### Scenario: A registry was read

- **WHEN** a publication cycle runs after a registry's descriptor was read successfully
- **THEN** the registry is not read again until the storefront restarts
