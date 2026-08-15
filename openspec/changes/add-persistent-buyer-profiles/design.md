## Context

See `proposal.md` for motivation and the delta specs for normative behavior.

`kit/identity` already owns canonical principals, scheme-neutral signers, Ed25519/EIP-191 implementations, authenticated envelopes, and dual-proof rotation intents. `core/buyer` currently resolves a public `[Identity]` principal and one environment credential directly, then injects a signer. VM and API-credit plugins still participate in bootstrap/configuration. Buyer run-log version 2 records the canonical public principal and migrates older address-only events transactionally, but has no stable local profile identity or credential-history resolver.

The profile layer must remain below market domains and above raw credential backends. It cannot make `kit/identity` depend on buyer core, hosted settlement, a domain, a wallet, or deployment code. The separately released hosted client may later associate one opaque payer binding, but provider concepts remain outside this change.

## Goals / Non-Goals

**Goals:**

- Establish one durable local buyer identity aggregate and one signer-resolution path used by every current and future buyer plugin.
- Separate versioned public metadata from private credential storage while making backend choice explicit and deterministic.
- Make fresh-run and exact-principal recovery behavior survive profile selection changes and key rotation.
- Provide a failure-atomic import/cutover from direct identity configuration without a long-lived compatibility precedence layer.
- Leave a provider-neutral slot for authority/environment-scoped hosted payer bindings without introducing Stripe vocabulary.

**Non-Goals:**

- Making local profiles remotely synchronized, multi-user, server-hosted, or recoverable without retained credentials.
- Building a password manager or copying keyring/file/environment secrets between providers automatically.
- Coordinating hosted payer ownership in this change; the profile model only stores and protects an opaque binding and its public principal relationship.
- Changing service-role identity configuration, wallet/chain effects, or marketplace proof version 2.

## Decisions

### 1. Identity kit owns models, storage, and credential-provider protocols

Add profile primitives under `kit/identity/src/market_identity/`:

- `BuyerProfile`, `ProfilePrincipal`, `CredentialReference`, `AuthorityPayerBinding`, lifecycle enums, and store envelope models;
- a `CredentialProvider` protocol with exact `load`, optional `store_generated`, and explicit `delete_unreferenced` operations;
- a provider registry keyed by a closed provider kind;
- a versioned profile-store repository with atomic compare-and-replace;
- profile validation, principal derivation, dual-proof rotation helpers, and redacted projections.

`core/buyer` owns the CLI/service that combines these primitives with XDG paths, run-log retention checks, plugin injection, and configuration migration. The identity kit does not scan run logs or import buyer core.

**Alternative considered:** implement profiles only in `core/buyer`. Rejected because credential references, principal history, and rotation are identity capability concepts needed consistently by future buyer compositions and profile-aware hosted integration.

### 2. The store is one strict versioned JSON document under XDG data

Use one metadata document at a stable path below `$XDG_DATA_HOME/arkhai/buyer/` (falling back to the platform XDG default), with an adjacent lock and atomic temporary file. The envelope contains:

```text
schema_version
revision
selected_profile_id | null
profiles[]
  profile_id (random opaque UUID)
  name
  state
  primary_principal
  principal_history[]
    principal
    credential_reference
    state
    overlap/retirement metadata
  authority_payer_bindings[]
    authority_id + environment
    opaque payer binding
    bound principal
    safe lifecycle metadata
```

Strict decoding rejects unknown fields, versions, duplicates, invalid canonical principals, multiple primaries, dangling selection, and one active principal assigned to multiple profiles. Writes acquire the same-directory exclusive lock, read and validate the current revision, validate the full candidate, write/fdatasync a restrictive temporary file, atomically replace the destination, and fsync the directory. Readers never accept the temporary file as state.

The file and containing private directory are owner-controlled. Metadata is not secret, but restrictive permissions prevent local tampering with credential locators, selected identity, or hosted bindings.

**Alternative considered:** one file per profile. Rejected because selection, global principal uniqueness, rotation, and multi-profile conflict checks would require a cross-file transaction and make interrupted writes harder to classify.

**Alternative considered:** SQLite. Rejected because the small local metadata set needs no query engine, and a strict replaceable document keeps backup, inspection, and atomic migration simple without adding another database lifecycle.

### 3. Credential references are closed tagged values with no fallback

Use three provider kinds:

| Kind | Locator | Read | Generate/store | Delete |
|---|---|---|---|---|
| `keyring.v1` | service + entry | OS keyring | supported | explicit entry delete |
| `secret_file.v1` | absolute path | regular file, current UID, no symlink, no group/other bits | exclusive create with owner-only mode | explicit unlink after revalidation |
| `environment.v1` | bounded variable name | exact process environment value | unsupported | unsupported |

The provider registry resolves exactly the tagged provider. It never tries another backend. `CredentialReference` contains no secret and has a redacted display representation. Backend exceptions are normalized before they cross the provider boundary.

