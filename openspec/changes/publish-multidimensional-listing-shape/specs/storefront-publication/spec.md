## ADDED Requirements

### Requirement: Published candidates carry declared capacity

A published listing candidate MUST carry every capacity dimension the site projection
declares for the underlying resource, using the domain's own dimension vocabulary. A
dimension the projection does not declare MUST be omitted from the published candidate
rather than defaulted, zero-filled, or inferred from provisioning fallbacks or host
inventory. The set of publishable dimensions MUST be derived from the domain's declared
vocabulary rather than from a fixed list held in the publication path.

#### Scenario: Projection declares several capacity dimensions

- **WHEN** a storefront publishes a candidate for a resource whose projection declares
  several capacity dimensions
- **THEN** every declared dimension appears on the published candidate

#### Scenario: Projection declares only some dimensions

- **WHEN** a resource's projection declares some capacity dimensions and not others
- **THEN** the undeclared dimensions are absent from the published candidate, and no
  provisioning default or host inventory value is substituted for them

#### Scenario: Buyer filters discovery on a capacity dimension

- **WHEN** a buyer filters discovery on a capacity dimension that a listing declares
- **THEN** the listing is matched or excluded on its declared value rather than
  excluded for want of the field

#### Scenario: Domain declares a new capacity dimension

- **WHEN** a domain's dimension vocabulary gains a dimension and a projection declares
  it
- **THEN** it is published without editing the publication path
