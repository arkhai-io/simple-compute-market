## Context

Provisioning and e2e loaders duplicate mechanics but differ in prefixes, dotenv options, `.secrets.toml`, include behavior, and profile helpers. `kit/config` has no Dynaconf dependency or shared factory today.

The current provisioning loader no longer contains the storefront fallback named in the
original change text. A repository-wide closeout scan found that the API-credit service
still has its own profile-based Dynaconf loader and storefront-admin-key fallback. That
consumer is outside this change: this refactor preserves current compute-provisioning and
e2e behavior rather than recreating historical provisioning behavior or claiming
repository-wide adoption of the shared bootstrap.

## Goals / Non-Goals

**Goals:** parameterized shared mechanics with independently characterized consumer behavior and correct wheel dependencies.

**Non-Goals:** one universal configuration policy, inclusion of the storefront loader, or migration of the API-credit service loader and its storefront-admin-key fallback.

## Decisions

- Add a small immutable loader-options contract for the default config directory,
  ordered settings files, base/profile include naming, prefix, nested separator,
  supported dotenv path/loading options, missing-include behavior, and merge/environment flags. Environment
  lookup for `CONFIG_DIRECTORY` and `ACTIVE_PROFILES` remains explicit input to the
  shared builder rather than hidden process-global behavior in kit.
- Shared code parses the comma-separated profile list, constructs the ordered include
  paths, optionally filters missing includes, and constructs Dynaconf. Consumer modules
  retain exported settings objects, validators, typed wrappers, profile/config-directory
  helpers, and any role-specific fallback or validation policy.
- Preserve the consumers' currently different file semantics exactly:
  - provisioning settings files: packaged `settings.toml`; includes: existing
    `config.yml` followed by existing `config-<profile>.yml` files; Dynaconf dotenv
    loading remains enabled with its normal `.env` discovery; prefix `PROVISIONING`;
    missing includes are filtered. The previously copied `dotenv_files=[".env",
    ".env.local"]` constructor argument is unsupported by the locked Dynaconf line and
    therefore was inert; remove it rather than introducing new `.env.local` behavior;
  - e2e settings files: project `settings.toml` followed by `.secrets.toml`; includes:
    `config.yml` followed by every requested `config-<profile>.yml` path in order;
    dotenv loading remains rooted at the e2e project `.env`; prefix `ARKHAI`; missing
    include paths are still passed to Dynaconf. Dynaconf loads that dotenv file into
    the process environment without overwriting already-exported values, so dotenv-
    sourced `ARKHAI_*` values participate at the environment layer above file layers.
- Preserve the exact Dynaconf constructor keyword used by each consumer for nested
  environment keys rather than normalizing that keyword during a behavior-preserving
  refactor. The shared options expose the nested separator and the compatible keyword
  spelling so parity does not depend on an undocumented alias behaving identically
  across the two locked Dynaconf versions.
- Characterize each migrated consumer through a small composition-root bootstrap seam that accepts an environment mapping and delegates to the shared loader. Module import still supplies `os.environ`, but tests exercise the real `CONFIG_DIRECTORY` / `ACTIVE_PROFILES` plumbing rather than reconstructing the lower-level call.
- Treat documented effective behavior as the durable oracle: assert adjacent-layer source ordering, ordered-profile precedence, missing-include policy, dotenv/secrets behavior, environment override behavior, and consumer wrappers/helpers. If executable characterization contradicts existing resolution documentation, stop for design review rather than choosing behavior or prose implicitly. Do not retain a duplicate pre-extraction constructor solely to create an old/new parity test.
- Keep the top-level `market_config` bootstrap API narrow: export `DynaconfBootstrapOptions`, `DynaconfBootstrapResult`, and `load_dynaconf`; leave profile/config/include helpers importable only from `market_config.dynaconf_bootstrap` unless a real cross-package consumer emerges.
- Add Dynaconf as an explicit `arkhai-kit-config` dependency and verify both consumers from built wheels.
- Use existing configured static typing where applicable. E2e has a mypy development dependency/configuration and will type-check the touched settings module; kit/config and compute provisioning have no configured mypy target/dependency, so that absence is disclosed rather than introducing a new toolchain in this refactor.

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
| Dotenv | enabled; normal Dynaconf `.env` discovery. The copied `dotenv_files=(".env", ".env.local")` argument is unsupported/inert and is removed; no `.env.local` support is added | enabled; project `.env` via `dotenv_path`; dotenv values populate missing process environment keys and therefore have environment-layer precedence over settings/includes |
| Dynaconf environments | disabled | disabled |
| Global merge | enabled | enabled |
| Consumer-owned behavior | typed path/policy wrapper | validators and profile/config-directory accessors |