The keyring adapter uses the platform keyring integration and fails clearly when no usable backend exists. Headless packages need not initialize keyring unless the profile selects it. Environment references are intended for orchestrated injection and are never persisted with the value. File reads use descriptor-level no-follow/ownership/type/mode checks to avoid check-then-open symlink substitution.

**Alternative considered:** precedence `keyring → file → env`. Rejected because it can silently use the wrong credential after deployment or rotation and makes recovery nondeterministic.

### 4. Creation and import use a staged credential transaction

The core profile service handles create/import in this order:

1. lock and validate the current store and proposed unique profile/name/principal constraints;
2. for generation, ask the selected writable provider to create one new entry without exposing the seed; for import, resolve the exact existing reference;
3. construct the signer, derive its canonical principal, and compare any declared/imported principal exactly;
4. build and validate the entire candidate store;
5. atomically replace metadata;
6. select only when explicitly requested or when creating the first profile under the documented command behavior.

If a generated credential is stored but metadata replacement fails, invoke the provider's unreferenced-entry cleanup using the exact generated reference. A cleanup failure returns a bounded reference and remediation command, never the secret. Existing imported credentials are never deleted on metadata failure.

Legacy import reads `[Identity]` only inside the explicit import command. The command may preview and write, but normal runtime never calls the legacy parser after cutover.

**Alternative considered:** write metadata before the credential. Rejected because it creates a selected profile that cannot sign if provider storage fails.

### 5. Core profile commands exist without domain plugins

`core_buyer.cli.build_app` registers one core-owned `profile` group before plugin assembly:

- `create`, `import`, `list`, `show`, `select`;
- `rotate`, `retire`, `delete`.

Commands accept public names, schemes, provider kinds, and locators, with secret input entering only through provider-owned secure prompts or preconfigured backends. JSON and human output use the same redacted projection. Domain entry points receive no authority to replace these commands.

**Alternative considered:** keep VM-specific identity commands and later extract. Rejected because it would immediately create the second convention this change exists to remove and leave API credits with different recovery semantics.

### 6. One core resolver injects signer plus immutable profile context

Replace `resolve_identity_config`, direct credential environment lookup, and plugin-local identity helpers with a core `BuyerProfileResolver` that returns:

```text
ResolvedBuyerIdentity
  profile_id
  principal
  signer
  source = fresh | recovery
```

Fresh resolution loads the selected active profile and primary principal. Recovery resolution receives the run's `profile_id` and canonical principal and loads that exact historical principal's credential reference, irrespective of current selection or primary. Both paths construct the signer through the identity registry and compare its derived principal before returning it.

Core passes `ResolvedBuyerIdentity` or its signer/profile-safe view through existing domain hooks. Plugins cannot request raw credential material. Wallet resolution remains separate and occurs only after a selected effect requires it.

**Alternative considered:** resolve a signer independently in each command. Rejected because nested phases could observe different selection or provider state and because plugins could reintroduce secret precedence.

### 7. Run-log version 3 records stable profile identity

Bump the buyer run-log envelope to version 3. The first event records `buyer_profile_id`, exact public `buyer_principal`, and signature-contract version. Every subsequent event retains and validates those reserved values. Secret-field rejection expands to profile and credential vocabulary that could carry resolved material.

Version-2 migration requires the profile store and finds exactly one profile history entry matching the recorded canonical principal. It atomically rewrites one run file with the stable profile ID while preserving run ID, event sequence, timestamps, negotiation/deal/settlement/operation IDs, and domain payloads. Zero or multiple matches fail without rewriting. Existing address-only migration runs first, then profile binding; the complete candidate is written once.

**Alternative considered:** omit profile ID and scan all profiles on every resume. Rejected because the same historical principal may eventually be imported into retired/audit-only metadata and because run ownership must not change when profiles are renamed or selected.

### 8. Rotation separates new-run promotion from retained recovery

The rotate command resolves both current and replacement signers and uses the existing canonical dual-proof rotation intent. After both proofs validate, one atomic store update:

- adds or validates the replacement history entry;
- marks it primary;
- marks the predecessor retained/overlap;
- records nonce, intent digest, overlap, and required authority-binding state.

Fresh runs immediately use the replacement. The predecessor credential reference remains loadable for exact old-run recovery. `core/buyer` builds retirement blockers by scanning validated recoverable run summaries for the principal. The profile store also blocks retirement while any authority payer binding remains bound to the predecessor or records incomplete rotation.

Retirement changes the principal state and disallows new resolution except where the run was already authorized under a still-retained recovery state. Credential deletion is a separate explicit action after no profile, run, or binding references it.

**Alternative considered:** rewrite old run logs to the replacement principal. Rejected because accepted counterparties and operation identities were signed by the original principal; rewriting history does not authorize recovery.

### 9. Profile deletion is conservative and does not imply secret deletion

Deleting a profile requires it to be unselected, retired, free of recoverable runs, free of active/incomplete authority bindings, and free of required principal audit state. The metadata removal and optional provider deletion are separate confirmations. Provider deletion revalidates that no other profile history references the same credential reference and only then invokes the exact provider.

**Alternative considered:** delete metadata and credentials together by default. Rejected because keyring/file entries may be shared intentionally outside this store and silent deletion would be irreversible.

