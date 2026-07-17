## ADDED Requirements

### Requirement: Installable compute provisioner

The extracted compute-provisioning distribution MUST install outside the repository layout with all declared runtime dependencies and MUST expose supported commands for its API and worker roles.

#### Scenario: Wheel is installed from built artifacts

- **WHEN** an operator installs the compute provisioner and selected adapter extras from built wheels without editable parent-directory sources
- **THEN** API and worker commands resolve their dependencies and start using the supplied configuration

### Requirement: Extracted service image

The repository MUST provide one destination compute-provisioning image whose startup, routes, background lifecycle, persistence, and shutdown behavior match the migrated service.

#### Scenario: Destination image starts

- **WHEN** the image starts with VM and bare-metal adapters and an existing compatible database
- **THEN** migrations initialize once, readiness becomes healthy, configured background tasks run, and graceful shutdown cancels them without corrupting job or lease state

### Requirement: Coordinated deployment cutover

Deployment manifests and operator configuration MUST reference the destination package, commands, and image, and MUST NOT retain the old VM-owned generic service after cutover.

#### Scenario: Repository deployment references are checked

- **WHEN** package, image, command, and manifest references are scanned after migration
- **THEN** all active deployments use the compute-owned service and no runtime path depends on the repository's parent-directory layout
