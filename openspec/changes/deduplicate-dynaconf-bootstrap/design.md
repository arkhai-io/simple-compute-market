## Context

Provisioning and e2e loaders duplicate mechanics but differ in prefixes, dotenv options, `.secrets.toml`, include behavior, and profile helpers. `kit/config` has no Dynaconf dependency or shared factory today.

The current provisioning loader no longer contains the storefront fallback named in the
original change text. A repository-wide closeout scan found that the API-credit service
still has its own profile-based Dynaconf loader and storefront-admin-key fallback. That
consumer is outside this change: this refactor preserves current compute-provisioning and
e2e behavior rather than recreating historical provisioning behavior or claiming
repository-wide adoption of the shared bootstrap.

## Goals / Non-Goals

**Goals:** parameterized shared mechanics with byte-for-behavior consumer parity and correct wheel dependencies.

**Non-Goals:** one universal configuration policy, inclusion of the storefront loader, or migration of the API-credit service loader and its storefront-admin-key fallback.

## Decisions

- Add a small immutable loader-options contract for the default config directory,
  ordered settings files, base/profile include naming, prefix, nested separator,
  dotenv options, missing-include behavior, and merge/environment flags. Environment
  lookup for `CONFIG_DIRECTORY` and `ACTIVE_PROFILES` remains explicit input to the
  shared builder rather than hidden process-global behavior in kit.
- Shared code parses the comma-separated profile list, constructs the ordered include
  paths, optionally filters missing includes, and constructs Dynaconf. Consumer modules
  retain exported settings objects, validators, typed wrappers, profile/config-directory
  helpers, and any role-specific fallback or validation policy.
- Preserve the consumers' currently different file semantics exactly:
  - provisioning settings files: packaged `settings.toml`; includes: existing
    `config.yml` followed by existing `config-<profile>.yml` files; the current constructor passes `dotenv_files=[".env", ".env.local"]` with dotenv loading enabled; prefix `PROVISIONING`; missing includes are filtered;
  - e2e settings files: project `settings.toml` followed by `.secrets.toml`; includes:
    `config.yml` followed by every requested `config-<profile>.yml` path in order;
    dotenv loading remains rooted at the e2e project `.env`; prefix `ARKHAI`; missing
    include paths are still passed to Dynaconf.
- Preserve the exact Dynaconf constructor keyword used by each consumer for nested
  environment keys rather than normalizing that keyword during a behavior-preserving
  refactor. The shared options expose the nested separator and the compatible keyword
  spelling so parity does not depend on an undocumented alias behaving identically
  across the two locked Dynaconf versions.
- Capture current consumer behavior in characterization tests before extraction and run old/new parity fixtures during cutover.
- Add Dynaconf as an explicit `arkhai-kit-config` dependency and verify both consumers from built wheels.

## Current behavior audit

| Concern | Compute provisioning | E2E tests |
|---|---|---|
| Default config root | package-local `config/` | project-local `config/` |
| Config root override | `CONFIG_DIRECTORY` | `CONFIG_DIRECTORY` |
| Profile selector | comma-separated `ACTIVE_PROFILES`, trimmed, empties removed | same |
| Settings files | package `settings.toml` | project `settings.toml`, then `.secrets.toml` |
| Includes | `config.yml`, then profiles | `config.yml`, then profiles |
| Missing includes | filtered before Dynaconf construction | passed through to Dynaconf |
| Environment prefix | `PROVISIONING` | `ARKHAI` |
| Nested separator | `__` via current provisioning constructor keyword | `__` via current e2e constructor keyword |
| Dotenv | enabled; current constructor passes `.env`, `.env.local` via `dotenv_files` | enabled; project `.env` via `dotenv_path` |
| Dynaconf environments | disabled | disabled |
| Global merge | enabled | enabled |
| Consumer-owned behavior | typed path/policy wrapper | validators and profile/config-directory accessors |

## Alternatives considered

- **One universal loader policy.** Rejected because it would silently standardize
  secrets, dotenv, and missing-file behavior that this change explicitly promises to
  preserve.
- **Pass an arbitrary `dict[str, Any]` of Dynaconf kwargs through kit.** Rejected as the
  primary API because it would remove duplication without creating a meaningful shared
  contract. A narrow compatibility field for the nested-separator keyword is acceptable
  because the two consumers are currently locked to different Dynaconf versions.
- **Move consumer helpers and validators into kit.** Rejected because those are role
  policy, not shared bootstrap mechanics, and would invert the intended dependency
  boundary.

## Risks / Trade-offs

- **[Abstraction erases meaningful differences]** → Parameterize only shared mechanics and reject options that cannot express current behavior.
- **[Merge precedence changes subtly]** → Compare nested values and source order across profile/env/secrets/include fixtures.
- **[Dependency inversion]** → Kit remains lower-level and imports no provisioning/e2e modules.

