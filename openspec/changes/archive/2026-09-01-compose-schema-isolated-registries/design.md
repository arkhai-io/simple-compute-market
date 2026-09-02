## Context

The registry executable is schema-opaque and selects one filter specification
at startup. Helm currently exposes one registry dependency and the subchart
validates its signer against a single umbrella-global identity. The image also
contains only the compute filter specification. Those assumptions prevent two
schema-isolated registries from sharing one release even though their runtime
processes are otherwise independent.

## Goals / Non-Goals

**Goals:** collision-free two-registry composition; independent public and
secret references; explicit filter-spec selection; unchanged compute-only
default.

**Non-Goals:** multi-schema behavior inside one registry process, cross-schema
queries, image publication, or infrastructure rollout.

## Decisions

### Alias the existing registry dependency

The umbrella chart composes the same registry subchart twice. `registry`
remains the enabled compute instance. `api-credits-registry` is a disabled-by-
default dependency alias. Helm's alias participates in generated resource
names, so enabling it creates distinct Deployments, Services, and PVCs without
copying templates.

### Keep identity instance-local

Each registry uses its own `identity` values as its active signer and Secret
reference. The umbrella's existing `global.registryIdentity` remains the
compute storefront trust input, but it is not an authority for every registry
subchart instance. This removes accidental coupling between independent
registry roles.

### Select one packaged filter specification per process

The registry image contains the compute and API-credit specifications at stable
paths. Each subchart instance sets `REGISTRY_FILTER_SPEC_PATH` from its values.
The default path selects compute; the alias selects API credits. A registry
still loads exactly one specification and remains schema-opaque.

### Prove rendered identities and coordinates

Structural tests render the default chart and a two-registry fixture. They
assert that the default contains only the compute registry, while the dual
render contains both schema paths and distinct workload, Service, PVC, signer
Secret, and descriptor coordinates.

## Risks / Trade-offs

- **A configured path is absent from an older image.** Deployments must pin an
  image built from a revision containing the selected specification.
- **Umbrella consumers may mistake the global compute trust pin for a second
  registry's identity.** The alias has a complete independent identity block,
  and documentation names the global value as compute-facing compatibility.
- **Two SQLite registries increase stateful workload count.** Each instance has
  its own PVC and remains constrained to one replica with `Recreate` strategy.

## Migration Plan

Existing values render the same single compute registry. Operators opt into the
API-credits registry and provide its identity, descriptor, auth, persistence,
and image values. Rollback disables the alias; its retained PVC is not deleted.

## Permanent Documentation Promotion

The normative topology belongs in `openspec/specs/deployment-state`; rationale
belongs in its architecture page. Operator-facing value behavior belongs in
`docs/development/DEPLOYMENT_AND_CONFIG.md`, and the role map belongs in
`docs/development/ARCHITECTURE.md`.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| One release may compose schema-isolated registry aliases | `openspec/specs/deployment-state/spec.md#requirement-schema-isolated-registry-composition` |
| Registry signer and filter selection are instance-local | `openspec/specs/deployment-state/architecture.md#role-separated-topology` |
| Compute and API-credit image paths and values behavior | `docs/development/DEPLOYMENT_AND_CONFIG.md#registry-descriptor-configuration` |
| Registry aliases retain independent Kubernetes coordinates | `docs/development/ARCHITECTURE.md#production-and-staging` |

This change does not alter a product roadmap goal. It makes an already-defined
role topology deployable, so `docs/development/ROADMAP.md` needs no update.
