# Testing Strategy

This document defines the testing conventions for this repository. It
exists to give every contributor — human or AI — a consistent mental
model of what each test level is responsible for, what it is explicitly
not responsible for, and how the levels relate to each other. Put a new
test at the lowest level that can meaningfully prove the behavior in
question; see `AGENTS.md`'s "Tests and diagnostics" for the underlying
rule this document elaborates.

Read this alongside `docs/development/ARCHITECTURE.md` (system shape)
and `openspec/README.md` (documentation placement). This document
describes current testing practice, the same way `ARCHITECTURE.md`
describes current system architecture — it is not a changelog of how
testing conventions were introduced, and it should be corrected in place
when practice changes rather than accumulate historical commentary.

## Four-Level Hierarchy

### 1. Unit Tests

**What they cover:** A class or function in isolation. A unit test
instantiates one class, passes mocked collaborators for its injected
dependencies, and asserts on the return value or side effects of a
specific method.

**What they do not cover:** Orchestration. If a function's sole purpose
is to call other functions in sequence, that function does not have
meaningful unit tests — the correctness of the sequence is an
integration-test concern. The final abstraction before an external
boundary (a database write, a subprocess invocation, an HTTP call) is
similarly not meaningful to unit test in isolation; its behavior is
validated by integration tests against the real boundary or a
well-defined mock of it.

**Mocking convention:** Use `unittest.mock.MagicMock`/`AsyncMock` for
injected collaborators, passed in via the constructor. Do not patch
module-level imports — the dependency-injection composition pattern
used throughout this repository makes constructor injection the natural
seam; patching around it defeats the purpose of the seam and produces
tests that break when internal call structure changes even though
behavior didn't.

**Composition-boundary convention:** When a role receives a versioned domain contract, unit tests should inject a distinct compatible object and assert object identity at each constructor boundary rather than patching the default resolver. Fail-closed cases belong at the composition root and must assert that persistence, network, and worker collaborators were not constructed. Existing integration tests remain responsible for public behavior and persisted-state parity.

**Negotiation-runtime convention:** Protocol invariants are tested once in
`kit/negotiation-runtime/tests/unit` with an in-memory recording repository and
injected opaque domain hooks. Those tests prove canonical-principal checks,
round and terminal ordering, transcript recovery, acceptance persistence, and
fail-before-effect behavior for recorded binding mismatches. Storefront tests
then prove only their domain adapters: term decoding, seller policy input,
accepted-artifact construction, and domain persistence/effect hooks. A domain
test must invoke `NegotiationRuntime`; reintroducing a local lifecycle helper
would test the duplication rather than the production composition.

### 2. Integration Tests

**What they cover:** End-to-end request → response paths with the full
application stack running (the real app, a real database, the DI
container wired) and a controlled mock only at the external I/O
boundary. Orchestration logic, background job processing, retry
behavior, and error propagation are validated here, not in unit tests.

**What they do not cover:** Every edge case of data transformation
logic — that belongs in unit tests. An integration test needs one
representative case per external-mock behavior, not exhaustive
parametrization.

**External boundary definition:** Any I/O that crosses a process
boundary — a subprocess invocation, a call to a service this codebase
doesn't own, a blockchain RPC call. Mock at the point this codebase's
own code wraps that boundary, not deeper.

**Test setup pattern:** Use `httpx.AsyncClient` with `ASGITransport`
against the real application instance, injected via the service's
canonical typed-client constructor (`FooClient(transport=...)`).
Override DI container providers for the specific collaborator being
mocked before the test and restore them after.

**Typed client contract verification — the "no raw calls" rule:**
Integration tests call a service's canonical typed client methods
directly against the in-process app, not raw HTTP. Route strings,
request body shapes, and response parsing are owned by the client;
happy-path tests should not construct requests by hand. If an API
renames a field or changes a route, the typed client should raise its
own client error and the test should fail immediately — a test that
builds its own request dict will not catch that, which is exactly the
kind of interservice mismatch that mocked-boundary unit tests cannot
catch either. This is the single most important rule for the layer
where real bugs are most often found in review: an integration test
that bypasses the typed client to make assertions easier has quietly
stopped testing the client contract at all.

Two narrow exceptions are permitted:

1. **Rejection-path tests** — testing server-side validation of inputs
   the typed client deliberately refuses to construct (asserting a 422
   on a malformed body the client's own request model would reject
   before it ever reached the HTTP layer). These verify the *server's*
   validation boundary, not the client's, and must only assert on
   status codes, never on response body field names, and must be
   clearly commented as rejection-path tests.
