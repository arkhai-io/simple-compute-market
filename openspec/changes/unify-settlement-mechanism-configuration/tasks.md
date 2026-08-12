## 1. Prerequisite contract pins

- [ ] 1.1 Confirm `add-nonchain-marketplace-identities` is implemented, strictly validated, promoted, and archived; pin its identity/config contract and the exact final hosted client release, whose service wheel no longer exposes the seller entry point, before changing settlement configuration.
- [ ] 1.2 Inventory current hosted and Alkahest TOML paths, Dynaconf/environment names, CLI flags/groups, Helm/Compose values, generated examples, status/preflight branches, publication inputs, and run-log config snapshots in `design.md`; map each old key to one new destination or explicit removal.

## 2. Common settlement configuration contract

- [ ] 2.1 Add typed settlement root, canonical priority, mechanism registration, role applicability, common readiness/status, source metadata, and config-schema version models to `kit/settlement-runtime/src/market_settlement_runtime/`; extend the existing mechanism-client registry rather than creating another runtime.
- [ ] 2.2 Extend `kit/config/src/market_config/` with strict nested role resolution and precedence (CLI, environment/Secret, TOML, defaults), whole-list replacement, unknown-key rejection, safe source reporting, and generated-model metadata without importing concrete mechanisms.
- [ ] 2.3 Add common contract tests for duplicate/unknown priority, missing/uninstalled registrations, buyer versus seller field applicability, list precedence, secret redaction, observational status, and no second settlement lifecycle.

## 3. Mechanism-owned settings and preflight

- [ ] 3.1 Add the `[Settlement.alkahest]` schema/registration in `kit/alkahest`, moving only mechanism policy/address-book/oracle fields while consuming separately injected `[Identity]`, `[Wallet]`, and `[Chains]`; implement sanitized wallet/chain/RPC/deployed-contract readiness only when enabled.
- [ ] 3.2 Add the `[Settlement.stripe]` schema/registration in `kit/hosted-settlement`, consuming only public hosted URL/trust/manifest/API/capability/account/currency/condition/timeouts and the injected marketplace signer; reject provider/admin/webhook/database/migration settings.
- [ ] 3.3 Implement common status projections with stable blocker codes and allowlisted details; prove neither mechanism preflight publishes, creates links/Checkout, submits transactions/provider mutations, or changes settlement state.
- [ ] 3.4 Add mechanism tests for valid/invalid roles, fiat-only no-wallet configuration, Alkahest chain requirements, hosted manifest/account/condition blockers, secret/provider-field rejection, sanitized output, and exact client factories.

## 4. Config migration and generated surfaces

- [ ] 4.1 Implement a comment-preserving migration in `kit/config` for top-level `HostedSettlement`, Alkahest flags/address-book fields, existing mechanism preferences, environment-name mapping, and unchanged `[Identity]`/`[Wallet]`/`[Chains]` ownership.
- [ ] 4.2 Register `config migrate --scope settlement --check|--write --backup` in core buyer and VM storefront config groups; redact values, refuse conflicting old/new fields, validate before write, preserve restrictive permissions, fsync, back up, atomically replace, and make rerun a no-op.
- [ ] 4.3 Generate `config init-user` templates, dotted-path metadata, environment/Helm schema fragments, and role reference tables from the typed model; delete hand-maintained duplicates after drift tests prove parity.
- [ ] 4.4 Add migration tests for buyer/seller legacy variants, comments/unrelated sections, conflicting values, malformed secrets, dry-run purity, failure rollback, file/backup permissions, atomic replacement, idempotence, and post-cutover legacy rejection with the exact remediation command.

## 5. Storefront composition, publication, and CLI

- [ ] 5.1 Replace `HostedSettlement` and Alkahest-specific startup branches in `domains/vms/storefront/src/market_storefront/{settings.toml,startup,settlement_composition}.py` with explicit mechanism registrations and one resolved settlement config.
- [ ] 5.2 Refactor `domains/vms/storefront/src/market_storefront/services/listing_service.py` and publication wiring so every enabled registration is preflighted and every ready option is emitted deterministically in priority order; suppress only unready peers and fail when none are ready.
- [ ] 5.3 Add `market-storefront settlement status`, `settlement stripe onboard|status`, and `settlement alkahest check` under `domains/vms/storefront/src/market_storefront/{cli,groups}/`; move Stripe seller workflow through the hosted client with transient URLs and machine-readable sanitized output.
- [ ] 5.4 Remove old top-level hosted flags/commands, marketplace references to the retired hosted seller executable, and old config paths after storefront parity; update marketplace entry points and package-content tests while keeping authority admin commands hosted-service-owned.
- [ ] 5.5 Add storefront tests for hosted-only, Alkahest-only, dual-ready order, each one-unready combination, none-ready failure, readiness recovery reconciliation, command exit codes/JSON, no side effects during status, and unchanged accepted Terms.

## 6. Buyer selection and late prerequisites

