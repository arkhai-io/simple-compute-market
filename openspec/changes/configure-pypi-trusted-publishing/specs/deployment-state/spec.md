## ADDED Requirements

### Requirement: Complete trusted-publishing distribution graph

Release automation MUST maintain a reviewed inventory of every current consumable Arkhai distribution, its source/build path, dependency order, protected GitHub environment, and matching PyPI trusted publisher/project. Excluded demo, test-harness, sample, or internal-tooling projects MUST be classified explicitly rather than omitted accidentally.

#### Scenario: Distribution is added or renamed

- **WHEN** repository metadata introduces or renames a consumable distribution
- **THEN** release inventory, path triggers, environment/project mapping, dependency order, and documentation are updated together before publication

#### Scenario: Distribution is published

- **WHEN** trusted release automation publishes an included distribution
- **THEN** it builds without source overrides and a clean downstream consumer can install the required dependency graph from PyPI without repository or `.dist` access

#### Scenario: External setup is missing

- **WHEN** the workflow names a distribution without a matching current-name protected environment or PyPI trusted publisher/project
- **THEN** release readiness remains blocked and matrix presence is not reported as completed external configuration