2. **Service-internal state setup** — inserting DB rows directly to
   establish precondition state that cannot be expressed through any
   HTTP API endpoint. This is not an HTTP call at all; it is standard
   test-setup, and should be preferred only when the state genuinely
   isn't reachable through an API — prefer creating precondition state
   through the HTTP API where feasible, so integration tests stay
   honest about what the API contract actually supports.

Any other use of a raw HTTP call in an integration test is a gap: either
add a method to the canonical client, or restructure the test. A comment
like "not yet a client method" is a deferred-debt marker, not a
permanent exemption.

**Sync/async client parity:** When a client package exposes both async
and sync variants, the owning service's unit suite should include a
small contract test comparing public method names and signatures across
both. A new client method must be added to both in the same change. This
guardrail belongs with the service's tests, not the client package,
because the service owns the contract-validation boundary — it does not
substitute for integration tests that exercise the methods through real
controller routes.

**Async test discipline — no sleeps:** Tests exercising a background
job-processing loop must never use `asyncio.sleep` or a bare timeout
race to wait for a side effect — this produces intermittent failures.
Use an explicit test seam instead: an injectable callback invoked at the
point the test needs to synchronize on (for example,
`AsyncJobQueue.__init__`'s `on_job_started: Optional[Callable[[str], None]]`,
`None` in production and zero-cost there), set an `asyncio.Event` from
the callback, and `await asyncio.wait_for(event.wait(), timeout=...)`
before proceeding. If no such seam exists yet where a test needs one,
adding it is the correct fix, not a sleep.

### 3. Smoke Tests (Deployment Validation)

**What they cover:** Stateless, idempotent verification that a deployed
stack is wired correctly — services can reach each other, authentication
is enforced, health endpoints respond, expected routes exist.

**What they do not cover:** Service semantics. By the time a smoke test
runs, semantics have already been validated by integration tests. A
smoke test verifies that a health endpoint returns 200 and that a
protected endpoint returns 401 without valid credentials — it does not
submit a real job and poll for completion.

**Current location:** `e2e-tests/tests/smoke/`, run as Helm test hooks
in Kubernetes (`helm/templates/tests/`, per-chart `templates/tests/`
directories).

### 4. System Integration Tests (End-to-End)

**What they cover:** Cross-service contracts — scenarios that require
two or more services to interact over the network to produce a
meaningful result.

**What they do not cover:** Anything already covered by the three levels
above. These tests are expensive to run and brittle to maintain; they
should be minimal in count and cover only the cross-service contract,
not any one service's internal logic.

**Current location:** `e2e-tests/tests/e2e/`.

Every deployable domain owns one release-qualified complete-deal scenario:
discovery, negotiation, settlement, delivery, and domain-defined teardown.
The teardown observation follows the resource sold: VM capacity is released,
an API-credit grant is consumed until the authority returns HTTP 402, and a
bare-metal lease is released only when authenticated access is revoked and the
selected-site authority reports teardown. A health check or static Compose
render is not deal evidence.

The scenarios share `DomainDealState`, exact event ordering, profiled buyer
configuration, and public client helpers from
`e2e-tests/tests/e2e/roles/helpers/domain_deal.py` and
`e2e-tests/tests/e2e/roles/buyer_cli.py`. The helpers keep domain results
opaque: they do not assume a VM listing, provisioning job, host field, API key,
Physical Resource, site, or teardown payload. A scenario supplies its codecs
and domain assertions instead of copying another domain's control flow.

Staged scenarios use `require_state` with one exact producer/consumer field.
When an earlier stage or external authority is unavailable, the dependent
stage names that prerequisite and remains blocked; it is never counted as a
successful live deal.

The e2e test pod cannot import service internals — it uses typed
clients, explicit test controllers, and stage/event APIs over HTTP, the
same "no raw calls" discipline integration tests follow. Design new
observability seams for e2e-visible behavior accordingly.

## Coverage Contract Between Levels

Each level has a defined jurisdiction. Duplicating coverage across
levels creates maintenance burden without a corresponding safety
benefit — a change should only need its assertions updated in one
place.

