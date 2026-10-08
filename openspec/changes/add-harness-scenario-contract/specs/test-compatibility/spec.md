## ADDED Requirements

### Requirement: Capacity scenarios are finite, declared, and non-executing
The harness MUST validate exactly the finite set of capacity scenarios it
declares, and MUST refuse a declaration outside that set naming the constraint
violated. Validating a declared scenario MUST perform no market, wallet, cloud,
host, provisioning, VM, GPU, or authenticated repository-hosting action.
Validation MUST report every violation found in one pass rather than only the
first.

#### Scenario: A declaration falls outside the finite set
- **WHEN** a scenario declares a deal type, GPU topology, or actor topology the
  set does not contain
- **THEN** validation refuses it and names the constraint it violated

#### Scenario: A declaration is internally inconsistent
- **WHEN** a scenario's declared successes and declared refusals do not
  reconcile with its declared actor counts
- **THEN** validation refuses it, rather than accepting a declaration whose
  outcome could never be satisfied

#### Scenario: Several declarations are wrong at once
- **WHEN** a scenario set is validated and more than one declaration is
  inadmissible
- **THEN** every inadmissible declaration is reported from one validation

#### Scenario: The declared set is validated
- **WHEN** validation runs over the declared set
- **THEN** no external system is contacted and no process is started on behalf
  of a scenario

### Requirement: A scenario declares the capacity hold posture it assumes
A scenario whose expectations depend on concurrent contention MUST declare
whether it assumes capacity is held before settlement. A scenario that omits the
declaration MUST be refused. A recorded result produced against a target whose
hold posture differs from the declaration MUST be classified as inadmissible
rather than as a failed expectation.

#### Scenario: A contention scenario omits the posture
- **WHEN** a scenario declares concurrent buyers and no hold posture
- **THEN** validation refuses it, because its refusal expectations are not
  evaluable without one

#### Scenario: A result was produced under the other posture
- **WHEN** a recorded result names a target whose hold posture differs from the
  scenario's declaration
- **THEN** the result is inadmissible and the mismatch is reported, and the
  product is not reported as having misbehaved

### Requirement: Refusal expectations name a match mode
A declared refusal MUST name the status, the stable error code, and how its
reason is to be matched. A scenario MUST NOT assert equality against a reason
the product emits with interpolated content. A scenario MUST NOT assert on the
interpolated content itself.

#### Scenario: A scenario asserts equality on an interpolated reason
- **WHEN** a declared refusal requires an exact reason match against a reason
  the product emits with interpolated detail
- **THEN** validation refuses the declaration, naming the reason and the match
  modes permitted for it

#### Scenario: A refusal is declared for a stable reason
- **WHEN** a declared refusal names a reason the product emits verbatim
- **THEN** an exact match is permitted

### Requirement: Contending buyers prove discovery before arrival
A scenario declaring more than one concurrent buyer MUST require, for each
buyer, evidence that it observed its assigned listing through its assigned
market before the arrival barrier released. A recorded result missing that
evidence for any buyer MUST be inadmissible.

#### Scenario: A buyer's discovery evidence is absent
- **WHEN** a recorded contention result carries no discovery evidence for one of
  its buyers
- **THEN** the result is inadmissible, and the buyer's outcome is not counted as
  scarcity

#### Scenario: A buyer never observed its listing
- **WHEN** a buyer's discovery evidence shows it did not observe its assigned
  listing before the barrier released
- **THEN** the outcome is classified as an environment outcome rather than as
  expected scarcity or as a product defect

### Requirement: Multi-market contention is declared over markets, not seller processes
A scenario asserting contention over one physical resource MUST declare that
contention across the markets the resource is listed on, and MUST NOT declare
several seller processes competing for it. A scenario declaring several
storefronts contending for one resource MUST be refused. A result from a
multi-market scenario MUST NOT be reported as evidence about competition
between seller processes, cross-storefront arbitration, or per-seller
fulfillment isolation.

#### Scenario: A scenario declares several storefronts contending for one resource
- **WHEN** a scenario declares more than one storefront competing for a single
  physical resource
- **THEN** validation refuses it, because one storefront serves one site and the
  fulfillment callback binds to one storefront

#### Scenario: A resource is listed on several markets and buyers arrive together
- **WHEN** a scenario declares one resource published to several registries,
  with buyers assigned to different registries and released on a common barrier
- **THEN** exactly one success is expected, every other buyer carries a declared
  refusal signature, and the sold capacity is expected absent from every
  registry the listing was published to

#### Scenario: A buyer is assigned a market the listing was not published to
- **WHEN** a scenario assigns a buyer to a market the declared listing does not
  reach
- **THEN** validation refuses it, rather than declaring a buyer that could only
  ever fail to discover

#### Scenario: Several storefronts publish to one market
- **WHEN** a scenario declares one registry indexing listings from several
  storefronts with separate resources
- **THEN** it declares no scarcity, because the sellers are not competing, and
  its result is not evidence about the resource fence