## Permanent Documentation Promotion

Shared construction and preserved precedence belong in `deployment-state` spec/architecture; consumer-specific operational profile documentation remains with each role.

## Implementation validation

Final verification used the repository's configured build and consumer install flows,
superseding the earlier sandbox-only compatibility harness. The built wheel contains
`market_config/dynaconf_bootstrap.py`, declares `dynaconf>=3.0.0`, and both migrated
consumers install `arkhai-kit-config==0.1.2` from their wheelhouse-backed reinit flows.

| Evidence | Result |
|---|---|
| Repository distribution build | `make dist` passed; `arkhai_kit_config-0.1.2-py3-none-any.whl` built successfully |
| Config wheel inspection | shared bootstrap module present; `Requires-Dist: dynaconf>=3.0.0` |
| `kit/config` repository-standard unit suite | 134 passed; 1 unrelated pytest configuration warning |
| Compute provisioning wheel reinstall | reinit passed and installed `arkhai-kit-config==0.1.2` with the Dynaconf dependency |
| Compute provisioning unit suite | 632 passed under `ACTIVE_PROFILES=mock`; 1 unrelated deprecation warning |
| Compute provisioning integration suite | 215 passed under `ACTIVE_PROFILES=mock`; 6 unrelated deprecation warnings |
| E2E wheel reinstall | reinit passed and installed `arkhai-kit-config==0.1.2` with the Dynaconf dependency |
| E2E focused settings characterization | 2 passed under the local profile |
| E2E unit suite | 236 passed under the local profile; 1 unrelated existing warning |
| Lock verification | `uv lock --check` passed in kit/config (51 packages), provisioning (95), and e2e (167) |
| Duplicate bootstrap scan | no consumer-owned profile splitting or direct `Dynaconf(...)` construction remains in the two migrated loaders; the API-credit service remains explicitly out of scope |
| Strict validation for this change | `npx @fission-ai/openspec@latest validate deduplicate-dynaconf-bootstrap --strict` passed |
| Repository-wide strict OpenSpec baseline | 76 passed, 11 failed in other active changes; no failure targets this change, so those baseline failures are deferred |
| Closeout hygiene | `make check-comment-hygiene` and `git diff --check` passed; the working tree contained only the 19 expected change files |

The full deployment/system e2e suite was not run. This behavior-preserving refactor's
planned executable evidence is the real built wheel, consumer reinstallation, complete
kit/config and e2e unit suites, and compute-provisioning unit plus locally available
profile-based integration suite. Earlier sandbox failures to obtain Hatchling, Python
3.12, consumer dependencies, and the OpenSpec CLI were environment limitations only
and are superseded by the successful maintainer-side verification above.

## Roadmap disposition

This refactor does not close or alter a directional roadmap gap. It consolidates
an existing deployment-state implementation boundary, so
`docs/development/ROADMAP.md` requires no current-state or change-mapping edit.

## Design promotion record

| Accepted decision | Classification | Permanent location |
|---|---|---|
| Shared config code owns ordered profile parsing, include resolution, and Dynaconf construction from explicit inputs | Permanent | `openspec/specs/deployment-state/spec.md#requirement-shared-dynaconf-bootstrap-preserves-consumer-policy`; `openspec/specs/deployment-state/architecture.md#configuration-bootstrap-boundary` |
| Composition roots own `CONFIG_DIRECTORY` / `ACTIVE_PROFILES` lookup and consumer-specific settings, secrets, dotenv, prefixes, wrappers, validators, and missing-file policy | Permanent | `openspec/specs/deployment-state/spec.md#requirement-shared-dynaconf-bootstrap-preserves-consumer-policy`; `openspec/specs/deployment-state/architecture.md#configuration-bootstrap-boundary` |
| Provisioning filters missing includes while e2e preserves requested missing paths | Permanent | `openspec/specs/deployment-state/spec.md#requirement-shared-dynaconf-bootstrap-preserves-consumer-policy` |
| Preserve each consumer's literal nested-separator constructor keyword during this behavior-preserving extraction | Temporary compatibility detail | Remains in this design and code options; any normalization requires a separately specified behavior change |
| The proposal's historical provisioning storefront fallback must be recreated | Superseded | Not promoted; current provisioning behavior contains no such fallback |
| All profile-based Dynaconf consumers are migrated by this change | Rejected scope expansion | Not promoted; the permanent contract is scoped to compute provisioning and e2e, while the API-credit service remains separate |
| One universal loader policy or moving role validators/wrappers into kit | Rejected | Rationale retained in `## Alternatives considered` only |