| Concern | Unit | Integration | Smoke | System |
|---|---|---|---|---|
| Data transformation / parsing logic | ✅ exhaustive | one happy path | ❌ | ❌ |
| Request/response model validation rules | ✅ exhaustive | ❌ | ❌ | ❌ |
| Orchestration / job lifecycle | ❌ | ✅ exhaustive | ❌ | ❌ |
| Retry / backoff arithmetic | ✅ | one case | ❌ | ❌ |
| Auth middleware enforcement | ❌ | ✅ | one case | ❌ |
| Client ↔ API contract | ❌ | ✅ | ❌ | ❌ |
| Service-to-service wiring | ❌ | ❌ | ✅ | ❌ |
| Cross-service business flow | ❌ | ❌ | ❌ | ✅ |

## Contract Fixtures

A **contract fixture** is a pair of functions — `build_*()` and
`validate_*()` — that define the canonical shape of a message at a
package boundary. They are shared between the producer's tests (which
call `validate_*` to assert real code emits the agreed shape) and the
consumer's tests (which call `build_*` to produce mock inputs of exactly
that shape). When the boundary changes, both sides break at once,
instead of the consumer silently mocking a shape the producer no longer
emits.

**When to add one:** A boundary earns a contract fixture when *both*
its producer and consumer have unit or integration tests. A
consumer-only mock with no corresponding producer test should stay as a
local inline value — a contract fixture without producer-side
enforcement just documents an agreement nothing actually checks.

**`build_*()`** constructs a minimal but complete canonical instance,
using keyword arguments with sensible defaults so a test can override
only the fields it cares about. Non-deterministic fields (timestamps,
generated IDs) get fixed sentinel values in `build_*` and range/type
assertions in `validate_*` — never equality checks, which produce
brittle failures when an incidental field shifts.

**`validate_*()`** asserts structural and semantic constraints on a
value produced by real code: field presence, type, and any invariant
the consumer depends on. It does not check incidental fields the
consumer ignores.

**Where they live — import direction always flows producer → consumer:**

- **Same-package boundary** (producer and consumer share a package):
  `tests/fixtures/<module>.py` within that package, importable as
  `tests.fixtures.<module>` by any test in the package. Example:
  `domains/vms/storefront/tests/fixtures/publish.py`.
- **Cross-package boundary** (the consumer is a separate, higher-level
  package): `src/<package_name>/fixtures/<module>.py` inside the
  producer's own source package. Because the producer is already
  installed as a wheel in consumer packages, this needs no path
  configuration — the import mirrors the client import it sits next to.
  Example: `core/storefront-client/src/storefront_client/fixtures/escrow.py`,
  imported as `from storefront_client.fixtures.escrow import build_claim_response`
  alongside `from storefront_client import SyncStorefrontClient`.

If the producer has no unit tests yet, create the `fixtures/` subpackage
anyway with dormant `validate_*` functions — they document the contract
and give a future producer test an immediate hook. Mark a dormant
validator's module docstring with which test file is expected to call
it once the producer gains coverage.

## Test File Layout

A service's tests split into `unit/` and `integration/` subdirectories
under its own `tests/` root, matching the four-level hierarchy above.
System-level tests live in the separate `e2e-tests` package, itself
split into `unit/` (its own helper logic), `smoke/`, and `e2e/`.

## Pool Offering-Mode Enforcement

Pool offering-mode coverage follows the lowest-meaningful-level rule while
proving that no execution layer relies on another layer's earlier decision:

- `kit/resource-pools` unit tests own declaration shape, typed reads,
  membership, absent-as-empty behavior, and identical validation across
  individual and bulk administration.
- `kit/site` unit tests own explicit claim identity and reservation admission.
  They assert that neither a VM-shaped resource nor any resource attribute
  supplies a missing mode, that an undeclared mode creates no hold, and that
  pool authorization remains independent of exclusive/shareable physical
  accounting.
- `kit/fulfillment` scheduler tests withdraw a declaration after reservation;
  orchestration tests withdraw it after provider input is prepared and assert
  no provider dispatch occurs.
- Provisioning migration tests cover fresh bootstrap, the system-owned default
  pool, exact derivation from provider/playbook/delegate configuration,
  idempotent rerun, narrowing, INFO evidence, malformed drift, single-proof
  backfill, conflicting proof, unproved active rows, and terminal rows.
- The deployed `e2e_pool_declared_modes` scenario sends an unsupported explicit
  mode for a real matching capacity resource and observes HTTP 409 plus no
  reservation row. It stops at the reservation boundary by design: provider
  failure would be evidence that admission occurred too late.

An executor-default inventory is part of closeout for changes to this boundary.
Search production compute contracts, persistence, dispatch, result, release,
site, storefront, and domain adapters for default arguments, `or` fallbacks,
and attribute-based inference; a passing focused suite alone cannot prove their
absence.