## Review follow-up design amendment: dotenv semantics

Executable/source review during task 5.2 invalidated one planned premise without changing
the shared-loader architecture. The locked Dynaconf behavior treats dotenv as an input to
the environment loader, not as a file layer beneath profile includes. Existing process
environment values are not overwritten by dotenv loading. Provisioning also carried a
`dotenv_files=(".env", ".env.local")` constructor option that the locked Dynaconf version
does not implement. That option never established `.env.local` behavior.

The accepted disposition is behavior preservation rather than feature expansion:

- e2e documentation and tests describe project `.env` values as environment-layer values;
  an already-exported `ARKHAI_*` variable wins over the same dotenv key, and either wins
  over settings/secrets/include files;
- provisioning keeps supported `load_dotenv=True` behavior and normal `.env` discovery,
  removes the unsupported shared/provisioning `dotenv_files` option, and does not add
  `.env.local` support;
- file-layer precedence remains characterized independently from dotenv/environment
  precedence so an environment value cannot mask errors in settings/secrets/base/profile
  ordering.

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

Shared construction and preserved precedence belong in `deployment-state` spec/architecture. Repository configuration-resolution conventions also belong in `docs/development/DEPLOYMENT_AND_CONFIG.md`: shared `arkhai-kit-config` mechanics are distinct from composition-root ownership of resolver environment variables and consumer-specific settings/secrets/dotenv, prefixes, and missing-file policy. Consumer-specific operational profile details remain with each role.

The provisioning integration suite contains pre-existing raw happy-path HTTP helpers in some areas where canonical typed clients exist. That debt is outside this configuration refactor: the suite remains useful broad regression evidence, but its pass count is not described as comprehensive typed-client contract proof.

## Validation evidence before review follow-up

The first closeout verification used the repository's configured build and consumer install flows, superseding the earlier sandbox-only compatibility harness. The built wheel contains `market_config/dynaconf_bootstrap.py`, declares `dynaconf>=3.0.0`, and both migrated consumers install `arkhai-kit-config==0.1.2` from their wheelhouse-backed reinit flows. This evidence remains valid regression history, but the follow-up plan below strengthens the consumer-seam and precedence characterization before final closeout.

| Evidence | Result |
|---|---|
| Repository distribution build | `make dist` passed; `arkhai_kit_config-0.1.2-py3-none-any.whl` built successfully |
| Config wheel inspection | shared bootstrap module present; `Requires-Dist: dynaconf>=3.0.0` |
| `kit/config` repository-standard unit suite | 134 passed; 1 unrelated pytest configuration warning |
| Compute provisioning wheel reinstall | reinit passed and installed `arkhai-kit-config==0.1.2` with the Dynaconf dependency |
| Compute provisioning unit suite | 632 passed under `ACTIVE_PROFILES=mock`; 1 unrelated deprecation warning |
| Compute provisioning integration suite | 215 passed under `ACTIVE_PROFILES=mock`; 6 unrelated deprecation warnings |
| E2E wheel reinstall | reinit passed and installed `arkhai-kit-config==0.1.2` with the Dynaconf dependency |
| E2E focused settings characterization | 2 passed under the local profile; these post-extraction tests exercised the shared loader with e2e options but did not independently prove the composition-root environment plumbing |
| E2E unit suite | 236 passed under the local profile; 1 unrelated existing warning |
| Lock verification | `uv lock --check` passed in kit/config (51 packages), provisioning (95), and e2e (167) |
| Duplicate bootstrap scan | no consumer-owned profile splitting or direct `Dynaconf(...)` construction remains in the two migrated loaders; the API-credit service remains explicitly out of scope |
| Strict validation for this change | `npx @fission-ai/openspec@latest validate deduplicate-dynaconf-bootstrap --strict` passed |
| Repository-wide strict OpenSpec baseline | 76 passed, 11 failed in other active changes; no failure targets this change, so those baseline failures are deferred |
| Closeout hygiene | `make check-comment-hygiene` and `git diff --check` passed; the working tree contained only the 19 expected change files |

