## ADDED Requirements

### Requirement: Evidence labels match the exercised boundary
Every capacity result MUST use the exact orthogonal fields
`execution_boundary` (`readiness`, `mock`, `real-reference`,
`real-qualification`, or `real-measured`) and `actor_trigger` (`none`,
`controller-driven`, or `agent-triggered`) whose acceptance boundaries were
actually exercised. Process readiness before controller-owned emission MUST
NOT be agent-triggered; mock provisioning MUST NOT be labeled real system
capacity; and a deterministic reference lifecycle MUST NOT be counted as
agent-capacity evidence. Qualification and measured boundaries MUST be
reserved for their respective admitted real paths.

#### Scenario: Readiness-before-emission is labeled accurately
- **WHEN** role processes exit after preparing or approving requests and a controller emits those requests later
- **THEN** the result records the real boundary actually exercised with `actor_trigger=controller-driven`, while the earlier preparation receipt remains `execution_boundary=readiness`

#### Scenario: Mock path stays preparatory
- **WHEN** buyer and seller agents complete their role path against mock provisioning
- **THEN** the result is `execution_boundary=mock` and `actor_trigger=agent-triggered` and cannot satisfy real KVM/GPU qualification or capacity measurement

#### Scenario: Deterministic reference remains a control
- **WHEN** a deterministic driver completes the real B1 VM lifecycle before agent-driven qualification
- **THEN** the result is `execution_boundary=real-reference` and `actor_trigger=controller-driven` and is excluded from agent-capacity frontiers

#### Scenario: Real evidence keeps qualification and measurement distinct
- **WHEN** a real qualification row or an admitted measured row completes
- **THEN** the result uses `real-qualification` or `real-measured` with `actor_trigger=agent-triggered` and cannot be relabeled across the pre-Q0 boundary

### Requirement: Capacity contracts preserve a portable executor seam
Local Codex execution and a future cloud or Tekton executor MUST consume the
same repository-relative public commands, pinned scenario/profile inputs, and
portable result schemas. The public contract MUST NOT depend on an
executor-local path, credential source, cloud project, process supervisor, or
Tekton object. Private infrastructure MUST own executor selection, credentials,
cancellation, watchdogs, native evidence, and teardown while producing the same
portable artifacts.

#### Scenario: Local and cloud executors validate the same artifact
- **WHEN** a local Codex runner and a future cloud or Tekton runner present the same pinned public scenario, profile-stage, role/action receipts, and result
- **THEN** the public commands calculate the same identities and validation outcome

#### Scenario: Executor detail enters a portable artifact
- **WHEN** a public capacity artifact contains a local path, credential location, cloud project, Tekton task name, or private host identity
- **THEN** validation rejects it instead of coupling the contract to that executor
