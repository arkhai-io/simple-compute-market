## MODIFIED Requirements

### Requirement: Compute mock executors share one compute-family mechanism

Under the provisioning mock profile, each compute provisioning adapter MUST register a
mock executor for its own actions built on one rule and gate mechanism owned by compute
provisioning beside the job lifecycle: rule matching, pause gates, a deterministic
signal when a job reaches a gate, the evaluate-job dry run, and a
framework-free test route service. A mock executor MUST be assembled from shared
execution mechanics and the adapter's contributed default output; no adapter's mock MAY
derive from another adapter's. The mechanism MUST NOT be presented as a foundation kit,
and a non-compute domain's executor mock MUST NOT be added to it. Each adapter MUST
mount its rule and evaluate-job routes under its own prefix, contributing their route
contracts from the family's template instantiated with its mount; job draining and
waiting MUST stay shared.
The test route service MUST answer with response models the compute family's contracts
distribution owns, so every adapter's rule routes answer the same typed shapes.

#### Scenario: A bare-metal grant runs under the mock profile

- **WHEN** a bare-metal grant job runs with the mock profile active
- **THEN** the bare-metal mock returns output bare metal's codec reads as a grant, unless
  a bare-metal rule shapes, pauses, or fails it

#### Scenario: A test waits for a held job

- **WHEN** a test needs a job held at a rule's gate
- **THEN** it waits on the gate-reached signal, not on elapsed time

#### Scenario: A VM rule is installed

- **WHEN** a scenario installs a VM mock rule
- **THEN** it matches VM jobs only and never a bare-metal job

#### Scenario: Two adapters' rule routes answer one shape

- **WHEN** a scenario lists the rules installed through VM's and through bare metal's rule
  routes
- **THEN** both answers are the family's typed rule models
