## ADDED Requirements

### Requirement: A seller may state details beside the listing envelope

A storefront MUST accept the seller-authored detail fields — `title`, `description`, and `metadata` — on its seller create surfaces, validates them against the limits the registry serves, stores them on the local listing row, and publishes them to every registry. Stored values survive resume and reconciliation-driven republication.

#### Scenario: A storefront create request carries seller details

- **WHEN** a seller's create request states `title`, `description`, or `metadata`
- **THEN** the storefront stores and publishes them, and a registry GET returns them unchanged under the listing signature

### Requirement: A compute listing derives its details from the pool override

A domain's publication cycle MUST treat a pool override's `details` as a term of sale: every listing the pool publishes carries them.

#### Scenario: A pool override states details

- **WHEN** a domain's publication cycle derives a listing from a pool whose storefront override states `details`
- **THEN** the listing publishes with those details, a cycle refreshes them in place when the override's details change, and an override that stops stating them clears them from its listings

### Requirement: An API-credit listing carries its seller's prose

A quota-backed API-credit publish SHALL treat its request's `description` as both the seller's prose beside the listing envelope and the service description inside the listing resource, so established consumers read it where they always have.

#### Scenario: A quota-backed publish states a description

- **WHEN** a quota-backed publish request states `description`
- **THEN** the description publishes beside the listing envelope and, unchanged, inside the listing resource its established consumers already read