## Multi-Domain Storefront Composition

The common shell owns a boundary matrix rather than duplicating complete domain
scenarios at every level:

- core storefront unit tests cover contribution discovery, duplicate/unknown
  rejection, exact-object registry resolution, immutable listing/thread
  bindings, lifecycle carriers, publication fan-out, and schema-opaque result
  dispatch;
- VM storefront tests cover installed contribution wiring, exact public
  `virtualization_type`, configured source selection, negotiation/settlement
  adapters, selected-site capacity calls, restart recovery, and transactional
  legacy migration;
- bare-metal domain/storefront tests own only bare-metal codecs, publication
  semantics, and the production lifecycle hook supplied by that package;
- deployment tests render one combined image/command/database, both explicit
  registrations, disabled-domain absence, and secret canary exclusion;
- the system lane must observe a real VM deal and a real selected-site POOLS-7
  bare-metal deal concurrently, including result, teardown, and restored
  capacity. It remains blocked—not mocked—until the production bare-metal
  contribution and its live provisioning prerequisites are installed.

Every cross-swap test asserts the unselected policy, repository mutation,
capacity/provider call, result decoder, and teardown spy remain untouched.
Restart fixtures route from recorded bindings even when current publication
configuration changes. Migration tests compare source bytes on failed check or
write and prove the successful rerun idempotent.

## Marketplace Identity Verification

Identity tests follow the same lowest-meaningful-level rule while exercising
the security boundary from canonical bytes through composed roles:

Scheme-neutral behavior is exercised from one shared fixture matrix under both
Ed25519 and EIP-191 rather than by maintaining parallel feature suites. Tests
specific to normalization and cryptographic dispatch stay with the identity
plugins; tests that require a wallet or chain stay with the explicitly selected
EVM adapter. The representative hosted-fiat system path deliberately uses
Ed25519 with every wallet and chain setting absent, while focused EIP-191
integration coverage proves that selecting that scheme or an EVM effect does
not change the common marketplace contract.

Buyer profile tests treat metadata, provider access, and run ownership as
separate boundaries. The deterministic matrix covers create/import/select,
strict permissions and symlink rejection, exact-provider failures, generated
secret cleanup, dual-proof rotation, retention blockers, restart, retirement,
and deletion without inspecting a secret through a second path.

Run-log migration is an atomic multi-artifact transformation: populated v1/v2
runs become version 3 with stable profile UUID and canonical principal, every
candidate validates before activation, and a failure after an earlier
replacement restores the profile store and all run logs. An unresolved durable
manifest must fail startup rather than admit mixed identity precedence.

- Identity-kit unit and conformance fixtures cover strict Ed25519 and EIP-191
  principal normalization, byte-identical version 2 request/response and
  rotation vectors, field-by-field tamper rejection, timestamp skew, exact
  replay, changed reuse, and dual-proof bounded rotation.
- Authority integration tests use canonical typed clients against real
  applications and databases. They prove replay reservation precedes handler
  dispatch, exact principals and roles authorize, configured service-peer and
  site pins are enforced, signed responses are verified, and no body address,
  administrator key, private-key field, or missing-header fallback reaches a
  state mutation.
- Migration tests cover populated legacy state as well as fresh bootstrap and
  idempotent rerun. They assert stable publisher, listing, negotiation,
  obligation, fulfillment, and operation identifiers, explicit buyer run-log
  migration, complete rollback on malformed or conflicting owners, and
  startup/readiness rejection of drift or mixed signature versions.
- Composition tests exercise an Ed25519 hosted-fiat path with wallet, chain,
  RPC, balance, and gas configuration absent, and separately prove that a
  selected EVM effect resolves and validates only its adapter-owned inputs.
- Configuration and artifact tests use secret canaries to reject private
  material in public models, persistence, logs, rendered ConfigMaps,
  arguments, images, wheels, manifests, and fixtures. Hosted integration uses
  the exact manifest-pinned released client and shared conformance fixtures;
  editable sibling imports or copied hosted signing behavior are test
  failures.
- VM and API-credit plugin conformance uses the same selected-primary and
  retained-principal recovery fixtures. Discovery rejects any plugin missing
  `core.resolved-buyer-identity.v1` before command registration.
- Secret-canary scans include profile JSON, run-log JSONL, human/JSON CLI
  output, exceptions/reprs, generated buyer TOML, Compose/Helm renders,
  ConfigMaps, wheels, images, and evidence. Credential values may appear only
  inside the selected provider boundary.