### 10. Hosted payer bindings use a provider-neutral authority key

Represent a binding by `(authority_id, environment)` plus an opaque binding string, the canonical marketplace principal currently owning it, and a small lifecycle enum such as `active`, `rotation_pending`, or `retired`. The identity kit validates bounds and uniqueness but does not import the hosted client or interpret the binding.

The later hosted consumer owns create/rotate/retire calls and updates this metadata through the profile service's atomic mutation. Store serialization and redacted projections reject Customer, PaymentMethod, mandate, provider, funding, action, and bank/card fields structurally.

**Alternative considered:** store hosted payer state in a separate settlement config. Rejected because payer ownership must rotate with the local buyer profile and retirement guards need one authoritative local relationship.

### 11. Deployment mounts metadata and secrets separately

Local interactive use defaults to the user XDG data location and may use keyring when explicitly selected. Headless Compose/Helm roles mount the profile metadata directory persistently and inject a strict file or exact environment reference only into the buyer process. Public templates contain provider kind and locator, never secret contents. Secret-file paths are absolute within the buyer runtime and checked at use.

The cutover generator removes direct buyer `[Identity]` from role templates. Service-role identity remains unchanged; this change does not move storefront, registry, or provisioning identities into buyer profiles.

**Alternative considered:** encode the profile document in a ConfigMap. Rejected because selection, rotation, and hosted-binding updates are mutable user-owned state and ConfigMap publication broadens local identity metadata unnecessarily.

## Risks / Trade-offs

- **[Keyring behavior varies by OS and session]** → Keep it an explicit provider, detect unusable backends before metadata commit, and make strict file/environment providers first-class headless options without fallback.
- **[Filesystem permission checks can race]** → Open with no-follow semantics, validate the opened descriptor's type/owner/mode, and read from that descriptor rather than reopening by path.
- **[Concurrent profile commands can lose updates]** → Serialize with one adjacent lock and revision comparison, then atomic replace and directory fsync.
- **[Generated secret cleanup can fail after metadata failure]** → Return only a bounded orphan reference and explicit cleanup command; never select the failed profile or expose the secret.
- **[Rotation may retain old credentials for a long time]** → Show concrete run and authority-binding blockers; require explicit retirement once blockers clear rather than guessing safe deletion.
- **[Run-log migration depends on profile import ordering]** → Stage explicit profile import first, preview unique run bindings, and fail atomically when a principal has zero or multiple profile matches.
- **[Clean cutover temporarily breaks old automation]** → Ship preview/import tooling before runtime removal, update every role fixture and deployment reference in one coordinated release, and reject old/new mixed inputs with actionable paths.
- **[Opaque hosted bindings could become a dumping ground]** → Use a strict bounded model with only authority/environment, opaque ref, owner principal, and lifecycle; reject unknown/provider-shaped fields.

## Migration Plan

1. Ship profile-store/provider libraries and read-only `profile import --check`/migration preview while existing buyer runtime remains quiesced for the selected operator migration window.
2. Inventory every local/headless buyer configuration and existing recoverable run log. Choose one explicit provider and XDG destination per profile; fix secret-file ownership/mode before import.
3. Run import preview. It derives each principal, detects duplicates/conflicts, and previews unique run-log bindings without writing or displaying secrets.
4. Run explicit import. Create the profile store atomically, validate it after replacement, then migrate each run log to version 3 atomically while preserving all operation identities. Keep legacy configuration backups until the whole candidate validates.
5. Update generated role files, Compose/Helm mounts, Secret references, and automation callers to use profile selection/provider references. Remove direct buyer `[Identity]` and raw credential inputs.
6. Activate the clean-cutover runtime only after every required profile, run log, plugin, and deployment render validates. Fresh runs use the selected primary; recovery resolves recorded history.
7. Before any profile-based run starts, rollback may restore the prior runtime and matching legacy config/run logs together. After version-3 events or profile rotation/binding updates exist, preserve the profile store and recover forward; do not downgrade logs or reconstruct raw identity precedence.

## Design promotion plan

| Accepted decision | Permanent destination |
|---|---|
| Profile aggregate, XDG store, credential providers, atomicity, rotation retention, opaque hosted bindings | `openspec/specs/marketplace-identity/{spec.md,architecture.md}` |
| Fresh/recovery resolver, core commands, plugin injection, run-log version 3, legacy runtime rejection | `openspec/specs/buyer-orchestration/spec.md` |
| XDG mounts, permissions, provider-specific headless injection, cutover and generated config | `openspec/specs/deployment-state/spec.md` and `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| Deterministic store/provider/migration matrix, multi-domain conformance, canary boundaries | `openspec/specs/test-compatibility/spec.md` and `docs/development/TESTING.md` |
| Foundation layering and buyer profile flow | `docs/development/ARCHITECTURE.md` |
| User lifecycle, import, selection, rotation, and recovery commands | `docs/buyer-quickstart.md` |
| Goal state and change mapping | `docs/development/ROADMAP.md` |
