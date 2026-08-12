## Context

See `proposal.md` for motivation. The settlement runtime and hosted adapter already share one mechanism-neutral lifecycle. Configuration does not reflect that architecture: Alkahest settings are distributed across wallet, chains, oracle flags, address books, buyer CLI parameters, and storefront defaults, while hosted settlement is a top-level `HostedSettlement` feature with separate seller onboarding commands. VM listing composition contains both branches directly, and operator status cannot answer the same questions for each mechanism.

The preceding identity change separates `[Identity]` from optional chain credentials and publishes an exact hosted-client identity pin. This change consumes those contracts; it must not reintroduce private-key fields into settlement models or put hosted authority/provider behavior in marketplace code.

## Goals / Non-Goals

**Goals:**

- Present Alkahest and hosted Stripe as peer mechanisms under one typed namespace and one seller CLI.
- Give every mechanism the same enablement, readiness, capability, publication, selection, and diagnostics contract.
- Keep shared identity, wallet, and chains outside mechanism-owned policy.
- Derive publication and buyer selection deterministically from one validated configuration.
- Migrate old configuration explicitly and atomically, then remove old paths and commands.
- Preserve the single settlement runtime and all existing financial/chain behavior.

**Non-Goals:**

- Merge Alkahest and hosted adapters, credentials, authorities, status vocabularies, or provider behavior.
- Put Stripe secrets, provider IDs, webhooks, EAS/RPC service configuration, or hosted database state in marketplace config.
- Require a wallet or chain for hosted non-EVM settlement.
- Add hosted settlement to API credits or bare metal.
- Add automatic mechanism fallback after accepted Terms or after any financial/chain operation starts.
- Keep legacy config keys, environment names, flags, or the hosted seller executable as aliases.

## Decisions

### One namespace, stable mechanism keys, explicit priority

The public TOML shape is:

```toml
[Identity]
scheme = "ed25519"
identifier = "<base64url-public-key>"
credential_env = "MARKET_IDENTITY_PRIVATE_KEY"

[Settlement]
priority = ["fiat.stripe.v1", "alkahest.v1"]

[Settlement.stripe]
enabled = true
base_url = "https://settlement.example"
authority = { scheme = "ed25519", identifier = "<authority-public-key>" }
expected_manifest_digest = "sha256:<digest>"
expected_api_version = "2"
required_capabilities = ["conditional-escrow", "account-identities", "ed25519"]
account_ref = "seller-main"
currency = "usd"
condition_profile = "vm-fulfillment"
request_timeout_seconds = 10.0
preflight_timeout_seconds = 5.0

[Settlement.alkahest]
enabled = false
address_config_path = "/etc/arkhai/alkahest.json"
oracle_gated = false
trusted_oracle_addresses = []

[Wallet]
address = ""
private_key = ""

[Chains.ethereum_sepolia]
rpc_url = "https://..."
chain_id = 11155111
```

`stripe` and `alkahest` are configuration keys registered by their mechanism packages and map exactly to `fiat.stripe.v1` and `alkahest.v1`. `[Settlement].priority` contains canonical mechanism IDs, rejects duplicates and unknown IDs, and defines deterministic publication and buyer preference order. New defaults enable no mechanism and use an empty priority; `config init-user` requires an explicit operator choice, while migration preserves the currently effective mechanisms and order. A mechanism section owns only policy and public client/trust inputs for that mechanism. `[Identity]` is role authentication. `[Wallet]` and `[Chains]` remain shared resources because multiple EVM mechanisms/conditions may consume them.

Role-specific validation allows seller-only fields such as `account_ref` to be absent from buyer config. A buyer declares allowed/priority mechanisms without receiving seller authority configuration. Unknown keys are errors, not ignored future compatibility.

A quoted TOML table keyed directly by `"fiat.stripe.v1"` was rejected because it is hostile to CLI dotted-path editing and environment overlays. A generic list of untyped mechanism dictionaries was rejected because it moves validation to runtime and makes templates/docs drift.

