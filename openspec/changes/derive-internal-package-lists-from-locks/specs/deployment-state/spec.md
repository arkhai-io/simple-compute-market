## ADDED Requirements

### Requirement: The internal packages a project refreshes are derived from its lock

The internal packages a project refreshes when it syncs MUST be derived from its
`uv.lock` rather than listed by hand: exactly the packages the lock resolves from a
local wheel registry. A project's `reinit` target MUST upgrade and reinstall each of
them, and a Docker build stage that installs from `.dist` MUST refresh each of them,
both through the same derivation.

#### Scenario: A new internal dependency is refreshed without editing any list

- **GIVEN** a project whose lock gains an internal package resolved from `.dist`
- **WHEN** its `reinit` target runs, or its image is built
- **THEN** the new package is upgraded and reinstalled, or refreshed, with no edit to
  the project's Makefile or Dockerfile

#### Scenario: A hand-written list is refused

- **GIVEN** a project whose lock installs internal wheels
- **WHEN** its `reinit` target, or a Dockerfile of its that copies `.dist`, names
  packages instead of deriving them
- **THEN** `make check-reinit` fails and names the project
