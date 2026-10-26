## Why

API credits and inference sell the same thing: access to an HTTP API, paid for
in advance and delivered as a bearer credential that a gate checks on every
request. What differs between them is what the listing describes and how a
request is priced. Everything else — issuance and its digest, the key service,
the gate's authority client, the storefront's issuance and settlement
composition, the buyer's purchase flow — is the same machinery.

The campaign first planned to copy that machinery into the inference domain and
extract a kit afterwards, once two working consumers showed where the boundary
lay. The copy was carried out as far as the storefront and the authority, and
it answered the question: inference needed roughly 12,500 copied source lines
and added fewer than 300 of its own — a model-card listing builder, a guard
refusing rate cards the stack cannot charge, and a materialization pinning the
rate card at acceptance. There is no boundary to find inside that machinery.
Review of the plan priced the duplication and asked for the alternative the
repository already defines for compute: a family vocabulary package and a family
kit, with each domain reduced to composition wiring, its API controllers, and
the behaviour it alone owns. The copied pull requests were withdrawn unmerged.

This change builds that family. `docs/development/ARCHITECTURE.md` says a
domain with no shared vocabulary beneath it has no family, and names API credits
as the example; a second API-selling domain gives it one. The family is `api`,
not `credits`: credits is one way to pay for API access, and a domain that sold
access by subscription or metered fiat would want the issuance and the gate
without the ledger.

## What Changes

- **Pin API credits first.** Before anything moves, regression tests record the
  exact issuance request digest, fulfillment identity, evidence digest bytes,
  and attestation shapes the API-credits domain produces today for a fixed input
  set. Every later slice is proven byte-identical against them. A failure here
  is a blocking defect, never a migration.
- **The `api` family under `domains/api`.** `ARCHITECTURE.toml` gains the
  family row and both domains join it. The kit lives under the family directory,
  as the scope rule prescribes; compute's kit sits elsewhere only under override
  rows another change owns.
