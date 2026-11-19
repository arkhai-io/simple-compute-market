## ADDED Requirements

### Requirement: A storefront reads again a registry whose recommendations it could not read

A storefront MUST keep, for each registry it publishes through, whether its last descriptor read succeeded and when it last failed. Each time it composes listing options — at each publication cycle in the VM and bare-metal storefronts, and when the API-credit storefront creates or seeds a listing — a storefront MUST first read again every registry whose last read failed, so that its recommended dispute authorities reach the first options composed after it answers, without a restart. A successful read MUST be kept until the storefront restarts. While a registry is unread and `use_registry_dispute_authorities` is true, the readiness of each mechanism whose options name a dispute authority MUST report, in its public details under `dispute_authorities_unread`, each unread registry and when its read last failed; each such mechanism's registration MUST allowlist that public detail, and its preflight MUST take it from the readiness resources the storefront supplies. The report MUST NOT be a readiness blocker and MUST NOT change the mechanism's readiness: the options the storefront's local dispute entries allow MUST still be published while a registry is unread. The report MUST be shown in each mechanism's readiness on the storefront's system status route (`GET /api/v1/system/status`); the `settlement status` command, which checks configuration in its own process, does not carry it. The storefront's health MUST NOT depend on it.

#### Scenario: A storefront starts before its registry

- **GIVEN** a storefront whose startup read of its registry's descriptor failed, so it offers no option naming a recommended authority
- **WHEN** the registry answers and the storefront next composes listing options
- **THEN** it reads the registry's recommendations and publishes the options they allow (or, in the API-credit storefront, accepts a listing they allow), without a restart

#### Scenario: A registry is still unread

- **WHEN** an operator reads a storefront's system status (`GET /api/v1/system/status`) while its registry has not been read
- **THEN** each mechanism whose options name a dispute authority reports `dispute_authorities_unread` in its public details, naming the registry and when its read last failed, with no readiness blocker for it, and the storefront's health is unaffected

#### Scenario: A storefront with local authorities whose registry is unread

- **GIVEN** a storefront with `use_registry_dispute_authorities` true and a local dispute entry its options can use
- **WHEN** its registry's descriptor read fails and the storefront composes listing options
- **THEN** the options the local entry allows are published, the mechanism stays ready, and its readiness reports the unread registry

#### Scenario: A registry was read

- **WHEN** the storefront composes listing options after a registry's descriptor was read successfully
- **THEN** the registry is not read again until the storefront restarts

#### Scenario: One of several registries could not be read

- **GIVEN** a storefront publishing through two registries, whose last read succeeded for one and failed for the other
- **WHEN** the storefront composes listing options
- **THEN** it reads again only the registry whose read failed, and keeps the other's recommendations