The full deployment/system e2e suite was not run. This behavior-preserving refactor does not require a live multi-service environment: the final planned evidence is the real built wheel, consumer reinstallation, complete kit/config and e2e unit suites, compute-provisioning unit plus locally available profile-based integration coverage, strengthened composition-root characterization, and applicable configured static typing. Earlier sandbox failures to obtain Hatchling, Python 3.12, consumer dependencies, and the OpenSpec CLI were environment limitations only and are superseded by the maintainer-side verification above.

## Roadmap disposition

This refactor does not close or alter a directional roadmap gap. It consolidates
an existing deployment-state implementation boundary, so
`docs/development/ROADMAP.md` requires no current-state or change-mapping edit.

## Design promotion record

| Accepted decision | Classification | Permanent location |
|---|---|---|
| Shared config code owns ordered profile parsing, include resolution, and Dynaconf construction from explicit inputs | Permanent | `openspec/specs/deployment-state/spec.md#requirement-shared-dynaconf-bootstrap-preserves-consumer-policy`; `openspec/specs/deployment-state/architecture.md#configuration-bootstrap-boundary`; `docs/development/DEPLOYMENT_AND_CONFIG.md` configuration-resolution conventions |
| Composition roots own `CONFIG_DIRECTORY` / `ACTIVE_PROFILES` lookup and consumer-specific settings, secrets, dotenv, prefixes, wrappers, validators, and missing-file policy | Permanent | `openspec/specs/deployment-state/spec.md#requirement-shared-dynaconf-bootstrap-preserves-consumer-policy`; `openspec/specs/deployment-state/architecture.md#configuration-bootstrap-boundary`; `docs/development/DEPLOYMENT_AND_CONFIG.md` configuration-resolution conventions |
| Provisioning filters missing includes while e2e preserves requested missing paths | Permanent | `openspec/specs/deployment-state/spec.md#requirement-shared-dynaconf-bootstrap-preserves-consumer-policy` |
| Dotenv behavior follows supported Dynaconf semantics: e2e project `.env` populates missing environment-layer values; provisioning uses normal `.env` discovery and does not gain `.env.local` support | Permanent | `docs/development/DEPLOYMENT_AND_CONFIG.md`; `openspec/specs/deployment-state/spec.md#requirement-shared-dynaconf-bootstrap-preserves-consumer-policy`; `openspec/specs/deployment-state/architecture.md#configuration-bootstrap-boundary` |
| Preserve each consumer's literal nested-separator constructor keyword during this behavior-preserving extraction | Temporary compatibility detail | Remains in this design and code options; any normalization requires a separately specified behavior change |
| Consumer characterization uses documented behavior at the real composition seam rather than retaining a duplicate old constructor as a parity oracle | Validation/design decision | Retained in this design; no new permanent testing convention is needed beyond `docs/development/TESTING.md#boundary-change-validation` |
| Only the options/result/loader bootstrap contract is exported from top-level `market_config`; resolution helpers remain submodule details | Package API decision | Retained in this design and package exports; no repository-wide architecture change |
| Pre-existing raw happy-path HTTP helpers in provisioning integration tests are repaired as part of this refactor | Rejected scope expansion | Not promoted; track separately if the integration-test debt is prioritized |
| The proposal's historical provisioning storefront fallback must be recreated | Superseded | Not promoted; current provisioning behavior contains no such fallback |
| All profile-based Dynaconf consumers are migrated by this change | Rejected scope expansion | Not promoted; the permanent contract is scoped to compute provisioning and e2e, while the API-credit service remains separate |
| One universal loader policy or moving role validators/wrappers into kit | Rejected | Rationale retained in `## Alternatives considered` only |
