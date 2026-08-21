## MODIFIED Requirements

### Requirement: Hosted consumer configuration pins the expanded release

Enabling any expanded hosted profile MUST pin one exact verified hosted manifest, client wheel, API/schema version, payer-profile contract, funding-authorization contract, funding-profile set, identity capability, disbursement capability, and service image identity. Buyer and storefront roles MUST agree on those public pins before publication or authorization. Marketplace schemas MUST reject hosted provider, Customer, PaymentMethod, mandate, webhook, database, migration, and administrator fields.

Those pins MUST be taken from the hosted release the run bound. A consumer MUST NOT carry an API version, schema version, or capability set of its own that a bound release is then measured against, because a consumer that names one release in its own configuration cannot admit the next one, and reports a genuine contract disagreement as a configuration edit that was not made. Where a run binds a release, the rendered consumer configuration MUST state that release's coordinates; where no release is bound, no consumer configuration MUST be rendered at all.

Whether a bound release can disburse a split obligation MUST be one of the declared capabilities read from that release. Accepted terms whose condition evaluation can produce a partial disposition MUST be refused before acceptance against a release that declares no such capability, because a plan that can only be discovered to be unsettleable at disbursement has already taken the payer's money.

Enforcement MUST NOT weaken. A disagreement between the bound release and the composed authority MUST fail closed before publication or authorization exactly as it does when the pins are written down.

#### Scenario: Buyer and storefront pins differ

- **WHEN** the buyer expects a different payer/profile capability or client identity from the publishing storefront's verified authority release
- **THEN** compatibility fails before terms acceptance or payer authorization

#### Scenario: A run binds a hosted release the consumer has never seen

- **WHEN** a run binds a hosted release whose API version, schema version, or capability set differs from every release bound before it
- **THEN** the rendered consumer configuration pins that release's own coordinates and the run proceeds, without a change to consumer source

#### Scenario: The composed authority contradicts the bound release

- **WHEN** the authority a run composed serves an API version, schema version, or capability set other than the one the run bound
- **THEN** the run fails closed before publication or payer authorization and names the disagreement

#### Scenario: Terms admit a split the bound release cannot execute

- **WHEN** offered terms name a condition evaluator whose decision can owe part of the obligation to each party, and the bound hosted release declares no partial-disposition capability
- **THEN** the terms are refused before acceptance, naming the bound release's capability set, and no obligation is materialized against them
