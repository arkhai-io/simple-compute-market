## 1. Identity-kit profile model and store

- [x] 1.1 Add strict profile-store, buyer-profile, principal-history, credential-reference, authority-binding, lifecycle, and redacted projection models in new `kit/identity/src/market_identity/profiles.py`; export them from `market_identity/__init__.py` without importing buyer core, domains, hosted settlement, wallets, or deployment code.
- [x] 1.2 Implement the versioned XDG JSON repository in `profiles.py` with global name/active-principal uniqueness, revision checks, same-directory serialization, restrictive owner permissions, full-candidate validation, fsynced atomic replacement, and malformed/unknown/partial-store rejection.
- [x] 1.3 Add random opaque UUID profile ID generation with stable preservation across rename, selection, migration, and restart; add selection, create/import candidate, dual-proof rotation-history, distinct principal/profile retirement, deletion eligibility, authority-binding mutation, and secret/provider-shaped metadata rejection helpers using the existing canonical principal and rotation contracts.
- [x] 1.4 Extend `kit/identity/tests/unit/` with `test_profiles.py` covering fresh store, random opaque/stable profile IDs, duplicate/conflicting profile and principal, invalid history/binding, selection, revision conflict, malformed/unknown store, interrupted write, concurrent serialization, permissions, restart, rotation overlap, principal/profile retirement blockers, one-profile retirement selection clearing, deletion, and redacted models.

## 2. Explicit credential providers

- [x] 2.1 Add the `CredentialProvider` protocol, closed provider registry, normalized errors, and secret-free reference/repr rules in new `kit/identity/src/market_identity/credentials.py`; do not add implicit provider order or a raw-value provider.
- [x] 2.2 Implement `keyring.v1` load/generate/delete through the supported OS keyring adapter, failing before metadata commit when no usable backend exists and never importing/initializing keyring for another selected provider.
- [x] 2.3 Implement `secret_file.v1` descriptor-level no-follow regular-file/current-owner/no-group-or-other-permission checks, exclusive owner-only generation, exact reads, revalidated explicit deletion, and absolute bounded locators.
- [x] 2.4 Implement read-only `environment.v1` resolution from one exact bounded variable name with no fallback, generation, deletion, default variable, or value persistence.
- [x] 2.5 Update `kit/identity/pyproject.toml`, its lockfile and build targets for the approved keyring adapter only if required; extend `kit/identity/tests/unit/test_credentials.py`, `test_signing.py`, and `test_package_boundary.py` for each backend, missing/unavailable/error cases, symlink/owner/mode races, generated-secret cleanup, principal derivation, canaries, and forbidden dependency directions.

## 3. Core profile service and CLI

- [ ] 3.1 Add `core/buyer/src/core_buyer/profile_service.py` to resolve XDG paths, combine the identity-kit repository/providers with run-log retention checks, stage generation/import, derive and compare principals, clean unreferenced generated secrets, and return only bounded remediation context.
- [ ] 3.2 Add a core-owned `market profile` Typer group in `core/buyer/src/core_buyer/cli.py` with create, import, list, show, select, rotate, retire, and delete commands; register it before domain plugins and support consistent safe human/JSON output.
- [ ] 3.3 Implement `profile import --check` and explicit write behavior against legacy buyer `[Identity]` plus one exact provider reference; validate principal equality and all conflicts before any metadata or legacy-file mutation and make exact rerun converge.
- [ ] 3.4 Implement dual-proof rotate, new-run promotion, run/binding blocker display, `retire --principal` for an eligible non-primary predecessor, whole-profile `retire` with atomic selection clearing, metadata deletion, and separately confirmed unshared credential deletion in `profile_service.py` and the core CLI.
- [ ] 3.5 Extend `core/buyer/tests/unit/test_cli.py` and add `test_profile_service.py` for plugin-free commands, create/import/select/show, JSON redaction, mismatch/duplicate/cleanup failures, rotation, predecessor retirement, selected one-profile retirement and later deletion, exact retry, legacy source preservation, and no secret in output, exceptions, or reprs.

## 4. Shared signer resolution and run-log migration

