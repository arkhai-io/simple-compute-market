## ADDED Requirements

### Requirement: Artifact-only local hosted composition

The marketplace MUST provide an opt-in local/E2E composition for one hosted migration process, API, reconciliation worker, and durable authority store on the marketplace network. It MUST consume a compatible hosted client wheel, signed release manifest, digest-pinned service or E2E image, and declared control-contract version without building, mounting, importing, or adding an editable path to hosted service source.

#### Scenario: Authorized developer uses a local private image

- **WHEN** a developer supplies a locally built private image plus its matching signed local release inputs
- **THEN** the marketplace verifies those inputs, starts the authority on the local network, and configures storefront consumers with the internal authority address rather than a remote deployment

#### Scenario: Registry and authority use the same container port

- **WHEN** both services listen on port `8080` inside their containers
- **THEN** service-to-service configuration uses distinct Compose names and the authority receives a non-conflicting host port without changing its internal contract

### Requirement: Ready-gated one-writer test topology

Local composition MUST complete exact release verification and migration before authority readiness, MUST preserve the hosted one-writer SQLite topology, MUST wait on the digest/schema/capability-bearing ready response rather than a fixed delay, and MUST preserve named volumes across selected restart scenarios.

#### Scenario: Worker restarts during settlement

- **WHEN** an E2E stage restarts the authority worker after a provider operation is durably submitted
- **THEN** the same database and accepted operation identity remain available and reconciliation resumes without starting a second writer or duplicating the effect

### Requirement: Optional private artifact boundary

Default marketplace initialization, builds, packaging, tests, Alkahest composition, and public contributor workflows MUST NOT require the private hosted image, simulator, sibling checkout, registry token, or Stripe credentials. Private values MUST be supplied only to explicitly selected local targets or protected CI and MUST NOT be copied into marketplace images, logs, reports, run state, committed environment files, or release artifacts.

#### Scenario: Ordinary public build runs without hosted access

- **WHEN** a contributor has no hosted repository checkout and no private registry credentials
- **THEN** the standard marketplace build and non-hosted tests run without resolving or pulling private artifacts

#### Scenario: Private integration workflow assembles both releases

- **WHEN** a protected workflow checks out an exact marketplace commit and supplies a verified private hosted release
- **THEN** it invokes the marketplace-owned hosted E2E target and may report its result against that commit without making the hosted implementation a marketplace source dependency

### Requirement: Production and test controls stay disjoint

Marketplace production configuration and ordinary hosted client code MUST NOT contain simulator control credentials, endpoints, commands, or provider-state models. The E2E harness MUST connect to controls only on an isolated test network and MUST reject a control artifact whose manifest is not explicitly marked E2E-only.

#### Scenario: Production image is supplied to the hermetic target

- **WHEN** a selected hermetic suite receives a hosted manifest without the required E2E simulator capability
- **THEN** preflight fails before publication and does not probe for hidden control routes on the production API
