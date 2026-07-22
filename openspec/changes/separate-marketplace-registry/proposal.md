## Why

The Helm dependency is conditional and permanent architecture allows an external shared registry, but umbrella defaults still deploy an embedded registry and storefront startup waits for the in-release service even when it is disabled. Provider deployments need one canonical external registry URL, while marketplace-operator and local profiles must opt into an embedded registry explicitly.

## What Changes

- Default provider-oriented umbrella values to `registry.enabled=false`.
- Replace host/port assumptions with one canonical full registry API URL supporting TLS and path prefixes.
- Make storefront configuration, health waits, authentication-key lookup, and publication use the same canonical URL.
- Add explicit marketplace-operator, local development, and e2e values that enable the embedded registry.
- Add render/startup tests for external, embedded, and disabled-role topologies.
- State: **Planned and implementation-ready after rebaseline.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `deployment-state`: Provider seller stacks default to an external registry, while explicit operator/development profiles may deploy the registry role.

## Dependencies and Related Changes

- Precedes `migrate-registry-to-postgres` so the database rollout targets an independently operated registry topology.
- Does not require registry API changes and is independent of filter indexing.

## Non-Goals

- Do not change registry listing/publication APIs.
- Do not provision or migrate the external registry database.
- Do not silently synthesize an internal service URL when the registry role is disabled.

## Impact

Touches umbrella/subchart values and helpers, storefront registry configuration and wait initialization, development/e2e overlays, Secret/value rendering, Helm tests, and operator documentation. Default deployment behavior changes for users relying implicitly on the embedded registry.
