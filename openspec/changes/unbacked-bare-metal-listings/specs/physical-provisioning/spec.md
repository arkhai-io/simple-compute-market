## ADDED Requirements

### Requirement: A failure after authentication is answered signed

A provisioning authority, and every service authenticating through the site kit's
middleware, MUST answer a request that fails after it was authenticated — a route
raising an unexpected error — with a signed 500 response carrying a fixed detail that
reveals nothing of the error, and MUST record that response as the request's replay
outcome, so an exact retry receives the same signed answer rather than an unsigned one
or an in-progress refusal. The error itself MUST be logged by the service.

#### Scenario: A route raises after authentication

- **WHEN** an authenticated request reaches a provisioning route that raises an
  unexpected error
- **THEN** the caller receives a signed 500 its typed client verifies, and the error is
  logged by the service

#### Scenario: The failed request is retried exactly

- **WHEN** the caller retries that request with the same request identity and body
- **THEN** it receives the recorded signed 500 without the route running again

## MODIFIED Requirements

### Requirement: A bare-metal publication view is built from its capacity declaration

A capacity declaration's bare-metal publication view SHALL take its Physical
Resource identity, pool, host, physical host identity, capacity, and availability
from that declaration alone, and SHALL NOT read a host inventory record. Its host
identity, physical host identity, access methods, and availability are delivery
terms: the view SHALL carry them only as the declaring pool's backing delegate passes
them, so a capacity-backed pool's view carries all of them and an unbacked pool's view
carries none, and SHALL be built and validated through the bare-metal domain's shared
view carrier with that pool's backing. The view builder SHALL hold no branch on backing
of its own, and the view SHALL carry no backing label.

The view builder SHALL NOT raise on a declaration's content. A declaration whose
publication is enabled but from which no valid view can be built — a capacity-backed
declaration naming no host or no access methods, a missing or invalid allocation mode,
a missing physical host identity, or a capacity or capability key the view may not
publish — SHALL be projected without the view, with a `publication_view_problems`
entry for the view naming why, and every other entry in the generation SHALL be
unaffected. A declaration in an unbacked pool whose publication is enabled SHALL be
projected with the view whether or not it names a host.

#### Scenario: An enabled publication names no host

- **GIVEN** a capacity declaration in a capacity-backed pool with an enabled
  bare-metal publication and no host
- **WHEN** the resource-pool projection is produced
- **THEN** the declaration is projected without the bare-metal view and with a
  `publication_view_problems` entry for it, and every other entry in the generation is
  unaffected

#### Scenario: An enabled publication declares no access methods

- **GIVEN** a capacity declaration in a capacity-backed pool with an enabled
  bare-metal publication that names a host and declares no access methods
- **WHEN** the resource-pool projection is produced
- **THEN** the projection succeeds, the declaration is projected without the bare-metal
  view, and its `publication_view_problems` entry names the missing access methods

#### Scenario: The named host is not registered

- **GIVEN** a capacity declaration in a capacity-backed pool with an enabled
  bare-metal publication naming a host that has no registered record
- **WHEN** the resource-pool projection is produced
- **THEN** the view is produced and carries the declaration's host

#### Scenario: An unbacked declaration names no host

- **GIVEN** a capacity declaration in an unbacked pool with an enabled bare-metal
  publication and no host
- **WHEN** the resource-pool projection is produced
- **THEN** the view is produced carrying the resource's identity, pool, shape,
  capabilities, and region, and no host identity, access methods, or availability

#### Scenario: An unbacked declaration names a host

- **GIVEN** a capacity declaration in an unbacked pool with an enabled bare-metal
  publication naming a host and access methods
- **WHEN** the resource-pool projection is produced
- **THEN** the view carries neither the host identity nor the access methods

### Requirement: Domains contribute their inventory views

A domain view in the site's resource-pool projection, whether attached to a projected
resource or to a pool, MUST be produced by a projection the domain's adapter contributes.
The provisioning service MUST NOT name a domain's view, its source attributes, or its
provider configuration. Each projection MUST declare the view identifiers it produces and
the declaration attributes it consumes, a consumed attribute MUST NOT appear in the neutral
projected attributes, and composition MUST refuse a view identifier or consumed attribute
declared by two projections.

A projection producing a resource view MUST receive the context of the resource's pool —
its provider and its resolved declarations, the backing delegate among them — alongside
the resource's declaration. The provisioning service MUST resolve that context from the
pool records it already reads for the projection, and MUST NOT interpret it. A
contributed projection MUST NOT raise on a declaration's content: it MUST return, beside
the views it built, the problems that kept it from building a view it declares, and the
provisioning service MUST carry them on the projected resource as
`publication_view_problems`, keyed by view identifier.

#### Scenario: A third domain contributes a view

- **WHEN** a domain contributes a projection producing a resource view under its own
  identifier
- **THEN** projected resources carry that view without any change to the provisioning
  service

#### Scenario: Two projections claim one view

- **WHEN** two contributed projections declare the same view identifier
- **THEN** composition refuses to start

#### Scenario: A resource view depends on its pool's backing

- **WHEN** a contributed projection builds a resource view for a resource whose pool
  declares itself unbacked
- **THEN** the projection receives that pool's backing delegate and the provisioning
  service makes no decision on backing itself

#### Scenario: A projection cannot build a view

- **WHEN** a contributed projection cannot build its view from one declaration's content
- **THEN** the resource-pool projection is served, that resource carries the projection's
  problem under `publication_view_problems`, and no other resource is affected