- [ ] 6.1 Update `core/buyer` orchestration/config APIs and `domains/vms/buyer/{config_cli,buy_cli,negotiate_cli,settle_cli}.py` to consume canonical priority and installed registrations; remove provider-specific top-level preference/credential flags.
- [ ] 6.2 Resolve `[Wallet]`/`[Chains]` and perform token/gas/RPC checks only after buyer policy selects an EVM option; hosted fiat selection must not construct or inspect chain resources.
- [ ] 6.3 Persist only config schema version, public mechanism set/fingerprint, accepted selection, and stable operation identity in run logs; recovery must use the accepted mechanism regardless of new priority/enablement/readiness.
- [ ] 6.4 Add buyer tests for hosted-first/Alkahest-first policy, incompatible preferred option, fiat-only no-wallet flow, EVM late validation, priority changes during recovery, removed flags, role-appropriate generated config, and no post-acceptance fallback.

## 7. Deployment and package cutover

- [ ] 7.1 Update VM storefront/buyer defaults, profile overlays, Helm values/schema/templates, Compose environment, Secret/ConfigMap placement, examples, and smoke configs to `[Settlement]`, `[Settlement.stripe]`, and `[Settlement.alkahest]` in one coordinated release boundary.
- [ ] 7.2 Update marketplace wheel dependencies/entry points, root review-wheelhouse scope, storefront image, release manifests/provenance, and deployment scripts; retain exact hosted manifest/client pins, verify the hosted wheel has no seller entry point, and ship no editable sibling source.
- [ ] 7.3 Add Helm/Compose/render tests for fiat-only, Alkahest-only, dual, wrong image/config version, missing Secret, old environment names, forbidden provider fields, and generated-schema drift.
- [ ] 7.4 Provide a production migration runbook command sequence in the owning deployment documentation task only after behavior passes: deploy migration tooling, preview/back up/migrate/validate all overlays, quiesce automation, deploy, inspect common status, then resume or restore prior config/artifacts before activation.

## 8. Verification

- [ ] 8.1 Run focused settlement-config, kit config/runtime, Alkahest, hosted adapter, core buyer, VM buyer/storefront, publication, CLI, run-log recovery, migration, package-content, and deployment tests plus affected Ruff/mypy checks.
- [ ] 8.2 Run integration suites for dual-mechanism publication/negotiation, hosted lifecycle, Alkahest lifecycle, restart/recovery, option reconciliation, and unready-mechanism isolation.
- [ ] 8.3 Build/install affected wheels and storefront image from the review wheelhouse; run exact hosted manifest/provenance verification, Helm/Compose smoke, generated-config drift, and `make check`.
- [ ] 8.4 Run cross-repository no-wallet hosted E2E and existing Alkahest E2E from generated/migrated configs; run available real Stripe test-mode evidence and disclose external webhook/EAS/Kubernetes/publisher limits without substitution.
- [ ] 8.5 Run targeted and repository-wide strict OpenSpec validation and report unrelated active-change failures separately.

## 9. Closeout

Per `openspec/README.md` plan-closeout requirements.

- [ ] 9.1 Run `make check-comment-hygiene`; review touched comments/docstrings and remove change/task IDs, migration narrative, tombstones, compatibility aliases, obsolete key/flag names, old hosted seller entry points, and provider/chain assumptions from common code.
- [ ] 9.2 Review imports and built artifacts: common config/runtime contains no concrete mechanism, mechanisms own their schemas/preflight, storefront/buyer compose registrations, hosted service authority remains external, and no provider secret or editable sibling path ships.
- [ ] 9.3 Promote hierarchy, precedence, status, CLI, migration, and recovery behavior/rationale to `openspec/specs/settlement-configuration/{spec,architecture}.md` and add it to `openspec/specs/README.md`.
- [ ] 9.4 Promote deltas to `openspec/specs/{settlement-servicing,storefront-publication,buyer-orchestration,market-composition,deployment-state}/{spec,architecture}.md` and current operator/system context to `docs/development/{ARCHITECTURE,DEPLOYMENT_AND_CONFIG}.md` plus owning role docs.
- [ ] 9.5 Update or explicitly leave `ROADMAP.md` unchanged with rationale, compress completed task notes to final behavior/evidence, and complete the design-promotion record below before archive.

## Design Promotion Record

| Accepted decision | Permanent location |
|---|---|
| One typed root with peer Stripe/Alkahest sections and canonical priority | `openspec/specs/settlement-configuration/{spec,architecture}.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| Identity, wallet, and chains remain shared resources outside mechanisms | `openspec/specs/{settlement-configuration,market-composition}/`; `docs/development/ARCHITECTURE.md` |
| Mechanisms own schemas, preflight, clients, options, compatibility, and unique commands; common code owns registration/status/order only | `openspec/specs/{settlement-configuration,settlement-servicing,market-composition}/` |
| Publication includes every ready mechanism, suppresses only unready peers, and never switches accepted Terms | `openspec/specs/{settlement-configuration,storefront-publication,settlement-servicing}/` |
| Storefront CLI owns seller status and mechanism administration | `openspec/specs/{settlement-configuration,storefront-publication}/`; VM storefront role docs |
| Config migration is explicit, previewable, conflict-rejecting, permission-safe, atomic, idempotent, then clean-cutover | `openspec/specs/{settlement-configuration,deployment-state}/`; `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| Recovery follows accepted plan/operation identity, not current priority or readiness | `openspec/specs/{settlement-configuration,settlement-servicing,buyer-orchestration}/` |
