## ADDED Requirements

### Requirement: The harness runtime is domain-agnostic
The harness's generic runtime MUST treat a domain payload as opaque, carrying it
without interpreting its fields. The runtime MUST NOT import a concrete domain
module, branch on a domain identity, or hold a lookup keyed by one. Supporting a
new domain MUST require an adapter, an oracle, redaction and cleanup rules, and
focused tests, and MUST NOT require an edit to the generic runtime.

#### Scenario: An adapter the runtime has never seen is introduced
- **WHEN** an arbitrarily-named adapter carrying an opaque namespaced payload is
  configured
- **THEN** its payload round-trips unchanged and no edit to the generic runtime
  is required

#### Scenario: The generic runtime is inspected
- **WHEN** the generic runtime's imports and reachable code paths are examined
- **THEN** no concrete domain module is imported and no domain identity appears
  in a branch, lookup, or emitted message

#### Scenario: An adapter declares an unsupported contract version or capability
- **WHEN** an adapter declares a contract version the runtime does not support,
  or a capability it does not know
- **THEN** it fails, naming what was declared and what is supported

### Requirement: Prepared domains validate without executing
A domain the harness has prepared for but does not support MUST validate and
dry-plan without executing. Attempting to execute one MUST produce no effect:
no process started, no file written, no connection opened, and no state changed.
A prepared domain that corresponds to a real product domain MUST use that
domain's own declared identity and capabilities rather than a substitute.

#### Scenario: A prepared domain fixture is validated
- **WHEN** a fixture for a prepared but unsupported domain is validated
- **THEN** it validates and dry-plans, and no adapter is required for it to do so

#### Scenario: Execution of a prepared domain is attempted
- **WHEN** execution of a prepared domain fixture is attempted
- **THEN** no process is started, no file written, no connection opened, and no
  state changed — the absence of effect being the assertion, not the presence of
  an error

#### Scenario: A prepared domain corresponds to a real product domain
- **WHEN** a fixture is prepared for a domain the product implements
- **THEN** it carries that domain's declared identity and capabilities, so that
  a change to them is visible as a fixture failure

#### Scenario: A fixture is prepared for a domain the product does not implement
- **WHEN** such a fixture is declared
- **THEN** it may carry only an identity, a namespace, and an opaque payload,
  and a declaration carrying capabilities, roles, expected outcomes, or oracles
  is refused

### Requirement: Incompatible product change fails explicitly
Where a product target, capability, or identity a fixture depends on is removed,
renamed, or changed incompatibly, the harness MUST fail naming the target, the
domain, and the fixture that referenced it. It MUST NOT degrade to a partial
result, a generic resolution error, or a silent skip.

#### Scenario: A product target a fixture depends on is renamed
- **WHEN** a fixture references a product target that no longer exists under
  that name
- **THEN** the harness fails naming the target, the domain, and the referencing
  fixture

#### Scenario: A declared capability disappears from a product domain
- **WHEN** a prepared domain's declared capabilities no longer include one its
  fixture depends on
- **THEN** the fixture fails rather than validating against the reduced set
