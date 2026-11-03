## MODIFIED Requirements

### Requirement: A capacity declaration names no mandatory dimension

A capacity authority MUST accept a declaration expressing any non-empty set of
dimensions, MUST refuse a declaration expressing none, and MUST NOT write a
dimension the caller did not declare. Where a legacy scalar unit mirror is
maintained, the dimension it mirrors MUST be supplied by the composition root, the
way domain-specific claim aliases already are, rather than fixed in the shared
capacity module.

Where a caller declares capacity explicitly, the authority MUST NOT add a mirror
dimension to that declaration. The legacy scalar unit total MUST be optional, and
MUST be absent where the declaration names no mirror dimension — the existing
consistency check between the scalar and its mirrored dimension compares them when
both are present, so absence rather than a substituted zero is what keeps that check
meaningful. A declaration naming only dimensions a domain owns —
for example a credit balance with no compute dimension — MUST be stored as declared.

#### Scenario: A declaration names no compute dimension

- **WHEN** an operator declares capacity consisting only of a domain's own unit dimension
- **THEN** the stored declaration contains exactly that dimension
- **AND** no GPU or other compute dimension is manufactured

#### Scenario: A declaration names no dimension

- **WHEN** a declaration names no dimension: its `capacity` map is empty or absent,
  and no legacy scalar total stands in for it
- **THEN** the declaration is refused, and no declaration is written or changed

#### Scenario: A declaration has no mirror dimension to total

- **WHEN** a declaration names no dimension the legacy scalar mirrors
- **THEN** the scalar unit total is absent rather than zero
- **AND** the consistency check between the scalar and its mirrored dimension does not apply

#### Scenario: A legacy single-quantity claim is translated

- **WHEN** a claim requests a unit count through a legacy single-quantity key rather
  than a dimensions map
- **THEN** it is translated to the composition's mirror dimension, and the matching,
  held-quantity, and payload mirror fields all read that same dimension

#### Scenario: A composition supplies its mirror dimension

- **WHEN** a composition root configures which dimension the legacy scalar mirror tracks
- **THEN** that dimension is used for the mirror in that composition
- **AND** no other composition's dimension name appears in it

#### Scenario: A claim names another domain's dimension as an attribute

- **GIVEN** a composition whose mirror dimension and unit claim keys do not include
  `gpu_count`
- **WHEN** a claim requires `gpu_count` equal to a resource's unit total
- **THEN** the resource does not match, because the unit total is a matchable fact
  only under the composition's own mirror dimension