- [ ] 4.1 Replace direct `[Identity]` and `ARKHAI_IDENTITY_CREDENTIAL` resolution in `core/buyer/src/core_buyer/buyer_config.py` with a `BuyerProfileResolver` and `ResolvedBuyerIdentity` for selected-primary fresh runs and exact profile/principal historical recovery; keep optional wallet/chain resolution separate.
- [ ] 4.2 Update `core/buyer/src/core_buyer/{cli.py,orchestration.py,orchestrator.py,plugins.py,settlement.py}` and public exports in `__init__.py` to resolve once per command/run and inject only the signer plus safe immutable profile context through existing schema-opaque hooks.
- [ ] 4.3 Bump `core/buyer/src/core_buyer/run_log.py` to version 3 with stable `buyer_profile_id`, exact canonical principal, and signature version as reserved fields; expand secret isolation and preserve every existing run, negotiation, deal, settlement, operation, and domain identifier.
- [ ] 4.4 Implement one coordinated address-only → canonical-principal → unique-profile version-3 migration in `run_log.py`: stage/validate the complete profile store and every run-log candidate, retain originals behind a durable migration manifest, commit replacements only after all candidates pass, restore all already-replaced artifacts on pre-activation failure/interruption, and reject startup while an incomplete manifest is unresolved.
- [ ] 4.5 Expand `core/buyer/tests/unit/test_identity_recovery.py`, `test_orchestrator.py`, `test_plugins.py`, and `test_cli.py` for selected fresh signer, selection change, retained predecessor resume, missing/retired/mismatched profile, exact principal comparison, v1/v2 populated multi-run migration, stable IDs, ambiguity or failure after an earlier replacement with complete profile/run-log restoration, interrupted-manifest restart/recovery, and no credential/provider value in JSONL.

## 5. VM buyer clean cutover

- [ ] 5.1 Replace direct identity helper imports and repeated signer construction in `domains/vms/buyer/{buy_cli.py,listing_cli.py,negotiate_cli.py,settle_cli.py,escrow_cli.py,service_cli.py,settlement_composition.py,common.py}` with the core fresh/recovery resolver and pass one resolved signer through each command path.
- [ ] 5.2 Update VM `--from` buy/settle/resume paths and `domains/vms/buyer/{run_log.py,deal_helpers.py,buyer_client.py,buy_orchestrator.py}` integration so they load the recorded profile/principal rather than the currently selected profile; do not change separate Alkahest wallet inputs.
- [ ] 5.3 Replace `[Identity]` and raw signer-secret content in `domains/vms/buyer/config_cli.py` templates/migration validation with XDG/profile/provider-reference guidance, explicit profile import, and clean rejection of removed fields and environment aliases.
- [ ] 5.4 Refactor VM buyer fixtures away from monkeypatching domain-local identity functions and extend `domains/vms/buyer/tests/{test_buy_resume_cli.py,test_vm_settlement_helpers.py,test_buy_orchestrator.py,test_buyer_client_resume.py,test_config_migration_cli.py,test_settlement_config_template.py,test_plugin_export.py}` for shared injection, selected fresh run, retained resume, legacy rejection, wallet independence, and secret-free output.

## 6. API-credit buyer and plugin conformance cutover

- [ ] 6.1 Replace identity scheme/identifier flags and direct secret resolution in `domains/apicredits/buyer/{buy_cli.py,listing_cli.py,negotiate_cli.py,settle_cli.py,common.py,cli_helpers.py,buyer_client.py}` with the same core fresh/recovery resolver; leave explicit EVM wallet/private-key inputs only on selected Alkahest effects.
- [ ] 6.2 Update API-credit run creation and resume state so the stable profile ID and exact principal flow through core run-log ownership without entering domain listing, negotiation, issuance, or API-key carriers.
- [ ] 6.3 Extend `domains/apicredits/buyer/tests/{test_negotiation_flow.py,test_settle_credentials.py,test_listing_helpers.py,test_plugin_export.py}` and the shared buyer-domain conformance suite to run VM and API credits against the same profile matrix and reject any plugin-local `[Identity]`, raw secret, or fallback provider path.
- [ ] 6.4 Add a conformance guard for every installed/future buyer plugin requiring core `ResolvedBuyerIdentity` injection and proving fresh-primary, retained-principal resume, missing selection, principal mismatch, and secret-free carriers without importing a concrete domain into core.

## 7. Generated config, deployment, and E2E fixtures

