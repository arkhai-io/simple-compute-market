## ADDED Requirements

### Requirement: MCW-t4fx A commit's suite evidence is the affected suites; validation stays full

This repository's hook run before each commit that changes a path outside the inert
paths MUST run `make check-packaging` and then `make test-affected`, never the full
`make test`. Validation's local part MUST keep `make dist-clean`, the full wheelhouse
build, and `make test`, and CI's test matrix MUST keep running every target `make
test` is made of.

#### Scenario: A section changes one kit

- **WHEN** an implementation session commits a change to `kit/site/src/`
- **THEN** the hook runs `kit/site`'s suite and its dependents' suites, not every
  suite

#### Scenario: The round is validated

- **WHEN** validation's local part runs on the round's commit
- **THEN** it rebuilds the wheelhouse from clean and runs the full `make test`