- The system-level identity scenario runs publication, discovery, negotiation,
  hosted funding, settlement, status, reclaim, and recovery with Ed25519
  principals and no wallet configuration. It also checks coordinated
  readiness failure when any authority or client lacks the pinned identity
  version.

## Hosted Settlement Evidence

Hosted settlement has one provider-authentic system lane:

```console
make hosted-stripe-test
```

This protected target verifies one exact ordinary signed hosted production release and one exact marketplace consumer release, then runs the wallet-free VM lifecycle against Stripe test mode. It attributes `card.v1`, `us_bank_transfer.v1`, `us_ach_debit.v1`, and off-session `requires_action` separately through ordinary publication, discovery, negotiation, exact post-acceptance funding authorization, storefront-mediated materialization/status/reclaim, transient buyer action, authoritative funding, VM fulfillment evidence, condition evaluation, collection or eligible reclaim, restart, and recovery.

Credential-free marketplace checks own the behavior that does not require Stripe: exact profile config and deterministic option identity, independent readiness/publication, local persistent payer binding, direct released-client payer and authorization helpers, bounded automation policy, storefront mediation, action redaction, delayed funding gates, immutable runtime journals, legacy card recovery, fulfillment/reclaim exclusion, package contents, release verification, and evidence-schema canaries. Deterministic hosted ports describe provider-neutral outcomes and never establish Stripe behavior.

API-credit hosted checks additionally divide ownership as follows:

- API-credit domain/buyer tests own strict `settlement_options`, exact
  quantity-scaled minor-unit pricing, selection and accepted-party/key-target
  validation, wallet-free policy resolution, transient actions, and recorded
  resume/reclaim identities;
- credits-authority tests own canonical principal ownership, deterministic
  fulfillment identity, immutable request-digest conflicts, exact-once quota,
  grant and balance mutation, and safe credential retry behavior;
- storefront tests own accepted-state preparation, no issuance before
  authoritative funding, commit-then-fail retrieval, private credential
  isolation, canonical signed portable evidence, condition-before-collection,
  reclaim exclusion, restart, and independent Alkahest behavior; and
- protected system evidence owns only the ordinary signed producer release,
  Stripe interaction/funding, deployed resolver, new-key consumption to 402,
  and same-profile existing-key top-up.

If the signed producer, protected Stripe account/browser inputs, or deployed
resolver is unavailable, those exact assertions remain blocked. A deterministic
hosted port, local resolver double, or successful Alkahest deal cannot be
reported as their substitute.

Protected preflight completes before publication or financial mutation and requires:

- the exact marketplace commit and signed hosted production manifest, client wheel hash/version, service image digest, API/schema/migrations, conformance and provenance identities, signed release repository/workflow reference, hosted source commit, and independently recorded protected workflow run;
- a test-mode secret (`sk_test` or least-privilege `rk_test`), Stripe connectivity, and non-live returned objects;
- the expected allowlisted connected account with the exact ownership, funding-profile, currency/country, charge/transfer, and readiness capabilities for the selected scenario;
- a supported interactive or saved-instrument/mandate/funding path for the selected profile;
- Stripe CLI forwarding to the exact loopback webhook endpoint; and
- Chromium plus the official Stripe test input required by that profile and action.

Unavailable external prerequisites are recorded per assertion. They do not become a silent skip and do not permit substituting another funding profile, a credential-free result, or a scripted provider result. Terminal executed outcomes are classified as `product` (the observed contract is wrong), `account` (ownership/capability/readiness is unsuitable), `environment` (artifact/credential/Stripe/CLI/browser/network access is unavailable), or `timeout` (a named state did not converge after valid preflight).

System recovery uses real omissions: webhook forwarding, the authority API, the ordinary worker, or the marketplace consumer may be stopped and restarted while preserving authority and marketplace state and the original obligation, authorization, settlement, and operation identities. Financial mutations remain inside production paths and exact retry cannot issue a replacement mutation under a new identity.

Protected evidence is schema-validated and signed by the marketplace evidence signer. It keeps the marketplace repository/commit distinct from hosted manifest/client/image/API/schema/migrations/provenance/repository/workflow/source and protected-run identities. Reports permit only selected profile/currency, public lifecycle stages, normalized outcomes, attempts, timestamps, and bounded hashed opaque correlations. Credentials, provider/customer/payment-method/mandate/bank/card identifiers or data, raw setup/payment/confirmation/bank-instruction actions and URLs, payloads, events, requests, source-bearing local paths, and unrestricted logs are rejected before signing.

