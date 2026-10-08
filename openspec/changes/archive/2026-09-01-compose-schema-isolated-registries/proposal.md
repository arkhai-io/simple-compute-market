## Why

The repository ships compute and API-credit filter specifications, but its Helm
umbrella can instantiate only one registry. A hosted marketplace needs both
schema authorities without sharing identity, state, or public coordinates.

## What Changes

- Add an optional API-credits registry dependency beside the existing compute
  registry.
- Give each registry its own identity, descriptor, authentication, Service,
  persistence, and filter-spec selection values.
- Package both repository-owned filter specifications in the registry image.
- Prove the compute-only default and the collision-free two-registry render.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `deployment-state`: one Helm release may compose independent registry roles
  for different schema identities.

## Non-Goals

- Publish an image or deploy a registry.
- Configure DNS, TLS, gateways, or external secret stores.
- Combine the registries' authority, database, or API-key state.

## Impact

Touches the umbrella dependency graph and values schema, the registry image,
Helm render checks, and permanent deployment documentation.
