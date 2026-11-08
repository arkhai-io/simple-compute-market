## ADDED Requirements

### Requirement: A storefront retires registry listings it does not hold open

This requirement governs VM, API-credit, and bare-metal publication, beside the convergence of the listings a storefront records.

Every publication pass MUST list, at each configured registry it can reach, the open listings published under the storefront's own publisher principal for the offering modes it serves, and MUST close at that registry each one the storefront does not hold open locally, whether it is closed locally or unknown to the storefront. Listings of an offering mode the storefront does not serve MUST be left as they are. A registry it cannot reach MUST be skipped and swept by a later pass. A preview pass MUST report each such close without making it.

#### Scenario: A registry holds an open listing the storefront has no record of

- **WHEN** a registry holds an open listing published under the storefront's principal, for an offering mode it serves, that the storefront does not record
- **THEN** the next publication pass closes it at that registry and reports the close with the reason that the storefront does not hold it

#### Scenario: A listing closed locally is still open at a registry the storefront no longer records

- **WHEN** a listing the storefront closed locally is open at a configured registry for which the storefront holds no publication record
- **THEN** the next publication pass closes it at that registry

#### Scenario: Another storefront's offering mode under the same principal

- **WHEN** the VM storefront and the bare-metal storefront publish under one principal and the VM storefront's pass finds an open bare-metal listing it does not record
- **THEN** it leaves that listing open

#### Scenario: A preview pass finds a listing it does not hold

- **WHEN** a preview publication pass finds an open registry listing the storefront does not hold open
- **THEN** it reports the close it would make and changes nothing at the registry

#### Scenario: A registry is unreachable during the sweep

- **WHEN** a configured registry cannot be reached during a publication pass
- **THEN** the pass sweeps the other registries and that registry is swept by a later pass