- **Eleven projects, each forced by a rule.** The vocabulary `arkhai_api`
  (purchase shape, issuance models, digests, evidence, the label type;
  foundation kits only, naming no domain's label); `contracts` and `client`
  for the family's wire models and negotiation carriers, the authority's
  plain-data route declarations, and its typed client; three side libraries whose dependencies the other sides do not need —
  `authority` (key service, ledger, quota-as-capacity composition, migrations,
  route services, the declaration adapter; never the client), `selling`
  (issuance and settlement composition, negotiation adapters, quota listing
  binding and publication, route services, persistence, the selling
  bundle), and `buying` (buy, negotiate, settle, and listing flows, the buying
  bundle); `gate` for the bearer gate; and four mechanism libraries split by
  side, `selling-alkahest`, `selling-arkhai-payments`, `buying-alkahest`, and
  `buying-arkhai-payments`. `design.md` names the rule behind each. The change
  stands on `dev` alone and depends on no other change.
- **API credits composes the kit, slice by slice.** Each slice deletes the
  implementation it replaces, leaves API credits green on its suites and lane,
  and keeps `make check-packaging` green. Behaviour, wire, digests, and data are
  unchanged. API credits ends as the first thin domain: its listing schema and
  kind bindings, its fixed per-request amount as a contribution, its
  configuration, its bindings, compose files, and seed.
- **One digest implementation.** The authority composes the vocabulary's digest
  and identity functions and deletes its own copy, so client and server cannot
  drift.
- **One typed contribution bundle per side.** A storefront hands `selling` its
  label, kind literals, listing schema and publication mapping, issuance
  projection from the accepted listing to the authority's command, optional
  guards, optional acceptance hook, optional public-result extension, and
  consumption rule; a buyer plugin hands `buying` its schema identity, filters,
  rendering, and commands. The API-credits terms module becomes a binding of
  the vocabulary's shape; the inference domain's binds the same shape when its
  own campaign composes the kit.
- **Each domain's service root composes the authority kit.** The API-credits
  service stays, with its distribution, image, entry point, and version response
  unchanged, and shrinks to a composition root that passes the kit its label
  and one immutable capacity profile — offering mode, pool declarations,
  backing — in place of the `api_credits` values the service
  hard-codes today. The inference service root is the stack change's, and
  mounts metering's routes when they come.
- **The gate relocates under its own name.** `arkhai-api-gate` is the bearer
  gate, httpx-only with identity optional, depending on no family package, with
  a dev-only parity test holding its local route spelling equal to `contracts`,
  and the Python reference for the conformance trace. Retiring
  `arkhai-apicredits-middleware` is a package and import break: the sample app
  and its tests, the service's integration tests, the conformance runner, the
  middleware READMEs, the cookbook, the identities README, the publish and test
  workflows, and the root and domains Makefiles migrate to the gate in the same
  change. No re-export is kept, because no third party installs it and sellers
  take the pre-built images.
- **The compatibility promise is proven at its width.** Beside the digest pins,
  the first task records baselines for the route surface and OpenAPI document,
  authentication roles and operation names, refusal codes and bodies,
  environment variables and settings keys, schema and migration history, and
  the version response; every slice diffs them to zero, and upgrade and
  rollback are each tested against a retained database.

## Capabilities

### New Capabilities

- `api-family`: the family vocabulary and kit — one vocabulary, distributions
  split only where a rule forces it, label-parameterized digests proven
  byte-identical, one typed contribution bundle per side with an issuance
  projection, each domain's service root composing the authority kit with its
  label and capacity profile, one published gate, kit-owned route services
  behind composition-owned bindings.

### Modified Capabilities

- `api-credits`: composes the family kit with no domain-local copy; runtime
  behaviour, wire, authentication, digests, schema, configuration, and its
  service's distribution unchanged, proven by the pins and the baselines; the
  middleware retirement classified as a package break.
- `market-composition`: the family-kit rules gain a second family beside
  compute, scoped to prepaid bearer access, and the extracted-concern rule
  gains this instance.
## Non-Goals

- No change to any API-credits digest, wire shape, database row, or runtime
  behaviour; the one break is the middleware distribution's retirement, listed
  as such.
- No inference domain work. The inference market campaign, opened in its own
  plan, composes this kit: its contract binds the vocabulary and its stack
  composes the libraries.
- No metering, holds, usage capture, or change to the fixed per-request
  consumption rule beyond relocating it.
- No ledger-free access distribution; deferred in `design.md` with its trigger.
- No TypeScript or Rust gate changes beyond what relocating the Python reference
  requires, and the verify-cache fixes the owner directed onto this change's
  branch (see `design.md` D10); their conformance fixture stays where it is and
  stays green.

## Dependencies and Related Changes

- **Depends on** nothing. API credits exists on `dev`, and every slice is proven
  against it.
- **Enables** the inference market campaign, opened in its own plan: its
  contract change binds the vocabulary and its stack change composes the
  libraries, contributing the model-card listing, its guards, its
  materialization, and its service root.
- `seed-default-pool-at-runtime` applies to the compute provisioning service the
  rule this change applies to the credits authority's pool seed: configuration-
  driven seeding runs in runtime initialization, not in a migration.
- `sign-multi-language-credits-middleware` owns the TypeScript and Rust gates
  and the conformance fixture's home.
- `align-package-paths-with-layers` owns the override rows that keep compute's
  kit outside its family directory; this change writes none.

## Impact

- New: `domains/api/` with eleven projects — the vocabulary at its root and
  `contracts`, `client`, `authority`, `selling`, `buying`, `gate`,
  `selling-alkahest`, `selling-arkhai-payments`, `buying-alkahest`, and
  `buying-arkhai-payments` beneath it; the pinned regression fixtures and
  compatibility baselines under `domains/apicredits/tests/`; a `[[families]]` row and the `family`
  attribute on the API-credits row in `docs/development/ARCHITECTURE.toml`; a row for the gate in
  `docs/development/RELEASING.md`'s published-packages table and the publish
  workflow, in place of the middleware's, with the gate's one-time PyPI setup
  for a maintainer.
- Touched: every `domains/apicredits` package, which shrinks to bindings and
  its own vocabulary, the service becoming a composition root over the
  authority kit with its distribution, image, and entry point unchanged; every
  repository consumer of the middleware;
  `domains/Makefile`, the root `Makefile` and `tests.yml` target lists, the
  aggregate kit test target, root `dist` ordering, and every touched project's
  `pyproject.toml` and lock.
- Removed: the `arkhai-apicredits-domain` override row in `ARCHITECTURE.toml`
  and the unmounted issuance-evidence router.
- Wire: none. Database: none; migration identifiers unchanged. Packaging:
  eleven new wheels, the gate published in the middleware's place; the
  API-credits wheels shrink and bump.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — the family-kit section gains the
      `api` family beside compute, with the rule that a family's distributions
      split only where a stated rule or dependency weight forces it; the runtime
      service map and the authority-boundaries row for keys and issuance cite
      the family authority.
- [x] `docs/development/RELEASING.md` — the published-packages table replaces
      the middleware's row with the gate's.
- [x] Existing subsystem specification — `api-credits` composition prose and
      its architecture companion's "Implementation composition";
      `market-composition` family-kit requirements.
- [x] New subsystem specification — `api-family`, with an architecture
      companion for the contribution surface and the deferred ledger split.

### Knowledge to promote

- The `api` family, its root, and the rule-derived distribution set —
  `docs/development/ARCHITECTURE.md#family-kits`.
- A family kit splits only where a rule or dependency weight forces it; an
  anticipated split is recorded with its trigger, not built —
  `docs/development/ARCHITECTURE.md#family-kits`.
- The contribution bundle and what each domain supplies —
  `openspec/specs/api-family/architecture.md`.
- Label-parameterized digests and the pin that proves them —
  `openspec/specs/api-family/spec.md`; the API-credits companion's
  "Idempotency boundaries" cites the vocabulary.
- Per-domain service roots over the authority kit, the capacity profile, and
  the issuance projection — `openspec/specs/api-family/spec.md` and
  `ARCHITECTURE.md`'s runtime service map.

## Status

Ready for implementation. The design in `design.md` passed its design gate on
2026-10-22 after four external review passes; the round's dispositions are
recorded in `interventions.jsonl`, and the review records and their triage are
kept in the change's `reviews/` directory, which the repository keeps untracked
as the change workflow prescribes. `tasks.md` plans eleven sections, pins and
baselines first. The change stands on `dev` and waits on nothing.