Alkahest remains an independent mechanism E2E:

```console
make -C e2e-tests test-buyer-machine \
  BUYER_MODULE=e2e_alkahest_escrow_codecs
```

Local EAS/allowlisted-arbiter behavior is condition-boundary conformance only, not hosted financial evidence. There is no standalone hosted local-EAS operator target; focused condition tests do not establish hosted financial behavior.

### Bare-metal hosted lanes

Credential-free bare-metal suites own exact trusted option/party/resource derivation, ready-profile publication, hosted-only registry composition, action redaction, immutable accepted binding persistence, no reservation before authoritative funding, selected-site reservation/fulfillment replay, access-ready evidence, restart and collect/reclaim exclusion, return/loss projection, teardown independence, buyer-wheel discovery, and Alkahest non-regression. These tests use provider-neutral ports and real local persistence; they do not claim Stripe or physical-host behavior.

The protected marketplace lane must use the ordinary signed hosted release for all three profiles and a disposable selected-site whole host. Acceptance observes authenticated discovery through collection or eligible reclaim, real access using buyer-only SSH material, lease expiry/revocation, executor teardown, and capacity release. Missing signed artifacts, Stripe account/rail prerequisites, or a disposable host remain named external blockers. A fake fulfillment flag, local evidence fixture, or no-op teardown never satisfies the protected lane.

## Boundary-Change Validation

Moving or renaming a contract at a package boundary needs more than
relocated unit tests. Validate:

