## ADDED Requirements

### Requirement: Compute listings carry two capacity bounds

Compute listings MUST carry resolved `max_duration_seconds` and MAY carry
`available_until_utc` as listing-level capacity facts. Resolution MUST prefer
storefront override, then pool hint, then configured default per offering mode.
The relative bound limits any deal's lifetime; the absolute UTC bound limits every
lease end. A later publication MUST NOT extend an accepted Agreement.

#### Scenario: Absolute date overrides a hint

- **WHEN** the pool and storefront override state different availability dates
- **THEN** the published listing uses the override while retaining the independently resolved relative bound

### Requirement: Compute product classes are derived options

Publication MUST retain existing capacity/shape listing identity while offering
separately priced billing/entitlement combinations. Reserved, on-demand and spot
MUST NOT be stored class fields. Recurring options MUST use shared early-termination
and adjudication terms; an on-demand option MUST grant no payee stop entitlement.
Unsupported lifecycle promises MUST NOT be synthesized for the Alkahest splitter.

#### Scenario: Three hosted products share capacity

- **WHEN** a pool offers prepaid, payer-only recurring and payer/payee recurring presets
- **THEN** one listing offers separately priced reserved, on-demand and spot options
- **AND** none creates independent capacity

#### Scenario: Existing splitter option

- **WHEN** an existing Alkahest splitter option is published
- **THEN** its accepted release condition and current service terms remain authoritative
- **AND** no unsupported lifecycle terms are invented to label it

### Requirement: Unbounded recurring candidates close independently

A recurring candidate with no positive finite seller bound MUST yield no recurring
option and a derivation diagnostic. This absence alone MUST NOT hold a readable
pool or suppress a valid reserved candidate. Bare metal's existing reserved-bound
admission rule MUST remain intact.

#### Scenario: Unbounded VM pool retains reserved sales

- **WHEN** a readable VM pool has no finite bound and has a valid reserved candidate
- **THEN** recurring options are omitted with a close reason and the reserved option remains

### Requirement: Recurring publication checks servicing

Publication MUST omit recurring candidates when composition does not declare
compatible rate servicing. It MUST derive the declaration from composition, not
listing terms; if no option remains it MUST use existing no-settlement-option
diagnostics. There MUST NOT be a bare-metal minimum-spend publication gate.

#### Scenario: Dark recurring product

- **WHEN** rate servicing is undeclared but a pool offers recurring and valid reserved candidates
- **THEN** only the reserved option publishes

#### Scenario: Bare-metal preset without minimum spend

- **WHEN** a bounded bare-metal recurring candidate has compatible servicing and no minimum-spend term
- **THEN** minimum-spend absence alone does not block publication
