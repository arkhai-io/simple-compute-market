## ADDED Requirements

### Requirement: Pool-declared offering modes

Each Resource Pool MUST declare the set of offering modes its configured provider can deliver under the domain-neutral `deliverable_modes` policy tag. The shared resource-pool capability MUST validate this declaration as a JSON-compatible set of unique, non-empty strings and expose typed resolution and membership behavior without defining which names are meaningful to a domain. An absent or empty declaration authorizes no mode and MUST NOT be widened by a default.

Create, replace, patch, bulk import, projection, and canonical export MUST use the existing policy-tag channel and precedence. An existing pool's initial set MUST be derived only from durable provider, playbook, and registered requirement-delegate configuration that proves the pool can deliver that mode. Derivation MUST include the system-owned `default` pool, MUST NOT use reservation history as capability evidence, MUST replace an unproved legacy declaration with the exact proved set, and MUST report each derived set at INFO.

#### Scenario: Pool declares two modes

- **WHEN** an operator stores `deliverable_modes: [bare_metal, vm]`
- **THEN** typed resolution returns exactly those two opaque mode names through ordinary projection and administration paths

#### Scenario: Declaration is absent

- **WHEN** a Resource Pool has no `deliverable_modes` tag
- **THEN** typed resolution returns an empty set and the pool delivers no offering mode

#### Scenario: Existing default pool is migrated

- **WHEN** the default pool has an Ansible playbook and the registered VM requirement delegate
- **THEN** migration declares exactly `vm`, reports that conclusion, and does not infer another mode from historical reservations

#### Scenario: Legacy declaration is wider than configuration

- **WHEN** a pool's durable provider configuration proves no deliverable mode but its legacy policy metadata names one or more modes
- **THEN** migration narrows the declaration to empty rather than retaining an unproved capability

#### Scenario: Declaration is malformed

- **WHEN** any Resource Pool write supplies a non-list, duplicate, empty, or non-string deliverable mode
- **THEN** validation rejects the write without changing the pool