- package build and wheel contents;
- typing markers and static type checks where the contract moved;
- allowed dependency direction, including `TYPE_CHECKING` imports (see
  `AGENTS.md`'s "Package and dependency discipline");
- old import removal, or an explicit, deliberate compatibility path;
- every changed consumer's unit and integration suites, not just the
  producer's;
- composition startup and duplicate-registration checks;
- deterministic, idempotent retry behavior;
- observable lifecycle events verified without arbitrary sleeps (see
  "Async test discipline" above).

## Cross-Language Contract Conformance

Where the same protocol has independent implementations in more than one
language, each implementation MUST reproduce one shared, data-driven
conformance trace rather than each maintaining its own hand-written
assertions of the same behavior. Keeping the trace in data, not in each
language's test code, is what makes "identical behavior across
languages" a checkable claim rather than an assumption.

**Current example:** the API-credits gating middleware's Python
(reference implementation), TypeScript, and Rust ports all replay
`domains/apicredits/middleware/conformance/session.json` — one recorded
session of requests against the gate, with each step asserting the
allow/deny decision, the deny body's machine-readable error code,
whether a `purchase` pointer is present, and call counts against the
stateful collaborators the step is meant to exercise (cache-hit
skipping, zero-calls-on-known-exhaustion). See
`domains/apicredits/middleware/conformance/README.md` for what each step
field asserts, and the runners at
`domains/apicredits/middleware/python/tests/conformance_runner.py`,
`domains/apicredits/middleware/typescript/test/conformanceRunner.ts`,
and `domains/apicredits/middleware/rust/tests/conformance.rs`.

## Offline Review Validation

Review validation packages a scoped wheelhouse rather than copying a
virtual environment or sharing a package cache, so an offline reviewer
can run each affected project's real `make test` target with network
and Python downloads disabled. The scope resolver accepts an explicit
project list or a review manifest, and otherwise maps a Git diff to
repository-owned project roots and applies impact-expansion rules from
there. Each project keeps its own locked third-party requirements rather
than being forced into one synthetic shared environment. A project's own
`Makefile` must keep its interpreter selection configurable so the
review environment can use the wheelhouse's declared Python version.

**Current implementation:** `make review-wheelhouse` (scope preview via
`make review-wheelhouse-scope`, controlled by `REVIEW_PROJECTS`,
`REVIEW_SCOPE_FILE`, or `BASE_REF`), which rebuilds wheels, refreshes
scoped lockfiles (`scripts/refresh-review-locks.py`), and bundles the
result via `scripts/package-review-wheelhouse.sh`.

## Running the hosted Stripe body locally

The protected matrix and the mechanical body it drives are separate concerns.
The body — compose stack, Stripe test-mode calls, webhook forwarding, browser
interaction, lifecycle assertions — runs on a developer machine against your own
branch. Only its *evidence* depends on release provenance.

A local run needs no attested release, no credential broker, and no self-hosted
runner. It does still refuse live credentials, an unready connected account, and
any webhook destination that is not loopback: those gates hold in every mode.

```sh
# 1. Assemble what a credential broker would otherwise return: provider
#    credentials from your own file, identities generated for this run, and a
#    storefront configuration whose pinned identities those keys own.
rundir="$(mktemp -d)"
eval "$(uv run --no-project --with arkhai-kit-identity --find-links .dist \
  python scripts/assemble-hosted-credentials.py \
  --provider-file ~/.config/arkhai/stripe-test.env \
  --storefront-config-template e2e-tests/config/hosted-storefront.toml \
  --buyer-config-template e2e-tests/config/hosted-buyer.toml \
  --directory "$rundir" --print)"

# 2. Producer identities: five are read from the committed trust manifest. The
#    run id is not in there, so it comes from the producer repo's release run
#    for that tag.
export HOSTED_PRODUCTION_WORKFLOW_RUN_ID=...

# 3. Pick a lane and run.
export HOSTED_STRIPE_TEST_SCENARIO=collection \
       HOSTED_STRIPE_TEST_FUNDING_PROFILE=card.v1 \
       HOSTED_STRIPE_TEST_INTERACTION=interactive \
       HOSTED_STRIPE_TEST_RUN_REF="local-$(git rev-parse --short HEAD)"
make hosted-stripe-test-local
```

Both templates are needed because the storefront, the buyer, and the service
environments in `compose.vms-fiat.yml` pin the *same* identities — the registry
authorities, the storefront, and the provisioning service. A brokered run holds
the private keys behind those committed identities; a development run generates
keys instead, so it has to re-point every pin at once. The exports the assembler
prints do that: the two rewritten configuration files, and the identifiers the
Compose overlay substitutes in place of its committed defaults.

The provider file defines `STRIPE_SECRET_KEY` and `STRIPE_CONNECTED_ACCOUNT_ID`.
Release v0.2.1 checks the key prefix against its own Stripe mode, so the key must
be an `sk_test_` value — a restricted `rk_test_` key is refused. Keep the file
outside the repository.

### Running against a settlement authority built here

The producer half needs no published release either. A version that has none —
the usual case while it is being developed — is bound by building it from a
sibling checkout and naming the image:

```sh
# Builds the image and the OpenAPI, conformance, and migration artifacts.
make build-hosted-producer HOSTED_SETTLEMENT_SOURCE=../hosted-settlement-service

export HOSTED_LOCAL_HOSTED_IMAGE=localhost/arkhai-hosted-settlement-service:0.3.0
make hosted-stripe-test-local
```

Two checkouts are the prerequisite, and that is already true for anyone changing
the producer. The alternative is publishing a release per iteration, which is
the loop this exists to remove.

None of the six `HOSTED_PRODUCTION_*` identities apply to a producer built here.
There are none to supply, and supplying any is refused: the binding reads the
whole provenance group as a set, so all twelve coordinates present is a release,
all twelve empty is a build, and anything between is an environment that cannot
say which it is.

What a build made here still has to answer for is what it *serves*. The
conformance artifact `make artifacts` generates states the API version, the
schema, the funding profiles, and the capabilities, and the run asserts the
composed authority against them exactly as it does for a release. A missing
artifact fails the run before Compose creates anything, and names what is
missing rather than falling back to another release's coordinates.

A locally built producer never qualifies evidence. Naming one is by itself
enough to make the run a development run, with no separate flag and no way to
combine it with an attested claim.

One thing this does not do is teach the marketplace half to consume a newer
producer. The storefront and buyer configurations pin an expected API version,
schema, and capability set of their own, so binding a producer past what they
pin needs those configurations re-pointed too — a separate change, and a
separate decision.

### Development evidence never qualifies

A local run records `release_mode: local` in its evidence, derived from what it
actually bound rather than from the flag it was given. No argument produces an
attested record without an attested release, and a verification task that
requires protected evidence is not satisfied by a development run — the recorded
mode is enough to reject the citation without re-inspecting the run.

What a development run *is* good for: reproducing a failure, developing against
the real provider, and reading a diagnostic that a protected run would otherwise
surface only after a release.

### Prerequisites

- A container engine reachable as `docker`. With podman, put the shim on PATH
  for this project (`mise.local.toml` with `_.path = ["~/.config/podman-docker/bin"]`).
- A registry authentication file with no unusable credential helper in it.
  Podman consults every `credHelpers` entry in `~/.docker/config.json` when it
  resolves an image, including ones for registries this stack never touches; a
  helper whose session has expired (`gcloud`, for instance) makes stack bring-up
  fail one image at a time with no compose output, which reads as a hang. Either
  re-authenticate that helper or point the run at a file without it:

  ```sh
  export REGISTRY_AUTH_FILE="$rundir/auth.json"
  python -c 'import json,os,pathlib
  src = json.load(open(os.path.expanduser("~/.docker/config.json")))
  path = pathlib.Path(os.environ["REGISTRY_AUTH_FILE"])
  path.write_text(json.dumps({"auths": src.get("auths", {})}))
  path.chmod(0o600)'
  ```
- The Stripe CLI, used to forward webhooks to the loopback authority endpoint.
- Patience between interactive runs. After several automated Checkout sessions
  the provider answers with an interactive hCaptcha; the run detects it and
  fails at payer setup with `chromium_unavailable`. That is the provider
  responding to automation, not a defect, and it is not something to work
  around — wait, and run the interactive lanes sparingly.

  Which lanes those are is decided by whether the profile drives a
  Stripe-hosted page, not by the `interaction` argument:

  | Funding profile | Payer action | Automatable |
  | --- | --- | --- |
  | `us_bank_transfer.v1` | `bank_instructions`, funded through the cash-balance test helper | yes, headless throughout |
  | `card.v1` | hosted Checkout | only until hCaptcha appears |
  | `us_ach_debit.v1` | hosted Checkout via Financial Connections | no — the page presents no manual routing/account fields |

  A `us_bank_transfer.v1` run must quote the payer reference Stripe issues with
  the funding instructions when it funds the test cash balance. Funding without
  it simulates an unreferenced deposit, and the authority is right to open an
  attribution incident against it.

#### Reusing a payer fixture

A `saved_instrument` lane needs an instrument the payer profile already holds,
and the authority learns instruments one way only: a Checkout Session it
creates in `setup` mode. That session's SetupIntent cannot be confirmed through
the API — Stripe answers `You cannot confirm SetupIntents created by Checkout`
— so the setup page has to be completed by a person or a browser exactly once.

`HOSTED_STRIPE_TEST_RETAIN_AUTHORITY_STATE=1` keeps that once. It leaves the
authority's named volume in place at teardown, so the payer profile, its
instrument, and the account-owner binding survive into the next run. The
topology declares exactly one named volume and it is the authority's; every
other service keeps its state inside the container, so nothing about the
marketplace side of the previous run is inherited.

Two preconditions, both satisfied by generating credentials once and reusing
the same `--directory`:

- the buyer identity must not change, or the payer profile ref changes with it
  and the retained instrument belongs to a profile nothing looks up;
- the storefront identity must not change, or re-admitting the same
  `account_ref` under a new owner fails with `account_binding_conflict`.

A protected run refuses the flag. Evidence has to come from an authority that
remembers nothing.

The cache is one named volume, so any later run *without* the flag destroys it
and the next saved-instrument lane pays for the setup page again. Keep the flag
on for the whole series of runs that share a fixture. Anonymous volumes the
services bring with them are still removed on every retained teardown, so a
long series does not leak storage.

What it holds, and what to check when a lane behaves as though it does not:

```sh
podman run --rm -v vms_hosted-settlement-data:/data   --entrypoint python "$HOSTED_PRODUCTION_IMAGE" -c '
import sqlite3
c = sqlite3.connect("/data/hosted-settlement.sqlite3")
for t in ("payer_profiles", "payer_instruments", "payer_setups",
          "connected_accounts"):
    print(t, c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])'
```

A saved-instrument lane runs without a page only once `payer_instruments` is
non-empty. Until then the run opens a setup session, and Stripe answers a
sufficiently automated series of those with an interactive hCaptcha — a
throttle, not a defect. `HOSTED_STRIPE_TEST_VISIBLE_BROWSER=1` shows the window
rather than running Chromium headless, which is itself part of what the
provider is answering; on a throttled account it is not enough on its own, and
the remaining lever is time.
- Browsers for the interactive lanes: `uv run --project e2e-tests --extra
  stripe-test playwright install chromium`.
- The locally built consumer image (`arkhai:storefront`) and the released hosted
  service image at the digest the trust manifest pins.

### The credential broker

CI takes its credentials from a broker over GitHub OIDC. No implementation
exists in this repository; `docs/development/HOSTED_CREDENTIAL_PAYLOAD.md`
records the payload it must return, and the local assembler produces that same
shape. A broker written later substitutes for the assembler with no change to
the body.
