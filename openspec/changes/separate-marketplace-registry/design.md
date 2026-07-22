## Context

`helm/Chart.yaml` already conditions the registry dependency on `registry.enabled`, but umbrella values default it on. Storefront helpers and wait initialization construct the in-release service URL even when disabled, so an apparently valid provider render cannot start. Permanent deployment architecture already treats registry, seller, and buyer roles as independently operable.

## Goals / Non-Goals

**Goals:** external-registry provider default; explicit embedded profiles; one canonical URL; topology render/startup evidence.

**Non-Goals:** registry API/database changes or external infrastructure provisioning.

## Decisions

### Use one canonical API URL

`global.registry.apiUrl` (or one equivalently named value selected during implementation) is the authority for storefront runtime config, wait/health probing, auth-key lookup, and user-facing output. It supports scheme, authority, and path prefix. Legacy host/port values receive a bounded compatibility migration or are removed with a documented values break.

### Make embedded registry explicit

Base/provider values disable the subchart. Marketplace operator, local Compose/Helm, and e2e profiles explicitly enable it and set the canonical URL to its service. A disabled role emits no registry Deployment/PVC/Service/migration job and no dependent wait targets that service.

### Validate topology structurally and behaviorally

Render tests cover provider external URL, embedded operator, and disabled role. Focused startup/config tests prove every consumer resolves the same normalized URL and authentication mapping.

## Risks / Trade-offs

- **[Existing installs lose an implicit registry]** → Document the values change and provide an explicit embedded compatibility profile.
- **[URL normalization changes auth-key lookup]** → Centralize normalization and test TLS/path-prefix/trailing-slash forms.
- **[Dev/e2e forget opt-in]** → Make overlays explicit and validate them in CI.

## Migration Plan

1. Introduce canonical URL with compatibility diagnostics.
2. Update all consumers and waits.
3. Add explicit embedded overlays and render tests.
4. Flip base default off and remove obsolete synthesis after the compatibility window.

Rollback re-enables the embedded profile and old value mapping while no registry API or state changes are involved.

## Permanent Documentation Promotion

Topology/default behavior belongs in `openspec/specs/deployment-state/spec.md` and `architecture.md`; repository role maps belong in `docs/development/ARCHITECTURE.md`; operator values belong in role-facing deployment documentation.
