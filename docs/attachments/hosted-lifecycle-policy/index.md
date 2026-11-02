# Hosted lifecycle policy and snapshot verification — implementation evidence

Nonvisual library/CLI encounter (`visual: false`; no screenshots). This packet
records implementer first use, not independent acceptance or live hosted
qualification. It covers authority/hold derivation, exact buyer mandate checks,
hosted option publication and API-credit admission, and snapshot verification.

## Required environment and prepared target

The task requires the coherently vendored payments contract and the installed
mediation interface. Those packages are present as checkout-owned `.dist`
wheels. The actual prepared target is an isolated `uv run --no-project`
consumer of those wheels, not an editable package import, external authority or
resident server. No inherited deployment selector is reused.

Persona/authentication: the offline fixture's payer and payee, using public,
deterministic development accounts and signing keys explicitly marked never for
public-network use. Owner-scoped calls use the kit's fake client. No credential
or environment secret is required. The real hosted credential is not simulated
as a production approval.

State: each invocation creates its own fixed-clock in-memory authority and
approval. No shared database or remote seed is read or changed. Readiness is the
payments preflight plus successful installed resource/model imports, before any
approval. The observed command below exited zero.

## First-use entry point

From the repository root:

```sh
unset ALL_PROXY all_proxy
export NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1
make dist
uv run --no-project --find-links .dist \
  --with .dist/arkhai_kit_arkhai_payments-0.3.0-py3-none-any.whl \
  --with .dist/arkhai_kit_arkhai_mediation-0.1.0-py3-none-any.whl \
  --with .dist/arkhai_kit_storefront-0.10.0-py3-none-any.whl \
  python docs/attachments/hosted-lifecycle-policy/first_use.py
```

The committed [entry point](first_use.py) uses the actual public builder,
authority policy, buyer approval, shared authority fixture and snapshot verifier.
It was rerun from rebuilt wheels after the final code edits.

## Observed behavior

| Operation | Observation |
|---|---|
| Publish a hosted unit-priced option | Adjudication uses the first offered payments-compatible authority and participates in the option identity. |
| Publish with no offered authority | No hosted option is emitted. |
| Substitute an unsupported mechanism advertisement or uninstalled interface | Publication refuses. |
| Set the case hold to zero below the advertised minimum | Publication refuses, naming the cap. |
| Accept a different origin for an otherwise matching authority | Exact identity admission refuses. |
| Derive prepaid and setup once parts | Ends are the term end and Agreement start respectively, with afterStop dispute holds and authority-only extension caps. The authority clamps a setup end to later approval. |
| Derive rate permissions | Payer and payee entries preserve their priced notice/treatment; the dispute entry has zero notice and chosen treatment. Setup once parts beside those rate rights retain no stops. |
| Reorder the entitlements object | A temporary diagnostic produces identical permission lists: JSON object insertion order does not alter the derived mandate. |
| Add an unentitled seller stop | Buyer refuses before approval, despite a recomputed transaction ID. |
| Approve the unchanged mandate | Approval completes under the accepted Agreement and payer. |
| Verify snapshots | Correct signatures pass; tampered observations, wrong keys, changed modes, regressing sequences and signed-value coercion refuse. |
| Rotate the receipt identity | A current-key snapshot verifies under bounded history while the embedded old receipt and proof remain unchanged. A snapshot signed by the expired key refuses. |

Temporary diagnostics additionally exercised zero, bounded and unbounded hold
caps, setup alongside rate entitlements, fractional term ends, and all four
publisher snapshot frames. The fixture and production verifier now share one
snapshot framing function. No new permanent test function was added; kept test
setups/assertions were adapted to the deliberate wire behavior.

## Composition and constraints

- VM, bare-metal and API-credit storefront roots supply offered authority
  projections and the installed mediation interface to the common builder.
  The payments kit names no mediation vocabulary.
