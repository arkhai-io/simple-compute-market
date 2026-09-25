## ADDED Requirements

### Requirement: A bare-metal listing carries its Physical Resource's shape

Every bare-metal listing MUST carry a family-grouped capability shape matching the
declared dimensions of the Physical Resource it offers, derived through the shared
capability-shape utility. The shape's quantities and attributes MUST be published as
top-level fields of the listing resource under the compute family's wire names, so
the compute schema's dimension filters evaluate bare-metal listings as they evaluate
VM listings. A bare-metal listing's derivation identity MUST remain its site and
Physical Resource.

#### Scenario: A buyer filters compute supply by GPU model

- **WHEN** a buyer queries a compute registry for a GPU model that a published
  bare-metal listing's Physical Resource declares
- **THEN** the bare-metal listing is returned

#### Scenario: Two Physical Resources declare the same dimensions

- **WHEN** two Physical Resources in one pool declare identical dimensions
- **THEN** each publishes its own listing, and both listings carry the same shape

### Requirement: Bare metal joins the site-scoped pool-override store

A bare-metal storefront MUST contribute a market vocabulary for the `bare_metal`
offering mode to the site-scoped pool-override store, so an operator may state the
storefront's own terms for one pool at one site through the same store, API, and
status reporting as VM.

#### Scenario: A bare-metal override is written

- **WHEN** an operator writes an override for a pool at a configured site in the
  `bare_metal` offering mode
- **THEN** bare metal validates it and it applies only to that site's pool's
  bare-metal listings
