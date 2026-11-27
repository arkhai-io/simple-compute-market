## ADDED Requirements

### Requirement: A migration that frees space is followed by compaction

A migration MAY declare that it frees space. When a migration so declared is applied to
a SQLite database, the service's migration command MUST compact the database with
`VACUUM` after applying the chain, outside any transaction, before the application
starts; the check mode MUST NOT compact. The release that introduces the version 3
request profile MUST drop the version 2 replay tables — the storefronts'
`auth_replay_reservations`, the provisioning service's
`provisioning_replay_reservations`, and the registry's `publisher_replay_reservations` —
by such a migration, or for the registry by an Alembic revision.

#### Scenario: A storefront upgrades from marketplace 0.4.0

- **WHEN** a storefront's migration command applies the migration dropping `auth_replay_reservations` to a database holding it
- **THEN** the table is gone, the database file is compacted to its remaining data, and the application starts afterwards

#### Scenario: An operator previews the upgrade

- **WHEN** the migration command runs with `--check` against that database
- **THEN** it lists the pending migration and neither drops nor compacts anything

### Requirement: The deal-lifecycle transport rows are deleted on upgrade

The deal-lifecycle routes MUST NOT keep a reservation of their own beside the admission
core's. A migration in deal-servicing's chain MUST delete the `_lifecycle_transport`
rows earlier releases wrote into `servicing_operations`, declared as freeing space, and
MUST leave every other row and every lifecycle evidence item in place.

#### Scenario: A storefront upgrades with lifecycle transport rows

- **WHEN** a storefront database holding `_lifecycle_transport` rows from marketplace 0.4.0 is migrated
- **THEN** those rows are gone, the deal's operation rows and lifecycle evidence remain, and the SQLite file is compacted after the chain applies

### Requirement: The authenticated-request replay table belongs to its kit

The authenticated-request replay table MUST be created by migrations the
authenticated-requests kit exports, composed into each authority's chain in its fixed
order, and mirrored in the registry by an Alembic revision. Each authority MUST hold the
table in its own database.

#### Scenario: A fresh provisioning database is migrated

- **WHEN** the provisioning service's migration command runs against an empty database
- **THEN** the replay table is created by the kit's migration in the chain's order, and no table is created when a store opens