- One stored listing has one option set for its destination registries. The
  seller offers from the ordered intersection of their resolved authority
  lists, rather than importing one registry's defaults into another. Local
  authorities are resolved into every destination's list.
- Publication input explicitly supplies `dispute_window_seconds`, independent
  of the existing approval `window`. Omitting `case_hold_max_seconds` selects
  an unbounded case hold. Compute publication also requires a delivery deadline.
- API-credit buy and standalone negotiate filter against the listing's own
  registry policy; approval resolves and checks that authority again.
- Seller snapshot consumption retains an injectable per-agreement verifier
  factory, with the shared rotation-aware verifier as its default. A temporary
  diagnostic confirmed an injected refusal prevents seller admission.
- `receipt_identities` configures validity-bounded current/retiring pins; a
  retiring pin requires an end to its validity interval. A nonempty set must
  include the current `service_identity`. Existing single-pin configuration
  remains supported. Snapshot consumers supply their durable minimum sequence.
- Once-only mandate construction still emits one prepaid once part. The
  foundation's `derive_part_terms` supplies setup and rate mappings for later
  builders; it does not enable rate publication or setup presets itself.

## Validation

Commands unset both all-proxy variables and set both no-proxy variables to
loopback, as above.

- Payments: **97 passing existing cases**, mypy over 21 source/example files,
  generated-model/resource drift, producer vectors, four snapshot replays and
  nine scenario steps pass.
- VM storefront: **1,189 unit cases and 501 integration cases pass** (one existing
  unit skip). API-credit storefront: **248 pass**; API-credit buyer: **35 pass**.
- Bare-metal storefront: **522 pass** in the final aggregate. An earlier run
  exposed a fixture signing snapshots with a different key from its configured
  receipt signer. The fixture now injects that signer; both its focused rerun
  and the complete suite pass.
- API-credit wheel-only installation: **41 pass**, including storefront import
  without a raw source copy. Its explicit fixture wheelhouse now includes the
  newly composed mediation dependency.
- `make check-architecture`, `make check-packaging`, `make check-locks`,
  `make check-comment-hygiene` and pinned strict OpenSpec validation pass.
  Changed projects and the e2e consumer were relocked; Helm config schemas were
  regenerated from refreshed wheel environments. The release dependency table
  and publication manifest/workflow include mediation once. Two pre-existing
  duplicate lifecycle rows were removed from the release guide in a separate
  small cleanup commit.
- The first full `make test` reached API-credit wheel installation and exposed
  that fixture's missing mediation wheel. Its focused repair passes. The next
  aggregate passed all package suites and reached release-tooling, which exposed
  the missing mediation distribution in the publication manifest/workflow.
  Dependency closure is now recorded once in those lists and the release table;
  release-tooling and deployment packaging pass on focused rerun. The final
  full aggregate passes as recorded below.
- The scoped documentation citation check reports only the three known future
  lifecycle destinations tracked in [#325](https://github.com/arkhai-io/simple-compute-market/issues/325).

## Aggregate result

The final full **`make test` passes**, on 2026-11-02 in **7m 2s**, including all
package unit/application-integration suites, **1,848 release-tooling cases**, and
Helm render/structural identity assertions. Both all-proxy variables were unset;
both no-proxy variables contained loopback; the local Docker-compatible Podman
shim was opted into that shell only. The earlier failed attempts are recorded
above rather than represented as passing.

The final installed-wheel first-use command, strict OpenSpec validation,
packaging/architecture/lock checks and comment hygiene also pass. The working
branch contains only local commits; it was not pushed or rebased.

## Boundary and cleanup

No service, browser page, container, tunnel or remote deployment was created or
left running. Independent acceptance and deployed `e2e_credits_payment_deal` are
unrun: no owned, ready hosted target was supplied. This evidence is offline
contract/library and application integration, not the readiness-gated hosted
lane. Normative spec/architecture promotion and archival remain reviewed
closeout work; the active change records their permanent destinations.
