## MODIFIED Requirements

### Requirement: Multi-domain storefront selection has focused compatibility coverage

Deterministic focused tests MUST cover frozen registry validation, immutable listing/thread binding, publication mode enforcement, domain-envelope matching, selected-site routing, settlement/fulfillment contexts, restart recovery, result decoding, and teardown under both VM and bare-metal contracts. Duplicate, missing, unknown, unsupported, mismatched, and cross-swapped modes/identities/versions MUST fail before an unselected policy, persistence mutation, capacity call, provider call, or decoder runs.

#### Scenario: One and two registrations use the same shell

- **WHEN** focused composition builds the shared shell with one explicit registration and with VM plus bare-metal registrations
- **THEN** both use the same registry, application builder, repository bindings, publication-source construction, and lifecycle carriers, with no default registration and no singleton

#### Scenario: Unknown binding is injected at a lifecycle boundary

- **WHEN** publication, opening, continuation, settlement, fulfillment, result, recovery, or teardown receives an unknown or mismatched binding
- **THEN** the owning boundary rejects it and its mutation/network spies remain untouched

#### Scenario: Installed-artifact deployment is inspected

- **WHEN** clean staged wheels render the combined image, Compose, and Helm configuration
- **THEN** both enabled contributions are discoverable, disabled domains leave no wait/source path, and signer/provider/SSH/private-result canaries are absent from public artifacts

#### Scenario: Full live proof is requested

- **WHEN** evidence is requested that one storefront process completes a VM deal and a bare-metal deal, while each storefront executable mounts its own routes and builds its services for one registration
- **THEN** that evidence is reported as blocked on a storefront process that serves a second registration
- **AND** a second registration held in the registry, deals completed by separate storefront processes, and a faked publication, fulfillment, teardown, or capacity restoration are none of them recorded as that proof
