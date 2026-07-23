## Why

Provisioning and e2e still duplicate profile parsing, include ordering, and Dynaconf construction, but their prefixes, dotenv/secrets behavior, missing-file handling, and fallbacks differ. A parameterized kit/config factory can remove duplicated mechanics only if consumer parity is proven.

## What Changes

- Extract profile parsing, config-directory/include ordering, and parameterized Dynaconf construction into `kit/config`.
- Keep provisioning/e2e validators, wrappers, profile helpers, and provisioning storefront fallback local.
- Preserve each consumer's prefix, nested separator, defaults, dotenv/secrets, missing-file, and merge precedence exactly.
- Add shared loader and consumer parity tests plus wheel dependency/install checks.
- State: **Relevant behavior-preserving refactor; independently implementation-ready.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `deployment-state`: Provisioning and e2e construct layered configuration through one parameterized shared loader without changing observable precedence.

## Non-Goals

- Do not force storefront's profile-free loader into this abstraction.
- Do not standardize consumer-specific prefixes, validators, fallbacks, or secrets behavior.
- Do not change configuration precedence as cleanup.

## Impact

Touches `kit/config`, provisioning service config, e2e settings, package dependencies/wheels, and focused parity tests. Deployment values and runtime behavior should remain unchanged.
