## ADDED Requirements

### Requirement: Conditional independently installable e2e harness

An independently released e2e harness MUST NOT be activated until a named external consumer, supported deployment/version profile, and release owner exist. Once activated, it MUST install and run its supported black-box suites outside the monorepo using published clients/contracts and explicitly declared test-control capabilities rather than service implementation imports or checkout-relative artifacts.

#### Scenario: Activation evidence is absent

- **WHEN** no named external operator or supported compatibility profile exists
- **THEN** extraction remains deferred and no implementation checklist is presented as ready

#### Scenario: External installation is verified

- **WHEN** an activated harness is installed in a clean environment without repository checkout or `.dist`
- **THEN** supported suites discover configuration through the declared profile and import no private service implementation modules or package-private generated data

#### Scenario: Root CI migrates to released harness

- **WHEN** the versioned package/image proves parity with current in-repository coverage
- **THEN** root CI and Helm consume that artifact before checkout-relative harness paths are removed
