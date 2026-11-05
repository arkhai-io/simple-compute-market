## ADDED Requirements

### Requirement: Indexed capability documentation

A capability MAY organize its documentation by an index: an `index.md` beside its
`spec.md` that lists each requirement by id, with a link to its heading in `spec.md`
and a summary line, under the parts and groups of its table of contents, and the
ids it retired. In such a
capability every requirement's name MUST begin with its id — the capability's
prefix and four random characters from `[a-z0-9]` — and an id MUST NOT be reused.

#### Scenario: A change adds a requirement to an indexed capability

- **WHEN** a change's delta adds `### Requirement: CW-q4ze Validation describes one commit`
- **THEN** closeout's promotion lists `CW-q4ze` in the capability's `index.md`
  before the archive merges the delta, and the index check accepts it from the
  delta

#### Scenario: A requirement has no id

- **WHEN** an indexed capability's `spec.md` holds a requirement whose name begins
  with no id
- **THEN** `make check-change` fails, naming the requirement

#### Scenario: The index omits an id

- **WHEN** an id in an indexed capability's `spec.md` is not listed in its
  `index.md`, or is listed twice
- **THEN** `make check-change` fails, naming the id

#### Scenario: A retired id is reused

- **WHEN** a requirement takes an id that `index.md` lists as retired
- **THEN** `make check-change` fails, naming the id

#### Scenario: An index entry links to another requirement's heading

- **WHEN** `index.md` lists `CW-a8tf` with a link to the heading of `CW-r3ka`
- **THEN** `make check-change` fails, naming `CW-a8tf` and its own heading

## MODIFIED Requirements

### Requirement: Permanent capability architecture companions
A capability MAY maintain a companion beside its normative `spec.md` for durable current-state conceptual models, ownership rationale, trade-offs, limitations, and relationships that do not fit observable requirement scenarios: `README.md` in a capability organized by an `index.md`, its human-readable description holding its diagrams, and `architecture.md` in any other. Normative behavior MUST remain in `spec.md`; proposed decisions MUST remain in an active change until accepted and implemented. Every companion MUST be linked from the canonical capability index, and every material update MUST be named in the implementing change's promotion tasks and design-promotion record because OpenSpec does not synchronize companion files automatically.

#### Scenario: Accepted rationale does not fit a behavioral requirement
- **WHEN** an implemented design decision explains why a capability boundary or trade-off exists without introducing independently testable behavior
- **THEN** the change promotes it to the owning capability's companion and links that document from the capability index

#### Scenario: Prose contains an observable invariant
- **WHEN** architecture prose states behavior that implementations must satisfy
- **THEN** the owning `spec.md` also expresses that invariant as a normative requirement with a verifiable scenario

#### Scenario: Change is archived
- **WHEN** a completed change contains accepted capability-level design rationale
- **THEN** archive review verifies its explicit permanent architecture destination even though OpenSpec's delta synchronizer does not process the companion file

#### Scenario: An indexed capability's companion
- **WHEN** a capability has an `index.md`
- **THEN** its companion is its `README.md`, and it has no `architecture.md`
