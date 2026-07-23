## 1. Characterize current behavior

- [ ] 1.1 Inventory provisioning/e2e roots, profiles, include order, prefixes, separators, dotenv/secrets, missing files, merge flags, validators, helpers, and fallbacks.
- [ ] 1.2 Add characterization fixtures for default/multiple profiles, nested merge, environment overrides, secrets, missing includes, and consumer fallbacks.

## 2. Extract shared construction

- [ ] 2.1 Add immutable loader options and profile/include resolution to `kit/config` without consumer imports.
- [ ] 2.2 Add explicit Dynaconf package dependency, shared unit tests, and built-wheel installation evidence.
- [ ] 2.3 Migrate provisioning wrapper while retaining validators/storefront fallback and prove fixture parity.
- [ ] 2.4 Migrate e2e wrapper while retaining profile helpers/secrets behavior and prove fixture parity.

## 3. Verify and promote

- [ ] 3.1 Run kit/config, provisioning config/startup, e2e config/unit, packaging, lock, and profile-based integration checks.
- [ ] 3.2 Promote shared/preserved behavior to `deployment-state` spec/architecture and keep consumer operation details in role docs.
- [ ] 3.3 Record promotion in `design.md`, scan for obsolete duplicate constructors, and run strict validation before archive.
