## ADDED Requirements

### Requirement: Wheel-owned domain code
Every shipped Python module MUST be owned by exactly one distribution whose
project directory contains it. A distribution MUST NOT assemble a package
namespace from files belonging to another project directory, and a role MUST
NOT obtain domain code by source-tree copy or interpreter path configuration
in place of a declared dependency.

#### Scenario: A domain package is inspected for ownership
- **WHEN** a Python package under a domain tree is checked against the
  repository's project definitions
- **THEN** exactly one `pyproject.toml` owns it, and no project's build
  configuration enumerates files outside its own directory

#### Scenario: A role image is built
- **WHEN** a role image is built without copying an unowned source tree and
  without adding the repository root to the interpreter path
- **THEN** the role starts and resolves every domain module it uses from
  installed distributions

#### Scenario: A shipped module imports a sibling the wheel omits
- **WHEN** a distribution is built and its shipped modules' first-party
  imports are resolved against its own contents
- **THEN** every such import resolves inside the distribution

### Requirement: Fatal domain plugin load failure
A role MUST fail when a discovered domain plugin cannot be loaded, reporting
the domain identity and the underlying cause. A role MUST NOT report a
loadable-plugin absence in place of a load failure, and MUST NOT continue with
a partial plugin set.

#### Scenario: An installed domain plugin cannot be imported
- **WHEN** a role starts with a domain plugin whose distribution is installed
  but incomplete
- **THEN** startup fails naming that domain and the import that failed, rather
  than reporting that no domain is installed

## MODIFIED Requirements

### Requirement: Explicit optional domain capabilities
A domain MUST declare optional capabilities and supply the typed hook set
required by each declaration; absence of a capability MUST be valid and MUST
NOT require placeholder or no-op implementations. A domain declares the
negotiation capability only to offer policies addressable by name from
operator configuration; a domain that composes its negotiation middlewares
directly MUST NOT be required to declare it.

#### Scenario: API-credit domain has no compute provisioner
- **WHEN** the API-credit domain is composed without a compute-provisioning
  capability
- **THEN** buyer and storefront roles remain usable and expose no
  compute-provisioning hooks for that domain

#### Scenario: Declared capability is incomplete
- **WHEN** a domain declares a capability but omits a required hook
- **THEN** contract validation fails before the role serves requests, naming
  the domain identity and the missing hook

#### Scenario: A domain composes its negotiation chain directly
- **WHEN** a domain assembles its negotiation middlewares as values and
  exposes no policy names to configuration
- **THEN** it declares no negotiation capability and the role composes
  successfully with that domain installed
