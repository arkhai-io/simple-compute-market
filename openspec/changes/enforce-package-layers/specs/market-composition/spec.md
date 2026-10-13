## MODIFIED Requirements

### Requirement: From-below kit dependencies
Every package MUST depend only on packages in its own layer or a lower one, without a cycle inside a layer, and only on packages whose scope is a subset of its own. Layer, kind, and scope MUST be read from the package's path and name, never inferred from its imports. Any import and any declared internal distribution is a dependency. One repository-wide check MUST hold these rules over every project, and every divergence it reports MUST be an owned exception that expires with its cause.

#### Scenario: Architecture boundary tests run
- **WHEN** the repository architecture check runs over every project outside the tooling paths
- **THEN** every project is classified by layer, kind, and scope, and every dependency a rule forbids is reported unless an owned exception row excuses it

#### Scenario: A lower layer depends on a higher one
- **WHEN** a kit or specialization imports a composition, at module level, inside a function, under `TYPE_CHECKING`, or behind `try`
- **THEN** the architecture check fails and names the importing file and line and the imported distribution

#### Scenario: Packages in one layer import each other
- **WHEN** two packages in the same layer depend on each other directly or through others in that layer
- **THEN** the architecture check fails and names the cycle

#### Scenario: A package knows a scope it is not placed in
- **WHEN** a package depends on one whose scope is not a subset of its own, such as a domain composition declaring a sibling domain's contribution without importing it
- **THEN** the architecture check fails and names the dependency and the scope elements it adds

#### Scenario: A package imports an internal distribution it does not declare
- **WHEN** a project's source imports a repository distribution its `pyproject.toml` does not declare
- **THEN** the architecture check fails and names the importing file and line

#### Scenario: A package imports a plugin
- **WHEN** any package imports a package that registers into a plugin entry-point group
- **THEN** the architecture check fails, while a declaration that installs the plugin passes

#### Scenario: A light kind outgrows its budget
- **WHEN** a contracts or client package depends on a distribution outside its kind's budget
- **THEN** the architecture check fails and names the dependency

#### Scenario: An exception outlives its cause
- **WHEN** an exception row's edge is gone, or the edge no longer breaks the rule the row names
- **THEN** the architecture check fails and names the row and its owning change

#### Scenario: An override outlives its cause
- **WHEN** an override row's project now classifies the same from its path alone, or the row grants a scope element none of the project's dependencies uses
- **THEN** the architecture check fails and names the row