### Mechanism packages register typed configuration and preflight

The settlement foundation defines a small registration record: canonical mechanism ID, config key/schema, role applicability, client factory, readiness/preflight function, listing-option builder, buyer compatibility hook, and optional CLI group factory. Composition roots explicitly register installed mechanisms. Core orchestration sees only the shared registration and status result; mechanism packages own their settings and diagnostics.

This extends the existing mechanism-client registry rather than creating another lifecycle. There remains one `SettlementRuntime`, obligation journal, retry model, and accepted-selection rule.

### Readiness is common; checks remain mechanism-owned

Every preflight yields:

- `mechanism`, `configured`, `enabled`, and `ready`;
- stable sanitized blocker codes and messages;
- declared capabilities and contract/schema versions;
- optional safe public details needed by an operator or listing builder.

Alkahest checks wallet/chain availability, RPC chain identity, address-book/deployed contracts, selected asset, and oracle policy only when enabled. Hosted checks signed manifest/API/capability pins, authority trust, account readiness, currency, condition profile, and client compatibility without exposing raw URLs, provider IDs, credentials, or administrator state. Common code never interprets provider- or chain-specific detail.

Status is observational and must not create Account Links, publish listings, submit transactions, create Checkout sessions, or mutate settlement state.

### Publication includes every ready mechanism and never falls back after acceptance

`market-storefront publish` preflights enabled registrations, logs one sanitized result per mechanism, and builds options from every ready mechanism in priority order. If one enabled mechanism is unready and another is ready, the unready mechanism is suppressed and publication continues. If none are ready, publication fails. Reconciliation removes only options no longer supported while preserving listing identity and exact accepted Terms.

Buyer selection filters advertised options by enabled mechanisms, uses `[Settlement].priority` as a policy input, and then pins one exact option in Terms. There is no automatic switch to a different mechanism after acceptance or when settlement fails.

### One storefront CLI owns seller settlement administration

The seller surface is:

```text
market-storefront settlement status [--json]
market-storefront settlement stripe onboard [--no-browser]
market-storefront settlement stripe status [--json]
market-storefront settlement alkahest check [--json]
market-storefront publish
```

`settlement status` is the common summary. Mechanism subgroups may expose genuinely different operations; symmetry does not mean inventing an Alkahest onboarding flow or hiding Stripe Account Links. Stripe onboarding calls the provider-neutral workflow shipped in the hosted client, uses the configured marketplace identity signer, and never persists a returned URL. Authority-only commands remain in the hosted service.

The standalone `hosted-settlement-seller` entry point is deleted after the storefront command reaches parity. Buyer commands retain domain-owned `buy`/`negotiate` UX; their settlement preference and prerequisites come from the shared model rather than new top-level provider commands.

### Configuration precedence and secrets are uniform

Resolution order is CLI override, environment/Secret overlay, role/user TOML, then committed defaults. A higher-layer list replaces the lower list. Only declared fields may be overridden. Status reports each non-secret field's source when requested but never its secret value.

`credential_env` names the secret source for `[Identity]`; it is not the credential. Wallet private keys and any mechanism request secret remain in the role secrets file or environment/Secret overlay, never ordinary committed TOML or ConfigMaps. Hosted provider/admin/webhook secrets never enter this repository's consumer schema.

The typed model is the source for `config init-user`, examples, CLI dotted-path validation, Helm schemas, and reference tables. Hand-maintained duplicate templates are removed.

### Migration is explicit, previewable, and clean-cutover

Each role exposes:

```text
<role> config migrate --scope settlement --check
<role> config migrate --scope settlement --write --backup
```

The migration maps top-level `HostedSettlement` fields to `[Settlement.stripe]`, moves mechanism-owned Alkahest flags/address-book settings under `[Settlement.alkahest]`, derives canonical priority from existing preference/enablement, and leaves `[Identity]`, `[Wallet]`, and `[Chains]` in place. It preserves unrelated sections and comments where the TOML editor can do so, validates the fully resolved result, reports secret moves without printing values, refuses conflicting old/new values, writes a same-directory temporary file, fsyncs, backs up with restrictive permissions, and atomically replaces the source.

