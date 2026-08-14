## REMOVED Requirements

### Requirement: Optional hosted test composition consumes immutable releases

**Reason**: The requirement establishes hermetic, simulator, controlled-clock, and simulator-backed local-EAS deployment profiles. Those test-only provider surfaces are retired; hosted financial system E2E uses Stripe test mode through the ordinary production authority release.

**Migration**: Replace the profile matrix with the production-release-only protected Stripe composition below. Preserve digest-pinned production release verification and authority-volume restart behavior. Run local EAS/arbiter condition conformance independently of hosted finance.

## MODIFIED Requirements

### Requirement: Hosted test secrets remain role-scoped

Stripe provider, webhook, hosted authority, release acquisition, marketplace signer, and browser-test credentials MUST be supplied only to the process that consumes them. Marketplace storefront and buyer configuration MUST contain no hosted provider/admin endpoint or credential, webhook secret, connected-account provider identifier, or raw provider state. Default and fork workflows MUST receive no protected hosted artifact or Stripe credential, and sanitized reports MUST NOT contain credentials, action URLs, customer/card data, raw webhook bodies, or unrestricted provider payloads.

#### Scenario: Public or fork workflow runs

- **WHEN** untrusted contributor code executes
- **THEN** no protected hosted artifact credential, Stripe credential, connected-account identifier, webhook secret, raw event, Checkout action, or secret-bearing report is available

#### Scenario: Stripe CLI forwards webhooks

- **WHEN** an authorized protected run starts Stripe CLI forwarding to the loopback-only hosted webhook mapping
- **THEN** the signing secret is delivered only to the authority webhook process, is never printed or persisted in marketplace state, and is destroyed with the run environment

## ADDED Requirements

### Requirement: Protected hosted test composition uses the production release

Local and protected hosted financial E2E MUST consume one verified signed production hosted release by exact client wheel and service image digest and MUST NOT build, mount, import, or install sibling hosted source. The composition MUST run the ordinary migration, API, and reconciliation worker roles against Stripe test mode and preserve the authority store across selected restart scenarios. It MUST NOT resolve or run an E2E fixture wheel, simulated provider, controlled clock, synthetic event worker, simulator/control image, simulator manifest, simulator store, or simulator credential.

#### Scenario: Protected Stripe composition starts

- **WHEN** an authorized operator supplies a compatible production release, test-mode Stripe credential, verified webhook-forwarding path, and ready connected account
- **THEN** release verification and migration complete before the ordinary authority API and worker become ready, marketplace consumers use the public authority address, and no simulator service or control network exists

#### Scenario: Authority process restarts

- **WHEN** a hosted recovery scenario restarts the ordinary authority API or reconciliation worker without resetting the scenario
- **THEN** the authority store and accepted operation identities remain available and reconciliation resumes against authoritative Stripe test-mode state

#### Scenario: Local EAS conformance runs

- **WHEN** an operator selects local EAS/allowlisted-arbiter condition conformance
- **THEN** the test exercises only the condition boundary and does not start, emulate, or claim hosted financial provider behavior

### Requirement: Stripe test-mode activation fails closed

Protected hosted startup MUST prove that credentials and returned provider objects are non-live, the connected account is the expected allowlisted test fixture and has required readiness/capabilities, webhook forwarding reaches the exact loopback authority endpoint, and the selected hosted release reports its exact expected manifest/API/capabilities. A mismatch or unavailable prerequisite MUST stop before Checkout, transfer, refund, publication side effects, or marketplace acceptance according to the stage's mutation boundary.

#### Scenario: Live credential is supplied

- **WHEN** protected hosted E2E receives a live-mode Stripe credential or observes a live provider object
- **THEN** preflight fails before creating any payment, transfer, refund, or marketplace settlement mutation and redacts the credential

#### Scenario: Connected account is unready

- **WHEN** the selected test connected account lacks an expected ownership binding, charge/transfer capability, or payout readiness required by the scenario
- **THEN** preflight reports a test-account readiness failure before publication of a Stripe option or payment creation

### Requirement: Simulator deployment surfaces are absent

Active marketplace Compose, Make, workflow, packaging, configuration, release-verification, schema, and documentation surfaces MUST contain no hosted simulator fixture distribution, image, manifest, protocol, control endpoint, controlled-clock store, simulator state volume, synthetic provider event worker, or hermetic hosted target. Historical archived change artifacts MAY retain provenance but MUST NOT be executable or referenced by current production/test entry points.

#### Scenario: Deployment surfaces are inspected

- **WHEN** active hosted test and packaging surfaces are scanned after cutover
- **THEN** only the ordinary hosted production release and protected Stripe test prerequisites remain and no simulator artifact can be selected or started
