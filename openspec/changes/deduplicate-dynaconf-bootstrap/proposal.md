## Why

Provisioning and e2e still duplicate profile parsing, include ordering, and Dynaconf construction, but their prefixes, dotenv/secrets behavior, missing-file handling, and fallbacks differ. A parameterized kit/config factory can remove duplicated mechanics only if the documented behavior of each consumer remains independently characterized.

## What Changes

- Extract profile parsing, config-directory/include ordering, and parameterized Dynaconf construction into `kit/config`.
- Keep provisioning/e2e validators, wrappers, profile helpers, and other consumer-specific policy local.
- Preserve each consumer's effective prefix, nested separator, defaults, dotenv/secrets, missing-file, and merge precedence. Remove the unsupported/inert provisioning `dotenv_files` constructor argument without adding `.env.local` behavior.
- Add shared-loader tests plus consumer behavior characterization at the real composition seam, along with wheel dependency/install checks.
- State: **Relevant behavior-preserving refactor; independently implementation-ready.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `deployment-state`: Provisioning and e2e construct layered configuration through one parameterized shared loader without changing observable precedence.

## Non-Goals

- Do not force storefront's profile-free loader into this abstraction.
- Do not migrate the API-credit service's separate profile loader or its storefront-admin-key fallback in this change.
- Do not standardize consumer-specific prefixes, validators, fallbacks, or secrets behavior.
- Do not change configuration precedence as cleanup.

## Impact

Touches `kit/config`, provisioning service config, e2e settings, package dependencies/wheels, focused behavior-characterization tests, and the permanent configuration-resolution guide. Deployment values and runtime behavior should remain unchanged.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] `docs/development/DEPLOYMENT_AND_CONFIG.md`
- [x] Existing subsystem specification
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- `openspec/specs/deployment-state/spec.md`: provisioning and e2e use the shared profile/Dynaconf bootstrap while preserving their existing source order, prefixes, secrets/dotenv behavior, and missing-file semantics.
- `openspec/specs/deployment-state/architecture.md`: shared configuration mechanics are a foundation capability; consumer policy remains at the composition root.
- `docs/development/DEPLOYMENT_AND_CONFIG.md`: configuration-resolution conventions distinguish shared `arkhai-kit-config` mechanics from composition-root ownership of `CONFIG_DIRECTORY`, `ACTIVE_PROFILES`, settings/secrets/dotenv, prefixes, and missing-file policy.