- [ ] 7.1 Update typed buyer configuration metadata and generated reference/template drift checks to use XDG profile-store/provider-reference inputs and reject direct buyer `[Identity]`, raw credential, seed, mnemonic, and implicit wallet-derived marketplace identity fields.
- [ ] 7.2 Update `e2e-tests/config/hosted-buyer.toml`, `e2e-tests/tests/e2e/roles/buyer_cli.py`, hosted boundary/driver setup under `e2e-tests/tests/e2e/roles/scenarios/vms/hosted/` and `e2e-tests/src/hosted_real_stripe/`, plus `compose.vms.yml` and `compose.vms-fiat.yml`, to create/mount one persistent buyer profile store and inject the selected headless provider secret only into the buyer process.
- [ ] 7.3 Update API-credit and VM Compose/examples (`compose.apicredits.yml`, `domains/{vms,apicredits}/compose.yml`) and any generated role fixtures to separate mutable XDG metadata from strict file/environment Secret injection; add Podman-compatible `mise` path only if an affected project hardcodes `docker` and lacks the repository convention.
- [ ] 7.4 Extend `e2e-tests/tests/unit/test_hosted_public_boundary.py`, hosted driver/workflow unit tests, Compose config checks, Helm/generated-config tests, and secret-canary artifact scans for profile-store persistence, owner/mode enforcement, provider exactness, legacy rejection, and absence of secrets in TOML/ConfigMaps/arguments/evidence.

## 8. Focused, integration, and package verification

- [ ] 8.1 Run focused identity-kit profile/provider/signing/package tests; core profile CLI/resolver/run-log/plugin tests; VM and API-credit buyer suites; generated-config, Compose, and hosted driver unit tests. Record exact commands and prove create/import/rotate/restart/recovery and all named failure cases.
- [ ] 8.2 Build the changed identity, core buyer, VM buyer, and API-credit buyer wheels into `.dist`; explicitly upgrade/reinstall them through each touched project's reinit target, inspect wheel contents/dependencies, and run typing plus forbidden-import checks without editable sibling paths.
- [ ] 8.3 Run the ordinary wallet-free Ed25519 VM and API-credit smoke paths with fresh and resumed runs under one persistent profile, then inspect JSONL, TOML, output, reprs, logs, Compose renders, wheels, and images with secret canaries; keep Alkahest wallet regression separate and unchanged.
- [ ] 8.4 Run the relevant integration/E2E suites for VM and API-credit buyer injection and run-log migration; disclose unavailable external hosted/cluster checks rather than replacing them with narrower focused evidence.

## 9. Permanent documentation and cutover

- [ ] 9.1 Promote profile/store/provider/lifecycle/rotation/binding requirements and rationale to `openspec/specs/marketplace-identity/{spec.md,architecture.md}`; promote fresh/recovery/plugin behavior to `openspec/specs/buyer-orchestration/spec.md`.
- [ ] 9.2 Promote XDG/permissions/provider/migration/config rules to `openspec/specs/deployment-state/spec.md` and `docs/development/DEPLOYMENT_AND_CONFIG.md`; promote deterministic matrix and secret-canary boundaries to `openspec/specs/test-compatibility/spec.md` and `docs/development/TESTING.md`.
- [ ] 9.3 Update `docs/development/ARCHITECTURE.md`, `docs/buyer-quickstart.md`, and every affected current-state buyer/config reference with the profile flow, exact commands, headless provider setup, clean legacy import, rotation/retention, and recovery semantics.
- [ ] 9.4 Execute the coordinated preview/import/run-log-v3/config/automation cutover and verify all stores/plugins/deployments before activation; after profile-based effects exist, preserve profile history and recover forward rather than restoring direct identity precedence.

## 10. Plan closeout

- [ ] 10.1 Close out the change: run `make check-comment-hygiene` and directly inspect touched comments/docstrings for current-state wording; move every safe touched function-local import to module scope and verify any retained local import with an observed circular-import or deliberate lazy-load reason; re-check every accepted decision against `openspec/README.md` documentation placement; compress completed task notes to final behavior, material evidence, unresolved work, and permanent destinations after moving retained rationale into `design.md`; update the affected identity/buyer goal and change mapping in `docs/development/ROADMAP.md`; and finalize the `design.md` promotion record with exact permanent headings after removing temporary migration/review commentary from production artifacts.