`--check` never writes. A repeated migration is a no-op. Startup and `config set` reject legacy paths after cutover with the exact migration command; runtime does not silently merge old and new values. Environment, Helm, and Compose keys have one coordinated release boundary and no fallback aliases.

### Persistence and recovery retain mechanism identity

No financial database ownership or settlement state schema changes. Existing plans already carry canonical mechanism IDs. Run logs and configuration fingerprints update only their configuration-schema version and public resolved mechanism set; recovery uses the accepted plan's pinned mechanism and operation identities, not current priority. A config change cannot reinterpret an in-flight settlement or make it fall back.

## Risks / Trade-offs

- **[Peer presentation hides genuine mechanism differences]** → Common status/enablement/selection is shared; mechanism subcommands and typed details remain owned by each adapter.
- **[Suppressing one unready mechanism masks an outage]** → Publication logs/status expose a stable blocker and readiness is nonzero when explicitly checking that mechanism; ready peers remain usable by design.
- **[Config migration can expose or lose secrets]** → Preview redacts values, conflict aborts, backup/write permissions are restrictive, and replacement is atomic; provider secrets are not accepted inputs.
- **[Priority is mistaken for financial failover]** → It orders advertised/acceptable choices only. Accepted Terms pin one option permanently.
- **[Generic mechanism registry becomes a plugin framework]** → Registrations are explicit at composition roots and extend the existing client registry; no dynamic untrusted discovery or second engine.
- **[Old operational automation breaks]** → The change is intentionally breaking, supplies deterministic migration and machine-readable status, and coordinates config/command removal in one release.

## Migration Plan

1. Complete and pin `add-nonchain-marketplace-identities` and its hosted release dependency.
2. Add typed settlement root/registration/status contracts and mechanism-owned Alkahest/Stripe config models.
3. Implement role-specific resolution, schema generation, source reporting, and secret/public validation.
4. Add preview/write config migration and prove idempotence, conflict rollback, permissions, and legacy rejection.
5. Compose mechanism registrations into VM storefront and buyer; derive publication and selection from readiness/priority.
6. Add the storefront CLI hierarchy and move Stripe seller workflow behind it; remove the standalone entry point and old flags/keys/environment names.
7. Update Helm, Compose, images, examples, generated templates/reference docs, and release/review packaging.
8. Verify fiat-only, Alkahest-only, dual-mechanism, one-unready, no-ready, restart/recovery, and exact-artifact deployments.
9. Deploy migration tooling first, preview and back up production configs, quiesce publication/config automation, migrate files/Secrets/overlays, deploy the clean-cutover release, verify status, then resume.
10. Roll back before new configuration is activated by restoring backups and the prior release together. After new publication or settlement starts, correct configuration and roll forward; never reinterpret accepted in-flight plans.

## Permanent Documentation Promotion

- New hierarchy, precedence, status, CLI, and migration: `openspec/specs/settlement-configuration/{spec,architecture}.md` and `openspec/specs/README.md`.
- Lifecycle/config registry boundary: `openspec/specs/settlement-servicing/{spec,architecture}.md`.
- Publication readiness and CLI ownership: `openspec/specs/storefront-publication/{spec,architecture}.md`.
- Buyer selection and late chain prerequisites: `openspec/specs/buyer-orchestration/{spec,architecture}.md`.
- Role/mechanism composition: `openspec/specs/market-composition/{spec,architecture}.md` and `docs/development/ARCHITECTURE.md`.
- Overlay, Secret, Helm/Compose, migration, and rollback rules: `openspec/specs/deployment-state/{spec,architecture}.md` and `docs/development/DEPLOYMENT_AND_CONFIG.md`.
