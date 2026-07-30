## ADDED Requirements

### Requirement: Portable internal wheel resolution

Consumable project metadata and locks MUST NOT resolve internal distributions through parent or sibling source paths. Local initialization and testing MUST build internal distributions and install them from the repository distribution directory with explicit upgrade/reinstall behavior for changed same-version wheels.

#### Scenario: Consumable project is initialized

- **WHEN** a developer initializes or reinitializes a project with internal dependencies
- **THEN** dependency ordering builds required wheels and installation succeeds without editable sibling paths

#### Scenario: Repository packaging check runs

- **WHEN** project and lock metadata are inspected
- **THEN** internal parent-directory path sources fail the check while declared external package-index selectors remain allowed

#### Scenario: Changed internal wheel keeps its version

- **WHEN** a prerequisite package is rebuilt without a version bump during local development
- **THEN** the dependent project's reinit command explicitly upgrades or reinstalls that wheel rather than retaining stale installed code
